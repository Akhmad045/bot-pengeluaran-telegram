"""Pengujian v2.2: mutasi atomik, pergantian bulan, privasi, dan pemulihan nyata di folder sementara."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import ExpenseBot
from backups import (BackupManager, RuntimeLock, snapshot_database, restore_database,
                     prepare_restore, readonly, backup_before_upgrade)
from bot import deliver, load_owner, run_scheduled
from core import Store, ZONES
from test_bot import message, callback


class V22Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'main.db'
        self.store=Store(self.path); self.store.bind_bot(99)
        self.current=datetime(2026,9,22,12,tzinfo=timezone.utc)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current,owner_id=111)
        self.mid=100; self.qid=0

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def send(self,text,uid=111,mid=None):
        self.mid+=1
        return self.bot.handle(message(text,mid or self.mid,uid,stamp=self.current))

    def click(self,data,uid=111,qid=None):
        self.qid+=1
        return self.bot.handle_callback(callback(data,uid,qid=qid or f'new{self.qid}'))

    def edit(self,rid,field,value):
        self.click(f'editopen:{rid}'); token=self.store.pending(111)['token']
        self.click(f'editfield:{token}:{field}'); self.send(value)
        return self.click(f'editsave:{token}')

    def bulk(self,ids,filtered=False):
        self.click('bulkstart:search' if filtered else 'bulkstart:all')
        token=self.store.pending(111)['token']
        for rid in ids: self.click(f'bulktoggle:{token}:{rid}')
        return token

    def confirm_button(self,reply,prefix):
        return next(b['callback_data'] for row in reply.buttons for b in row if b['callback_data'].startswith(prefix))

    def repeat(self,month='2026-09'):
        reply=self.click(f'repeatask:{month}')
        return self.click(self.confirm_button(reply,'repeatyes:'))

    def test_main_menu_and_settings_have_expected_hierarchy(self):
        menu=self.send('/menu')
        actions=[b['callback_data'] for row in menu.buttons for b in row]
        self.assertEqual(actions,['add','history','reports','budget:2026-09','cash:2026-09','settings','menu'])
        settings=self.send('/pengaturan')
        self.assertIn('backup',[b['callback_data'] for row in settings.buttons for b in row])
        other=self.send('/pengaturan',uid=222)
        self.assertNotIn('backup',[b['callback_data'] for row in other.buttons for b in row])
        for command in ['/riwayat','/laporan','/riwayatedit','/pilih']:
            self.assertNotIn('tidak dikenal',self.send(command).text)

    def test_history_before_after_time_and_undo_update_both_months(self):
        self.send('25000 makan | Makanan')
        reply=self.edit(1,'spent_on','2026-08-31')
        change=self.store.changes(111)[0]
        self.assertIn('undoask:',json.dumps(reply.buttons))
        detail=self.click(f"change:{change['id']}")
        self.assertIn('Sebelum: 22 September 2026',detail.text)
        self.assertIn('Sesudah: 31 Agustus 2026',detail.text)
        self.assertIn('22-09-2026 19:00:00 WIB',detail.text)
        self.assertIn('Rp0',self.send('/bulanini').text)
        prompt=self.click(f"undoask:{change['id']}")
        self.assertEqual(self.store.get(111,1)['spent_on'],'2026-08-31')
        result=self.click(self.confirm_button(prompt,'undoyes:'),qid='undo-once')
        self.assertIn('berhasil diurungkan',result.text)
        self.assertEqual(self.store.get(111,1)['spent_on'],'2026-09-22')
        self.assertIn('Rp25.000',self.send('/bulanini').text)
        self.assertEqual(len(self.store.changes(111)),2)
        self.assertEqual(result.text,self.click('undoyes:1',qid='undo-once').text)
        self.assertEqual(len(self.store.changes(111)),2)

    def test_undo_is_private_and_rejects_changed_deleted_or_previously_undone(self):
        self.send('1000 kopi'); self.edit(1,'amount','2000')
        self.assertIn('tidak ditemukan',self.click('change:1',uid=222).text)
        self.assertIn('tidak bisa',self.click('undoask:1',uid=222).text)
        self.edit(1,'amount','3000')
        self.assertIn('sudah berubah',self.click('undoyes:1').text)
        self.click('undoyes:2')
        self.assertEqual(self.store.get(111,1)['amount'],2000)
        self.assertIn('sudah berubah',self.click('undoyes:2').text)
        self.edit(1,'note','kopi lain')
        change=self.store.changes(111)[0]
        self.store.set_deleted(111,1,True)
        self.assertFalse(self.store.undo_change(111,change['id'],self.current.isoformat()))

    def test_history_and_edit_rollback_together_if_receipt_fails(self):
        self.send('1000 kopi')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk failure')):
            values={'amount':2000,'note':'kopi','category':'Lainnya','spent_on':'2026-09-22'}
            with self.assertRaises(RuntimeError):
                with self.store.transaction():
                    self.store.edit_expense(111,1,0,values,self.current.isoformat())
                    self.store.save_receipt('x',111,'{}',0)
        self.assertEqual(self.store.get(111,1)['amount'],1000)
        self.assertEqual(len(self.store.changes(111)),0)

    def test_noop_edit_does_not_invent_history_or_revision(self):
        self.send('1000 kopi'); self.edit(1,'amount','1000')
        self.assertEqual(len(self.store.changes(111)),0)
        self.assertEqual(self.store.get(111,1)['revision'],0)

    def test_undo_and_audit_marker_roll_back_when_receipt_cannot_be_saved(self):
        self.send('1000 kopi'); self.edit(1,'amount','2000')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError): self.click('undoyes:1')
        self.assertEqual(self.store.get(111,1)['amount'],2000)
        self.assertIsNone(self.store.change(111,1)['undone_by'])
        self.assertEqual(len(self.store.changes(111)),1)
        self.assertIn('berhasil diurungkan',self.click('undoyes:1').text)

    def test_recurring_budget_starts_next_month_and_preserves_overrides(self):
        self.send('/anggaran 1,5jt'); self.send('/anggaran 2026-11 2jt')
        self.repeat()
        self.assertEqual(self.store.budget(111,'2026-10')['amount'],1500000)
        self.assertEqual(self.store.budget(111,'2026-10')['source'],'auto')
        self.assertEqual(self.store.budget(111,'2026-11')['amount'],2000000)
        self.assertEqual(self.store.budget(111,'2026-12')['amount'],1500000)
        self.assertIsNone(self.store.budget(222,'2026-10'))
        self.assertIsNone(self.store.budget(111,'2026-08'))

    def test_recurring_rollover_scheduler_and_alerts_survive_restart(self):
        self.send('/anggaran 1000'); self.repeat()
        self.store.close(); self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current,owner_id=111)
        self.current=datetime(2026,9,30,17,1,tzinfo=timezone.utc)
        api=Mock(); run_scheduled(api,self.bot)
        row=self.store.db.execute("SELECT * FROM budgets WHERE user_id=111 AND month='2026-10'").fetchone()
        self.assertEqual(row['amount'],1000)
        self.assertIn('Batas 80%',self.send('800 mulai bulan').text)
        self.assertNotIn('Batas 80%',self.send('10 lagi').text)

    def test_versioned_rules_preserve_past_amount_even_unopened_months(self):
        self.send('/anggaran 1jt'); self.repeat()
        self.current=datetime(2026,12,22,12,tzinfo=timezone.utc)
        self.send('/anggaran 2jt'); self.repeat('2026-12')
        self.assertEqual(self.store.budget(111,'2026-11')['amount'],1000000)
        self.assertEqual(self.store.budget(111,'2027-01')['amount'],2000000)
        prompt=self.click('repeatoffask:2027-01')
        self.click(self.confirm_button(prompt,'repeatoff:'))
        self.assertIsNone(self.store.budget(111,'2027-01'))
        self.assertEqual(self.store.budget(111,'2026-11')['amount'],1000000)
        self.assertEqual(self.store.budget(111,'2026-12')['amount'],2000000)

    def test_recurring_confirmation_rejected_after_month_rollover(self):
        self.send('/anggaran 1jt'); prompt=self.click('repeatask:2026-09')
        self.current+=timedelta(days=31)
        self.assertIn('Bulan sudah berganti',self.click(self.confirm_button(prompt,'repeatyes:')).text)
        self.assertIsNone(self.store.budget_rule(111,'2026-11'))

    def test_return_to_automatic_budget_keeps_alert_if_amount_unchanged(self):
        self.send('/anggaran 1000'); self.repeat()
        self.current=datetime(2026,10,3,12,tzinfo=timezone.utc)
        self.send('/anggaran 1000'); self.send('800 kopi')
        prompt=self.click('repeatresetask:2026-10')
        result=self.click(self.confirm_button(prompt,'repeatreset:'))
        self.assertNotIn('Batas 80%',result.text)
        self.assertEqual(self.store.budget(111,'2026-10')['source'],'auto')
        self.assertEqual(self.store.budget(111,'2026-10')['alert_level'],80)

    def test_bulk_selection_across_pages_and_soft_delete_requires_confirmation(self):
        self.send('\n'.join(f'1000 catatan {i}' for i in range(8)))
        token=self.bulk([8]); self.click(f'bulkpage:{token}:1'); self.click(f'bulktoggle:{token}:1')
        self.assertEqual(len(self.store.pending(111)['data']['selected']),2)
        preview=self.click(f'bulkaction:{token}:delete')
        self.assertIn('Total: Rp2.000',preview.text)
        self.assertEqual(len(self.store.history(111)),8)
        yes=self.confirm_button(preview,'bulkapply:')
        self.assertIn('2 catatan dihapus',self.click(yes,qid='bulkonce').text)
        self.assertEqual(len(self.store.history(111)),6)
        self.click(yes,qid='bulkonce')
        self.assertEqual(len(self.store.history(111,True)),2)
        self.click('restore:1:0')
        self.assertEqual(len(self.store.history(111)),7)

    def test_bulk_category_preview_history_and_individual_undo(self):
        self.send('1000 kopi\n2000 air\n3000 roti | Makanan')
        token=self.bulk([1,2,3]); self.click(f'bulkaction:{token}:category')
        self.assertIn('maksimal 32',self.send('x'*33).text)
        preview=self.send('MAKANAN')
        self.assertEqual(self.store.get(111,1)['category'],'Lainnya')
        self.click(self.confirm_button(preview,'bulkapply:'))
        self.assertEqual(self.store.get(111,1)['category'],'Makanan')
        self.assertEqual(len(self.store.changes(111)),2)
        self.assertEqual(self.store.changes(111)[0]['kind'],'bulk_category')
        self.click('undoyes:1')
        self.assertEqual(self.store.get(111,1)['category'],'Lainnya')
        self.assertEqual(self.store.get(111,2)['category'],'Makanan')

    def test_bulk_filter_cancel_expiry_and_cross_user_privacy(self):
        self.send('1000 bensin\n2000 roti'); self.send('3000 bensin rahasia',uid=222)
        self.send('/cari bensin'); token=self.bulk([1],filtered=True)
        view=self.click(f'bulkpage:{token}:0')
        self.assertNotIn('rahasia',view.text); self.assertNotIn('roti',view.text)
        self.assertIn('tidak tersedia',self.click(f'bulktoggle:{token}:3').text)
        self.assertIn('tidak aktif',self.click(f'bulkaction:{token}:delete',uid=222).text)
        preview=self.click(f'bulkaction:{token}:delete'); self.click('cancel')
        self.assertIn('tidak aktif',self.click(self.confirm_button(preview,'bulkapply:')).text)
        token=self.bulk([1]); self.current+=timedelta(minutes=31)
        self.assertIn('Waktu pengisian habis',self.send('5000 bukan transaksi').text)
        self.assertEqual(len(self.store.history(111)),2)

    def test_bulk_stale_record_rejects_whole_batch_without_partial_changes(self):
        self.send('1000 satu\n2000 dua'); token=self.bulk([1,2])
        preview=self.click(f'bulkaction:{token}:delete')
        self.store.set_deleted(111,2,True); self.store.set_deleted(111,2,False)
        result=self.click(self.confirm_button(preview,'bulkapply:'))
        self.assertIn('Belum ada perubahan disimpan',result.text)
        self.assertEqual(len(self.store.history(111)),2)
        self.assertEqual(self.store.get(111,1)['revision'],0)

    def test_bulk_old_confirmation_cannot_apply_new_selection(self):
        self.send('1000 satu\n2000 dua'); token=self.bulk([1])
        preview=self.click(f'bulkaction:{token}:delete')
        old=self.confirm_button(preview,'bulkapply:')
        self.click(f'bulkback:{token}'); self.click(f'bulktoggle:{token}:2')
        newer=self.click(f'bulkaction:{token}:delete')
        self.assertIn('Konfirmasi sudah tidak aktif',self.click(old).text)
        self.assertEqual(len(self.store.history(111)),2)
        self.click(self.confirm_button(newer,'bulkapply:'))
        self.assertEqual(len(self.store.history(111)),0)

    def test_bulk_limit_and_all_or_nothing_on_storage_failure(self):
        self.send('\n'.join(f'1000 catatan {i}' for i in range(51)))
        token=self.bulk(range(1,51))
        self.assertIn('Maksimal 50',self.click(f'bulktoggle:{token}:51').text)
        self.assertEqual(len(self.store.pending(111)['data']['selected']),50)
        self.send('/batal'); token=self.bulk([1,2]); preview=self.click(f'bulkaction:{token}:delete')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError): self.click(self.confirm_button(preview,'bulkapply:'))
        self.assertEqual(len(self.store.history(111)),51)
        self.assertIsNotNone(self.store.pending(111))

    def test_bulk_draft_survives_restart_and_category_text_not_new_expense(self):
        self.send('1000 satu'); token=self.bulk([1]); self.click(f'bulkaction:{token}:category')
        self.store.close(); self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current,owner_id=111)
        preview=self.send('5000 Belanja',mid=777)
        self.assertEqual(preview.text,self.send('5000 Belanja',mid=777).text)
        self.click(self.confirm_button(preview,'bulkapply:'))
        self.assertEqual(len(self.store.history(111)),1)
        self.assertEqual(self.store.get(111,1)['category'],'5000 belanja')

    def test_backup_owner_check_happens_before_replaying_saved_receipt(self):
        reply=self.click('backupdownload',qid='download')
        self.assertTrue(reply.backup_request)
        self.bot.owner_id=222
        self.assertFalse(self.click('backupdownload',qid='download').backup_request)
        self.assertIn('hanya dapat',self.send('/cadangan').text)

    def test_backup_delivery_outside_transaction_and_sqlite_mime(self):
        self.send('1000 kopi'); manager=BackupManager(self.store,111)
        api=Mock(); reply=self.click('backupdownload')
        self.assertFalse(self.store.db.in_transaction)
        deliver(api,self.store,111,reply,backup_manager=manager)
        document=api.send_document.call_args.args[1]
        self.assertEqual(document.mime_type,'application/vnd.sqlite3')
        self.assertTrue(document.content.startswith(b'SQLite format 3'))
        api.reset_mock(); deliver(api,self.store,222,reply,backup_manager=manager)
        api.send_document.assert_not_called()

    def test_all_new_callbacks_fit_64_utf8_bytes(self):
        self.send('1000 '+'字'*160+' | '+'界'*32); self.send('/anggaran 1jt')
        self.edit(1,'amount','2000')
        replies=[self.send('/menu'),self.send('/pengaturan'),self.send('/riwayatedit'),self.click('change:1'),
                 self.click('repeatask:2026-09'),self.send('/pilih')]
        token=self.store.pending(111)['token']; self.click(f'bulktoggle:{token}:1')
        replies.append(self.click(f'bulkaction:{token}:delete'))
        for reply in replies:
            for row in reply.buttons:
                for b in row: self.assertLessEqual(len(b['callback_data'].encode()),64)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.path=self.root/'original.db'; self.store=Store(self.path); self.store.bind_bot(99)
        self.current=datetime(2026,9,22,12,tzinfo=timezone.utc)
        self.bot=ExpenseBot(self.store,{111},ZONES['WIB'],clock=lambda:self.current)
        self.bot.handle(message('1000 kopi\n2000 roti',100,stamp=self.current))
        self.copy=self.root/'backup.db'

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_live_snapshot_includes_committed_wal_data_and_rejects_open_transaction(self):
        self.store.db.execute('PRAGMA journal_mode=WAL')
        self.bot.handle(message('3000 air',101,stamp=self.current))
        snapshot_database(self.store.db,self.copy)
        with closing(readonly(self.copy)) as db:
            self.assertEqual(db.execute('SELECT SUM(amount) FROM expenses').fetchone()[0],6000)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        with self.store.transaction(),self.assertRaises(ValueError): snapshot_database(self.store.db,self.copy)

    def test_daily_startup_schedule_retention_and_manual_files(self):
        manager=BackupManager(self.store,111)
        now=datetime(2026,9,1,2,tzinfo=ZONES['WIB'])
        first=manager.ensure_daily(now)
        self.assertEqual(first.name,'auto-2026-08-31.db')
        self.assertIsNone(manager.ensure_daily(now))
        next_file=manager.ensure_daily(now.replace(hour=3))
        self.assertEqual(next_file.name,'auto-2026-09-01.db')
        manual=manager.manual(now)
        for i in range(2,21): manager.ensure_daily(now.replace(day=i,hour=4))
        self.assertEqual(len(list(manager.folder.glob('auto-*.db'))),14)
        self.assertTrue(manual.exists())
        restart=BackupManager(self.store,111)
        restart.ensure_daily(now.replace(day=20,hour=5))
        self.assertEqual(len(list(manager.folder.glob('auto-*.db'))),14)

    def test_failed_backup_never_replaces_successful_snapshot(self):
        snapshot_database(self.store.db,self.copy); before=self.copy.read_bytes()
        with patch('backups.check_integrity',side_effect=ValueError('corrupt')):
            with self.assertRaises(ValueError): snapshot_database(self.store.db,self.copy)
        self.assertEqual(before,self.copy.read_bytes())
        self.assertEqual(list(self.root.glob('.snapshot-*')),[])

    def test_retention_cleanup_failure_retries_after_five_minutes(self):
        manager=BackupManager(self.store,111)
        for day in range(1,15): manager.ensure_daily(self.current.replace(day=day))
        original_unlink=Path.unlink
        def unlink(path,*args,**kwargs):
            if path.name.startswith('auto-'): raise OSError('file busy')
            return original_unlink(path,*args,**kwargs)
        with patch('pathlib.Path.unlink',new=unlink):
            manager.ensure_daily(self.current)
        self.assertIsNotNone(manager.last_error)
        manager.ensure_daily(self.current+timedelta(minutes=6))
        self.assertIsNone(manager.last_error)
        self.assertEqual(len(list(manager.folder.glob('auto-*.db'))),14)

    def test_automatic_failure_retries_without_stopping_bot_and_repairs_corrupt_file(self):
        manager=BackupManager(self.store,111)
        with patch('backups.snapshot_database',side_effect=OSError('full')):
            manager.ensure_daily(self.current)
        self.assertIsNotNone(manager.last_error)
        self.assertIsNone(manager.ensure_daily(self.current+timedelta(seconds=100)))
        good=manager.ensure_daily(self.current+timedelta(minutes=6))
        self.assertTrue(good.exists()); self.assertIsNone(manager.last_error)
        good.write_bytes(b'bad')
        restarted=BackupManager(self.store,111); restarted.ensure_daily(self.current)
        with closing(readonly(good)) as db: self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_restore_roundtrip_preserves_full_data_and_discards_stale_forms(self):
        self.store.edit_expense(111,1,0,{'amount':3000,'note':'kopi','category':'Minum','spent_on':'2026-09-22'},self.current.isoformat())
        self.store.set_deleted(111,2,True); self.store.set_zone(111,'WITA')
        self.store.set_budget(111,'2026-09',100000)
        self.store.set_budget_rule(111,'2026-10',150000,self.current.isoformat())
        self.store.set_reminder(111,'21:00',True,int(self.current.timestamp())+7200)
        self.store.start_pending(111,'edit',{},int(self.current.timestamp()))
        snapshot_database(self.store.db,self.copy)
        target=self.root/'moved.db'
        result=restore_database(self.copy,target,lambda info:True)
        self.assertEqual(result['summary'],{'active':1,'deleted':1,'changes':1,'users':1,'bot_id':'99','incomes':0,'transfers':0,'wallets':1})
        restored=Store(target)
        try:
            self.assertEqual(restored.get(111,1)['amount'],3000)
            self.assertTrue(restored.get(111,2)['deleted'])
            self.assertEqual(restored.get_zone(111,ZONES['WIB']),ZONES['WITA'])
            self.assertEqual(restored.budget(111,'2026-10')['amount'],150000)
            self.assertTrue(restored.reminder(111)['enabled'])
            self.assertIsNone(restored.pending(111))
            self.assertEqual(restored.db.execute('SELECT COUNT(*) FROM event_receipts').fetchone()[0],0)
            self.assertTrue(restored.undo_change(111,1,self.current.isoformat()))
        finally: restored.close()

    def test_restore_creates_previous_snapshot_and_can_recover_it(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'target.db'; old=Store(target); old.bind_bot(99)
        old_bot=ExpenseBot(old,{111},ZONES['WIB'],clock=lambda:self.current)
        old_bot.handle(message('9000 lama',400,stamp=self.current)); old.close()
        result=restore_database(self.copy,target,lambda summary:True)
        with closing(readonly(result['previous'])) as previous:
            self.assertEqual(previous.execute('SELECT amount FROM expenses').fetchone()[0],9000)
        restore_database(result['previous'],target,lambda summary:True)
        with closing(readonly(target)) as db: self.assertEqual(db.execute('SELECT amount FROM expenses').fetchone()[0],9000)

    def test_invalid_or_foreign_backup_and_cancellation_leave_target_unchanged(self):
        target=self.root/'target.db'; old=Store(target); old.bind_bot(88); old.close()
        before=target.read_bytes(); snapshot_database(self.store.db,self.copy)
        with self.assertRaisesRegex(ValueError,'bot berbeda'): restore_database(self.copy,target,lambda s:True)
        self.assertEqual(before,target.read_bytes())
        self.copy.write_bytes(b'PK excel not db')
        with self.assertRaisesRegex(ValueError,'bukan laporan Excel'): restore_database(self.copy,target,lambda s:True)
        self.assertEqual(before,target.read_bytes())
        target.unlink(); snapshot_database(self.store.db,self.copy)
        self.assertIsNone(restore_database(self.copy,target,lambda s:False))
        self.assertFalse(target.exists())

    def test_extra_trigger_is_rejected_without_executing_it(self):
        snapshot_database(self.store.db,self.copy)
        with closing(sqlite3.connect(self.copy)) as db:
            db.execute('CREATE TRIGGER unwanted AFTER INSERT ON expenses BEGIN DELETE FROM expenses; END;'); db.commit()
        target=self.root/'target.db'
        with self.assertRaisesRegex(ValueError,'Skema'): restore_database(self.copy,target,lambda s:True)
        self.assertFalse(target.exists())

    def test_corrupt_target_is_preserved_as_raw_copy_before_recovery(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'broken.db'; target.write_bytes(b'broken original database')
        result=restore_database(self.copy,target,lambda s:True)
        self.assertEqual(result['previous'].read_bytes(),b'broken original database')
        with closing(readonly(target)) as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0],2)

    def test_running_lock_blocks_second_bot_and_restore(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'locked.db'
        with RuntimeLock(target):
            with self.assertRaisesRegex(ValueError,'sedang digunakan'):
                with RuntimeLock(target): pass
            with self.assertRaisesRegex(ValueError,'sedang digunakan'):
                restore_database(self.copy,target,lambda s:True)
        self.assertIsNotNone(restore_database(self.copy,target,lambda s:True))

    def test_failed_replace_keeps_existing_database(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'target.db'; old=Store(target); old.bind_bot(99); old.close()
        before=target.read_bytes(); original_replace=os.replace
        def replace(src,dst):
            if Path(dst)==target: raise OSError('replace denied')
            return original_replace(src,dst)
        with patch('backups.os.replace',side_effect=replace):
            with self.assertRaises(OSError): restore_database(self.copy,target,lambda s:True)
        self.assertEqual(before,target.read_bytes())

    def test_old_journal_never_returns_after_successful_restore_if_cleanup_fails(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'broken.db'; target.write_bytes(b'broken')
        journal=Path(str(target)+'-wal'); journal.write_bytes(b'old journal bytes')
        original_unlink=Path.unlink
        def unlink(path,*args,**kwargs):
            if str(path).endswith('.old'): raise OSError('cleanup denied')
            return original_unlink(path,*args,**kwargs)
        with patch('pathlib.Path.unlink',new=unlink):
            result=restore_database(self.copy,target,lambda s:True)
        self.assertIsNotNone(result)
        self.assertFalse(journal.exists())
        with closing(readonly(target)) as db:
            self.assertEqual(db.execute('SELECT SUM(amount) FROM expenses').fetchone()[0],3000)

    def test_owner_config_autodetect_and_validation(self):
        config=self.root/'config.json'; config.write_text('{}')
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(load_owner(config,{111}),111)
            self.assertIsNone(load_owner(config,{111,222}))
            config.write_text(json.dumps({'owner_user_id':222}))
            self.assertEqual(load_owner(config,{111,222}),222)
            with self.assertRaises(ValueError): load_owner(config,{111})

    def test_restore_after_crash_preserves_wal_contents_in_recovery_copy(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'crashed.db'
        script='''import os,sys
from core import Store
s=Store(sys.argv[1]); s.bind_bot(99)
s.db.execute("PRAGMA journal_mode=WAL")
s.db.execute("INSERT INTO expenses(user_id,chat_id,message_id,spent_on,amount,note,category,created_at) VALUES(111,111,500,'2026-09-22',9000,'wal','Lainnya','2026-09-22T12:00:00+00:00')")
s.db.commit()
os._exit(0)
'''
        subprocess.run([sys.executable,'-c',script,str(target)],check=True,cwd=Path(__file__).parent)
        self.assertTrue(Path(str(target)+'-wal').exists())
        result=restore_database(self.copy,target,lambda s:True)
        with closing(readonly(result['previous'])) as old:
            self.assertEqual(old.execute('SELECT amount FROM expenses').fetchone()[0],9000)
        with closing(readonly(target)) as new:
            self.assertEqual(new.execute('SELECT SUM(amount) FROM expenses').fetchone()[0],3000)
        self.assertFalse(Path(str(target)+'-wal').exists())

    def test_invalid_data_and_failed_recovery_backup_leave_original_intact(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'safe.db'; old=Store(target); old.bind_bot(99); old.close()
        before=target.read_bytes()
        with patch('backups.snapshot_database',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): restore_database(self.copy,target,lambda s:True)
        self.assertEqual(target.read_bytes(),before)
        with closing(sqlite3.connect(self.copy)) as db:
            db.execute('UPDATE expenses SET amount=1000000000001'); db.commit()
        with self.assertRaisesRegex(ValueError,'Nominal'): restore_database(self.copy,target,lambda s:True)
        self.assertEqual(target.read_bytes(),before)

    def test_restore_cli_confirms_and_handles_paths_with_spaces(self):
        snapshot_database(self.store.db,self.copy)
        target=self.root/'folder baru'/'pengeluaran baru.db'
        result=subprocess.run([sys.executable,'cadangan.py','restore',str(self.copy),'--database',str(target)],
                              input='PULIHKAN\n',text=True,capture_output=True,cwd=Path(__file__).parent,
                              env={**os.environ,'PYTHONUTF8':'1'})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Pemulihan berhasil',result.stdout)
        with closing(readonly(target)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM expenses').fetchone()[0],2)

    def test_v21_migration_keeps_data_budget_alerts_and_pre_upgrade_copy(self):
        oldpath=self.root/'v21.db'
        with closing(sqlite3.connect(oldpath)) as db:
            db.executescript('''CREATE TABLE expenses(id INTEGER PRIMARY KEY,user_id INTEGER,chat_id INTEGER,message_id INTEGER,
                line_no INTEGER,spent_on TEXT,amount INTEGER,note TEXT,category TEXT,created_at TEXT,deleted INTEGER,revision INTEGER);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO metadata VALUES('bot_id','99');
                CREATE TABLE budgets(user_id INTEGER,month TEXT,amount INTEGER,alert_level INTEGER,PRIMARY KEY(user_id,month));
                INSERT INTO budgets VALUES(111,'2026-09',1000,80);
                INSERT INTO expenses VALUES(17,111,111,10,0,'2026-09-01',800,'kopi','Lainnya','2026-09-01T00:00:00+07:00',0,3);''')
        previous=backup_before_upgrade(oldpath)
        self.assertTrue(previous.exists())
        migrated=Store(oldpath)
        try:
            self.assertEqual(migrated.get(111,17)['revision'],3)
            self.assertEqual(migrated.budget(111,'2026-09')['alert_level'],80)
            self.assertEqual(migrated.budget(111,'2026-09')['source'],'manual')
            self.assertEqual(migrated.changes(111),[])
            self.assertIsNone(backup_before_upgrade(oldpath))
        finally: migrated.close()
        restored=restore_database(previous,self.root/'legacy-restore.db',lambda s:True)
        self.assertEqual(restored['summary']['active'],1)


if __name__=='__main__': unittest.main(verbosity=2)
