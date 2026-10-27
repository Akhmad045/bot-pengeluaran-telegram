"""Uji perilaku fitur 2.3 tanpa menghubungi Telegram atau memakai database pengguna."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import ExpenseBot
from backups import snapshot_database, restore_database, readonly, backup_before_upgrade
from bot import APIError, run_polling, run_scheduled
from core import Store, ZONES
from schedule_v23 import (bill_due, first_bill_month, make_summary, report_due, report_window,
                          send_scheduled_reports, send_bill_reminders)
from storage_v23 import V23_TABLES
from test_bot import message, callback, xml_sheet, cell, NS


class SmartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.path=self.root/'data.db'
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
        return self.bot.handle_callback(callback(data,uid,qid=qid or f'smart{self.qid}'))

    def restart(self):
        self.store.close(); self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current,owner_id=111)

    def action(self,reply,prefix):
        return next(b['callback_data'] for row in reply.buttons for b in row if b['callback_data'].startswith(prefix))

    def favorite(self,title='Bensin',expense='50rb bensin | Transportasi',uid=111):
        self.click('favform:0',uid); self.send(title,uid); preview=self.send(expense,uid)
        self.click(self.action(preview,'formsave:'),uid)
        return self.store.favorite_rows(uid)[-1]['id']

    def bill(self,title='Internet',expense='300rb internet | Tagihan',day='25',at='09:00',uid=111):
        self.click('billform:0',uid); self.send(title,uid); self.send(expense,uid); self.send(day,uid)
        preview=self.send(at,uid); self.click(self.action(preview,'formsave:'),uid)
        return self.store.bill_rows(uid)[-1]['id']

    def set_limit(self,category,amount,month='2026-09',uid=111):
        self.click('catbudgetnew:'+month,uid); self.send(category,uid); return self.send(amount,uid)

    def change(self,rid,field,value):
        self.click(f'editopen:{rid}'); token=self.store.pending(111)['token']
        self.click(f'editfield:{token}:{field}'); self.send(value)
        return self.click(f'editsave:{token}')

    def test_rules_classify_batch_and_explicit_categories_win(self):
        self.send('50rb BENSIN motor\n20rb makan siang\n15rb minum | Pribadi\n10rb makan | Lainnya\n1 barang lain')
        rows=self.store.history(111)
        self.assertEqual([r['category'] for r in reversed(rows)],['Transportasi','Makanan','Pribadi','Lainnya','Lainnya'])
        self.assertEqual(sum(r['amount'] for r in rows),95001)

    def test_rule_matching_uses_whole_phrases_longest_first_and_literal_symbols(self):
        self.click('ruleform:0'); self.send('makan siang | Kantor')
        self.send('1000 makan siang\n1000 makanan\n1000 pemakan')
        self.assertEqual(self.store.get(111,1)['category'],'Kantor')
        self.assertEqual(self.store.get(111,2)['category'],'Lainnya')
        self.assertEqual(self.store.get(111,3)['category'],'Lainnya')
        self.click('ruleform:0'); self.send('café | Minuman')
        self.send('1000 CAFÉ')
        self.assertEqual(self.store.get(111,4)['category'],'Minuman')

    def test_rule_edit_delete_toggle_and_private_settings_survive_restart(self):
        self.store.rules(111)
        rule=next(r for r in self.store.rules(111) if r['keyword']=='bensin')
        self.click(f"ruleform:{rule['id']}"); self.send('bensin | Kendaraan')
        self.send('1000 bensin'); self.send('1000 bensin',uid=222)
        self.assertEqual(self.store.get(111,1)['category'],'Kendaraan')
        self.assertEqual(self.store.get(222,2)['category'],'Transportasi')
        self.click('ruletoggle:0'); self.restart(); self.send('1000 bensin')
        self.assertEqual(self.store.get(111,3)['category'],'Lainnya')
        self.click('ruletoggle:1'); prompt=self.click(f"ruledeleteask:{rule['id']}")
        self.click(self.action(prompt,'ruledelete:')); self.restart()
        self.assertFalse(any(r['keyword']=='bensin' for r in self.store.rules(111)))
        self.assertEqual(self.store.get(111,1)['category'],'Kendaraan')

    def test_rule_invalid_duplicate_and_cross_user_changes_do_not_write(self):
        self.click('ruleform:0')
        self.assertIn('kata | kategori',self.send('tanpa pemisah').text)
        self.assertIn('sudah memiliki',self.send('BENSIN | Baru').text)
        self.assertIsNotNone(self.store.pending(111))
        rid=self.store.rules(111)[0]['id']
        self.assertIn('tidak ditemukan',self.click(f'ruleview:{rid}',uid=222).text)
        self.assertIn('sudah berubah',self.click(f'ruledelete:{rid}:0',uid=222).text)

    def test_favorite_creation_is_not_expense_and_use_requires_confirmation(self):
        self.click('favform:0'); self.send('Bensin'); preview=self.send('50rb bensin')
        self.assertEqual(self.store.favorite_rows(111),[])
        self.assertEqual(self.store.history(111),[])
        self.click(self.action(preview,'formsave:'))
        self.assertEqual(self.store.history(111),[])
        preview=self.click('favuse:1'); self.assertEqual(self.store.history(111),[])
        self.assertIn('22 September 2026',preview.text)
        result=self.click(self.action(preview,'quickcommit:'))
        self.assertIn('Tercatat 1',result.text)
        row=self.store.get(111,1)
        self.assertEqual((row['amount'],row['category'],row['spent_on']),(50000,'Transportasi','2026-09-22'))
        exported=self.send('/excel').document
        self.assertEqual(cell(xml_sheet(exported.content,1),'B5').find('s:v',NS).text,'50000')

    def test_favorite_cancel_expiry_and_invalid_form_never_record(self):
        self.click('favform:0'); self.send('Favorit')
        for text in ['0 kopi','1000 satu\n1000 dua','2026-09-21 1000 kemarin']:
            self.assertIn('Kirim ulang',self.send(text).text)
        self.send('/batal'); self.assertEqual(self.store.favorite_rows(111),[])
        rid=self.favorite(); preview=self.click(f'favuse:{rid}'); self.click('cancel')
        self.assertIn('tidak aktif',self.click(self.action(preview,'quickcommit:')).text)
        self.click(f'favuse:{rid}'); self.current+=timedelta(minutes=31)
        self.assertIn('Waktu pengisian habis',self.send('1000 kopi').text)
        self.assertEqual(self.store.history(111),[])

    def test_favorite_edit_values_and_repeated_use_are_intentional(self):
        rid=self.favorite(); self.click(f'favform:{rid}'); self.send('Bensin hemat'); preview=self.send('40rb isi bensin | Transportasi')
        self.click(self.action(preview,'formsave:'))
        first=self.click(f'favuse:{rid}'); self.click(self.action(first,'quickcommit:'),qid='same-confirmation')
        self.restart(); self.click(self.action(first,'quickcommit:'),qid='same-confirmation')
        self.assertEqual(len(self.store.history(111)),1)
        second=self.click(f'favuse:{rid}'); self.click(self.action(second,'quickcommit:'))
        self.assertEqual(len(self.store.history(111)),2)
        self.assertEqual(self.store.get(111,1)['amount'],40000)

    def test_quick_amount_and_date_changes_invalidate_old_confirmation(self):
        rid=self.favorite(); initial=self.click(f'favuse:{rid}'); old=self.action(initial,'quickcommit:')
        token=self.store.pending(111)['token']
        self.click(f'quickfield:{token}:amount'); preview=self.send('60rb')
        self.assertIn('Tinjauan sudah berubah',self.click(old).text)
        self.click(f'quickfield:{token}:spent_on')
        self.assertIn('masa depan',self.send('2026-09-23').text)
        preview=self.send('2026-09-21'); self.click(self.action(preview,'quickcommit:'))
        self.assertEqual(self.store.get(111,1)['amount'],60000)
        self.assertEqual(self.store.get(111,1)['spent_on'],'2026-09-21')
        self.assertEqual(self.store.owned('favorites',111,rid)['amount'],50000)

    def test_favorite_stale_deleted_or_foreign_templates_are_rejected(self):
        rid=self.favorite(); preview=self.click(f'favuse:{rid}')
        self.assertIn('tidak ditemukan',self.click(f'favuse:{rid}',uid=222).text)
        self.store.remove_owned('favorites',111,rid,0)
        self.assertIn('tidak ditemukan',self.click(self.action(preview,'quickcommit:')).text)
        self.assertEqual(self.store.history(111),[])

    def test_quick_receipt_failure_rolls_back_expense_source_and_keeps_draft(self):
        rid=self.favorite(); preview=self.click(f'favuse:{rid}')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('full disk')):
            with self.assertRaises(RuntimeError): self.click(self.action(preview,'quickcommit:'))
        self.assertEqual(self.store.history(111),[])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM expense_sources').fetchone()[0],0)
        self.assertIsNotNone(self.store.pending(111))
        self.click(self.action(preview,'quickcommit:'))
        self.assertEqual(len(self.store.history(111)),1)

    def test_category_budget_thresholds_and_total_budget_are_independent(self):
        self.send('/anggaran 1000'); self.set_limit('Makanan','500')
        result=self.send('400 makan')
        self.assertIn('KATEGORI Makanan',result.text); self.assertIn('Batas 80%',result.text)
        self.assertNotIn('🔔 ANGGARAN',result.text)
        self.assertIn('Batas 100%',self.send('100 makan').text)
        self.assertNotIn('KATEGORI Makanan',self.send('1 makan').text)
        total=self.send('499 bensin')
        self.assertIn('🔔 ANGGARAN',total.text); self.assertIn('Batas 100%',total.text)

    def test_category_limits_are_private_per_month_and_copy_does_not_overwrite(self):
        self.set_limit('Makanan','1000','2026-08'); self.set_limit('Transportasi','2000','2026-08')
        self.set_limit('Makanan','3000'); self.set_limit('Makanan','9000',uid=222)
        self.click('catbudgetcopy:2026-09')
        rows={r['category']:r['amount'] for r in self.store.category_limits(111,'2026-09')}
        self.assertEqual(rows,{'Makanan':3000,'Transportasi':2000})
        self.assertEqual(self.store.category_limits(222,'2026-09')[0]['amount'],9000)
        self.assertEqual(self.store.category_limits(111,'2026-10'),[])

    def test_category_budget_edit_move_undo_and_bulk_recalculate_alerts(self):
        self.set_limit('Makanan','1000')
        self.send('800 barang | Lainnya')
        reply=self.change(1,'category','Makanan')
        self.assertIn('Batas 80%',reply.text)
        self.click('undoyes:1')
        self.assertIn('Rp0 / Rp1.000',self.send('/anggarankategori').text)
        self.set_limit('Transportasi','500')
        self.click('bulkstart:all'); token=self.store.pending(111)['token']
        self.click(f'bulktoggle:{token}:1'); self.click(f'bulkaction:{token}:category')
        preview=self.send('Transportasi'); reply=self.click(self.action(preview,'bulkapply:'))
        self.assertIn('KATEGORI Transportasi',reply.text); self.assertIn('Batas 100%',reply.text)

    def test_category_limit_delete_confirms_and_cannot_delete_other_users(self):
        self.set_limit('Makanan','500'); rid=self.store.category_limits(111,'2026-09')[0]['id']
        prompt=self.click(f'catbudgetdelask:{rid}')
        self.assertEqual(len(self.store.category_limits(111,'2026-09')),1)
        self.assertIn('tidak ditemukan',self.click(self.action(prompt,'catbudgetdel:'),uid=222).text)
        self.click(self.action(prompt,'catbudgetdel:'))
        self.assertEqual(self.store.category_limits(111,'2026-09'),[])

    def test_favorite_and_bill_payment_both_trigger_category_budget_notice(self):
        self.set_limit('Transportasi','50000'); rid=self.favorite()
        preview=self.click(f'favuse:{rid}'); self.assertIn('KATEGORI Transportasi',self.click(self.action(preview,'quickcommit:')).text)
        self.set_limit('Tagihan','300000'); rid=self.bill()
        preview=self.click(f'billpay:{rid}:2026-09'); self.assertIn('KATEGORI Tagihan',self.click(self.action(preview,'quickcommit:')).text)

    def test_reports_are_opt_in_and_preview_does_not_mark_scheduled_job(self):
        self.send('1000 kopi'); self.send('/rekapotomatis')
        self.assertFalse(self.store.report_setting(111,'weekly')['enabled'])
        api=Mock(); send_scheduled_reports(api,self.bot); api.send.assert_not_called()
        self.click('reportpreview:weekly')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM report_jobs').fetchone()[0],0)

    def test_weekly_report_period_totals_categories_and_excel_are_private(self):
        self.current=datetime(2026,9,27,12,tzinfo=timezone.utc)
        self.send('2026-09-14 500 pembanding\n2026-09-21 1000 bensin\n2026-09-27 2000 makan')
        self.send('999999 rahasia',uid=222)
        self.click('reportexcel:weekly:1'); reply=self.click('reportpreview:weekly')
        self.assertIn('14 September 2026 – 20 September 2026',reply.text)
        self.current+=timedelta(days=1)
        reply=self.click('reportpreview:weekly')
        self.assertIn('Total: Rp3.000',reply.text); self.assertIn('Naik Rp2.500 (500,0%)',reply.text)
        self.assertIn('Makanan: Rp2.000',reply.text); self.assertNotIn('rahasia',reply.text)
        self.assertEqual(cell(xml_sheet(reply.document.content,1),'B5').find('s:v',NS).text,'3000')

    def test_weekly_delivery_waits_for_next_schedule_and_survives_restart(self):
        self.click('reporttoggle:weekly:1'); api=Mock()
        send_scheduled_reports(api,self.bot); api.send.assert_not_called()
        self.current=datetime(2026,9,27,23,59,tzinfo=timezone.utc) # Senin 06:59 WIB.
        send_scheduled_reports(api,self.bot); api.send.assert_not_called()
        self.current+=timedelta(minutes=1)
        send_scheduled_reports(api,self.bot); self.assertEqual(api.send.call_count,1)
        self.restart(); send_scheduled_reports(api,self.bot); self.assertEqual(api.send.call_count,1)
        self.current+=timedelta(days=7); send_scheduled_reports(api,self.bot)
        self.assertEqual(api.send.call_count,2)

    def test_monthly_schedule_uses_user_zone_and_last_complete_month(self):
        self.click('zone:WIT'); self.click('reporttoggle:monthly:1'); api=Mock()
        self.current=datetime(2026,9,30,21,59,tzinfo=timezone.utc)
        send_scheduled_reports(api,self.bot); api.send.assert_not_called()
        self.current+=timedelta(minutes=1)
        send_scheduled_reports(api,self.bot); self.assertEqual(api.send.call_count,1)
        self.assertIn('1 September 2026 – 30 September 2026',api.send.call_args.args[1])

    def test_offline_report_catches_up_latest_period_only(self):
        self.click('reporttoggle:weekly:1'); self.click('reporttoggle:monthly:1'); api=Mock()
        self.current=datetime(2027,1,20,12,tzinfo=timezone.utc)
        send_scheduled_reports(api,self.bot)
        self.assertEqual(api.send.call_count,2)
        messages='\n'.join(call.args[1] for call in api.send.call_args_list)
        self.assertIn('1 Desember 2026 – 31 Desember 2026',messages)
        self.assertIn('11 Januari 2027 – 17 Januari 2027',messages)

    def test_excel_retry_does_not_resend_summary_and_snapshot_stays_fixed(self):
        self.click('reporttoggle:weekly:1'); self.click('reportexcel:weekly:1')
        self.send('1000 kopi'); self.current=datetime(2026,9,28,1,tzinfo=timezone.utc)
        api=Mock(); api.send_document.side_effect=APIError(429)
        with self.assertRaises(APIError): send_scheduled_reports(api,self.bot)
        self.assertEqual(api.send.call_count,1)
        self.send('2026-09-22 9000 terlambat dicatat')
        self.restart(); api.send_document.side_effect=None
        send_scheduled_reports(api,self.bot)
        self.assertEqual(api.send.call_count,1)
        doc=api.send_document.call_args.args[1]
        self.assertEqual(cell(xml_sheet(doc.content,1),'B5').find('s:v',NS).text,'1000')
        job=self.store.report_job(111,'weekly','2026-09-21')
        self.assertTrue(job['completed']); self.assertIsNone(job['excel'])

    def test_turning_excel_off_cancels_pending_attachment(self):
        self.click('reporttoggle:weekly:1'); self.click('reportexcel:weekly:1')
        self.current=datetime(2026,9,28,1,tzinfo=timezone.utc)
        api=Mock(); api.send_document.side_effect=APIError(0)
        with self.assertRaises(APIError): send_scheduled_reports(api,self.bot)
        self.click('reportexcel:weekly:0'); api.reset_mock(); api.send_document.side_effect=None
        send_scheduled_reports(api,self.bot)
        api.send_document.assert_not_called(); api.send.assert_not_called()

    def test_blocked_off_and_removed_accounts_do_not_receive_reports(self):
        self.click('reporttoggle:weekly:1'); self.click('reporttoggle:monthly:1',uid=222)
        self.current=datetime(2026,10,5,12,tzinfo=timezone.utc)
        self.bot.allowed_ids={111}; api=Mock(); api.send.side_effect=APIError(403)
        send_scheduled_reports(api,self.bot)
        self.assertFalse(self.store.report_setting(111,'weekly')['enabled'])
        self.assertEqual(api.send.call_count,1)
        api.reset_mock(); send_scheduled_reports(api,self.bot); api.send.assert_not_called()

    def test_report_time_validation_and_same_period_not_repeated_after_time_change(self):
        self.click('reporttime:weekly'); self.assertIn('format 24 jam',self.send('25:00').text)
        self.send('06:00'); self.click('reporttoggle:weekly:1')
        self.current=datetime(2026,9,28,0,tzinfo=timezone.utc); api=Mock()
        send_scheduled_reports(api,self.bot)
        self.click('reporttime:weekly'); self.send('07:00'); send_scheduled_reports(api,self.bot)
        self.assertEqual(api.send.call_count,1)

    def test_reports_run_when_no_chat_updates_arrive(self):
        self.click('reporttoggle:weekly:1'); self.current=datetime(2026,9,28,0,tzinfo=timezone.utc)
        api=Mock(); api.call.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): run_polling(api,self.bot)
        self.assertEqual(api.send.call_count,1)

    def test_bill_creation_preview_validation_and_next_due(self):
        self.click('billform:0'); self.send('Kos'); self.send('1jt kos | Tempat tinggal')
        self.assertIn('1–31',self.send('32').text)
        self.send('10'); self.assertIn('format 24 jam',self.send('99:00').text)
        preview=self.send('09:00')
        self.assertIn('Mulai periode: 2026-10',preview.text)
        self.assertEqual(self.store.bill_rows(111),[])
        self.click(self.action(preview,'formsave:'))
        self.assertEqual(self.store.history(111),[])
        self.assertEqual(self.store.bill_rows(111)[0]['start_month'],'2026-10')

    def test_bill_reminder_does_not_record_expense_and_sends_once_per_period(self):
        rid=self.bill(); api=Mock()
        self.current=datetime(2026,9,25,1,59,tzinfo=timezone.utc)
        send_bill_reminders(api,self.bot); api.send.assert_not_called()
        self.current+=timedelta(minutes=1); send_bill_reminders(api,self.bot)
        self.assertEqual(api.send.call_count,1); self.assertEqual(self.store.history(111),[])
        self.restart(); send_bill_reminders(api,self.bot); self.assertEqual(api.send.call_count,1)
        self.current=datetime(2026,10,25,2,tzinfo=timezone.utc); send_bill_reminders(api,self.bot)
        self.assertEqual(api.send.call_count,2)

    def test_bill_payment_confirmation_is_unique_and_deleted_payment_can_be_restored(self):
        rid=self.bill(); preview=self.click(f'billpay:{rid}:2026-09')
        self.assertEqual(self.store.history(111),[])
        yes=self.action(preview,'quickcommit:'); self.click(yes,qid='paidonce')
        self.restart(); self.click(yes,qid='paidonce')
        self.assertEqual(len(self.store.history(111)),1)
        already=self.click(f'billpay:{rid}:2026-09'); self.assertIn('Sudah dicatat',already.text)
        self.click('deleteyes:1:0')
        removed=self.click(f'billpay:{rid}:2026-09'); self.assertIn('catatannya dihapus',removed.text)
        self.click(self.action(removed,'restore:'))
        self.assertEqual(len(self.store.history(111)),1)

    def test_bill_payment_for_other_period_creates_separate_expense_and_can_be_backdated(self):
        rid=self.bill(); first=self.click(f'billpay:{rid}:2026-09'); self.click(self.action(first,'quickcommit:'))
        self.current=datetime(2026,10,25,12,tzinfo=timezone.utc)
        preview=self.click(f'billpay:{rid}:2026-10'); token=self.store.pending(111)['token']
        self.click(f'quickfield:{token}:spent_on'); preview=self.send('2026-10-24')
        self.click(self.action(preview,'quickcommit:'))
        self.assertEqual(len(self.store.history(111)),2)
        self.assertEqual(self.store.get(111,2)['spent_on'],'2026-10-24')
        self.assertEqual(self.store.bill_cycle(111,rid,'2026-10')['expense_id'],2)

    def test_bill_toggle_and_foreign_access_cannot_change_expenses(self):
        rid=self.bill(); view=self.click(f'billview:{rid}'); self.click(self.action(view,'billtoggle:'))
        self.current=datetime(2026,9,25,12,tzinfo=timezone.utc)
        api=Mock(); send_bill_reminders(api,self.bot); api.send.assert_not_called()
        self.assertIn('tidak ditemukan',self.click(f'billpay:{rid}:2026-09',uid=222).text)
        self.assertEqual(self.store.history(111),[])

    def test_bill_receipt_failure_does_not_leave_paid_marker(self):
        rid=self.bill(); preview=self.click(f'billpay:{rid}:2026-09')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError): self.click(self.action(preview,'quickcommit:'))
        self.assertEqual(self.store.history(111),[])
        self.assertIsNone(self.store.bill_cycle(111,rid,'2026-09')['expense_id'])

    def test_bill_edit_invalidates_preview_and_keeps_past_payment(self):
        rid=self.bill(); preview=self.click(f'billpay:{rid}:2026-09')
        values=dict(self.store.owned('bills',111,rid)); values['amount']=350000
        self.store.save_bill(111,values,rid,values['revision'])
        self.assertIn('sudah berubah',self.click(self.action(preview,'quickcommit:')).text)
        self.assertEqual(self.store.history(111),[])
        new=self.click(f'billpay:{rid}:2026-09'); self.click(self.action(new,'quickcommit:'))
        self.assertEqual(self.store.get(111,1)['amount'],350000)

    def test_offline_bill_reminds_current_month_only_and_respects_removed_users(self):
        self.bill(); self.bill(uid=222)
        self.current=datetime(2027,1,27,12,tzinfo=timezone.utc); self.bot.allowed_ids={111}
        api=Mock(); send_bill_reminders(api,self.bot)
        self.assertEqual(api.send.call_count,1)
        self.assertIn('2027-01',api.send.call_args.args[1])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM bill_cycles').fetchone()[0],1)

    def test_bill_retry_and_blocked_chat(self):
        self.bill(); self.current=datetime(2026,9,25,12,tzinfo=timezone.utc); api=Mock()
        api.send.side_effect=APIError(429)
        with self.assertRaises(APIError): send_bill_reminders(api,self.bot)
        self.assertIsNone(self.store.bill_cycle(111,1,'2026-09')['reminded_at'])
        api.send.side_effect=APIError(403); send_bill_reminders(api,self.bot)
        self.assertFalse(self.store.owned('bills',111,1)['enabled'])

    def test_backup_roundtrip_preserves_new_settings_payments_and_schedule_receipts(self):
        favorite=self.favorite(); bill=self.bill(); self.set_limit('Makanan','1000')
        self.click('ruleform:0'); self.send('café | Minuman')
        self.click('ruletoggle:0')
        preview=self.click(f'billpay:{bill}:2026-09'); self.click(self.action(preview,'quickcommit:'))
        preview=self.click(f'favuse:{favorite}'); self.click(self.action(preview,'quickcommit:'))
        self.click('reporttoggle:weekly:1'); self.current=datetime(2026,9,28,12,tzinfo=timezone.utc)
        send_scheduled_reports(Mock(),self.bot)
        backup=self.root/'backup.db'; target=self.root/'restored.db'
        snapshot_database(self.store.db,backup)
        restore_database(backup,target,lambda s:True)
        restored=Store(target)
        try:
            self.assertEqual(restored.rule_settings(111)['enabled'],0)
            self.assertEqual(len(restored.favorite_rows(111)),1)
            self.assertEqual(len(restored.bill_rows(111)),1)
            self.assertEqual(restored.bill_cycle(111,bill,'2026-09')['expense_id'],1)
            self.assertEqual(len(restored.history(111)),2)
            self.assertTrue(restored.report_job(111,'weekly','2026-09-21')['completed'])
            bot=ExpenseBot(restored,{111},ZONES['WIB'],clock=lambda:self.current)
            api=Mock(); send_scheduled_reports(api,bot); api.send.assert_not_called()
        finally: restored.close()

    def test_restore_preserves_unused_favorite_ids_to_reject_old_buttons(self):
        rid=self.favorite(); self.store.remove_owned('favorites',111,rid,0)
        backup=self.root/'backup.db'; target=self.root/'restored.db'
        snapshot_database(self.store.db,backup); restore_database(backup,target,lambda s:True)
        restored=Store(target)
        try:
            new=restored.save_favorite(111,dict(title='Baru',amount=1000,note='baru',category='Lainnya'))
            self.assertGreater(new,rid)
        finally: restored.close()

    def test_migrate_real_v22_schema_preserves_data_without_old_schedule_enrollment(self):
        oldpath=self.root/'v22.db'
        old=Store(oldpath); old.bind_bot(99)
        old.add_confirmed(111,dict(amount=1000,note='uji',category='Lainnya',spent_on='2026-09-22'),'fav:000000000001',self.current.isoformat())
        with old.transaction():
            old.db.execute('UPDATE expenses SET message_id=100 WHERE id=1')
            for table in V23_TABLES: old.db.execute('DROP TABLE '+table)
            old.db.execute("UPDATE metadata SET value='2.2' WHERE key='schema_version'")
        old.close(); previous=backup_before_upgrade(oldpath)
        self.assertIn('before-v2.4',previous.name)
        migrated=Store(oldpath)
        try:
            self.assertEqual(migrated.get(111,1)['amount'],1000)
            self.assertFalse(migrated.report_setting(111,'weekly')['enabled'])
            self.assertEqual(migrated.favorite_rows(111),[])
            self.assertEqual(migrated.bill_rows(111),[])
            self.assertIsNone(backup_before_upgrade(oldpath))
        finally: migrated.close()

    def test_new_commands_and_callback_data_respect_privacy_and_telegram_limits(self):
        rid=self.favorite(title='字'*40,expense='1 '+'界'*160+' | '+'类'*32)
        for cmd in ['/kategoriotomatis','/favorit','/rekapotomatis','/anggarankategori','/tagihan']:
            self.assertIn('belum diberi akses',self.send(cmd,uid=333).text)
        replies=[self.send('/catat'),self.send('/pengaturan'),self.send('/anggaran'),self.send('/kategoriotomatis'),
                 self.send('/favorit'),self.click(f'favuse:{rid}'),self.send('/rekapotomatis')]
        for reply in replies:
            for row in reply.buttons:
                for b in row: self.assertLessEqual(len(b['callback_data'].encode()),64)


class CalendarTests(unittest.TestCase):
    def test_bill_day_31_clamps_for_short_month_and_leap_year(self):
        bill={'day_of_month':31,'at_time':'09:00'}
        self.assertEqual(bill_due(bill,'2027-02',ZONES['WIB']).day,28)
        self.assertEqual(bill_due(bill,'2028-02',ZONES['WIB']).day,29)
        self.assertEqual(bill_due(bill,'2026-04',ZONES['WIB']).day,30)
        self.assertEqual(bill_due(bill,'2026-12',ZONES['WIB']).day,31)

    def test_report_periods_cross_year_and_leap_month_correctly(self):
        now=datetime(2027,1,1,8,tzinfo=ZONES['WIB'])
        due,start,end=report_due('monthly','07:00',now)
        self.assertEqual((str(start),str(end)),('2026-12-01','2027-01-01'))
        due,start,end=report_due('monthly','07:00',datetime(2024,3,1,8,tzinfo=ZONES['WIB']))
        self.assertEqual((end-start).days,29)
        due,start,end=report_due('weekly','07:00',datetime(2027,1,4,8,tzinfo=ZONES['WIB']))
        self.assertEqual((str(start),str(end)),('2026-12-28','2027-01-04'))


if __name__=='__main__': unittest.main(verbosity=2)
