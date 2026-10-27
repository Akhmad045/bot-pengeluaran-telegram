"""Uji perilaku fitur versi 2.1 tanpa jaringan dan tanpa data pengguna."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bot import ExpenseBot, Store, ZONES, APIError, send_due_reminders, run_polling
from test_bot import message, callback, xml_sheet, cell, NS


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'data.db'
        self.store=Store(self.path)
        self.current=datetime(2026,9,21,12,tzinfo=timezone.utc)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current)
        self.mid=100; self.qid=0

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def send(self,text,uid=111,mid=None):
        self.mid+=1
        return self.bot.handle(message(text,mid or self.mid,uid,stamp=self.current))

    def click(self,data,uid=111,qid=None):
        self.qid+=1
        return self.bot.handle_callback(callback(data,uid,qid=qid or f'click{self.qid}'))

    def restart(self):
        self.store.close(); self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current)

    def draft(self,record_id=1):
        self.click(f'editopen:{record_id}')
        return self.store.pending(111)['token']

    def field(self,token,key,value):
        self.click(f'editfield:{token}:{key}')
        return self.send(value)

    def test_edit_all_fields_requires_confirmation_and_updates_excel(self):
        self.send('15000 makan | Makanan')
        token=self.draft()
        for key,value in [('amount','25rb'),('note','bensin motor'),('category','TRANSPORTASI'),('spent_on','2026-08-31')]:
            self.field(token,key,value)
        self.assertEqual(self.store.get(111,1)['amount'],15000)
        reply=self.click(f'editsave:{token}')
        self.assertIn('Perubahan disimpan',reply.text)
        row=self.store.get(111,1)
        self.assertEqual((row['amount'],row['note'],row['category'],row['spent_on']),(25000,'bensin motor','Transportasi','2026-08-31'))
        self.assertEqual(len(self.store.history(111)),1)
        self.assertIn('Total: Rp0',self.send('/bulanini').text)
        exported=self.send('/excel 2026-08').document
        self.assertEqual(cell(xml_sheet(exported.content,1),'B5').find('s:v',NS).text,'25000')

    def test_edit_invalid_values_do_not_leave_input_mode(self):
        self.send('1000 kopi')
        token=self.draft()
        for key,value in [('amount','-1'),('spent_on','2026-09-22'),('spent_on','2026-02-30'),('note','x'*161),('category','x'*33)]:
            reply=self.field(token,key,value)
            self.assertIn('Kirim ulang',reply.text)
            self.assertIsNotNone(self.store.pending(111))
        self.assertEqual(len(self.store.history(111)),1)
        self.assertEqual(self.store.get(111,1)['revision'],0)

    def test_edit_cancel_and_navigation_discard_draft(self):
        self.send('1000 kopi')
        token=self.draft(); self.field(token,'amount','2000')
        self.send('/batal')
        self.assertIsNone(self.store.pending(111))
        self.assertIn('tidak aktif',self.click(f'editsave:{token}').text)
        token=self.draft(); self.field(token,'amount','3000')
        self.click('menu')
        self.assertIsNone(self.store.pending(111))
        self.assertEqual(self.store.get(111,1)['amount'],1000)

    def test_edit_draft_survives_restart_and_duplicate_input_is_not_an_expense(self):
        self.send('1000 kopi')
        token=self.draft(); self.click(f'editfield:{token}:note')
        first=self.send('50000 bensin',mid=500)
        self.restart()
        second=self.send('50000 bensin',mid=500)
        self.assertEqual(first.text,second.text)
        self.click(f'editsave:{token}',qid='save-once')
        self.click(f'editsave:{token}',qid='save-once')
        self.assertEqual(self.store.get(111,1)['revision'],1)
        self.assertEqual(len(self.store.history(111)),1)

    def test_expired_input_is_not_reinterpreted_as_expense(self):
        self.send('1000 kopi'); token=self.draft()
        self.click(f'editfield:{token}:note')
        self.current+=timedelta(minutes=31)
        reply=self.send('2000 air')
        self.assertIn('Waktu pengisian habis',reply.text)
        self.assertEqual(len(self.store.history(111)),1)

    def test_stale_and_cross_user_edit_cannot_change_a_record(self):
        self.send('1000 kopi'); token=self.draft()
        self.field(token,'amount','2000')
        self.assertIn('tidak aktif',self.click(f'editsave:{token}',uid=222).text)
        self.assertIn('tidak ditemukan',self.click('editopen:1',uid=222).text)
        self.store.set_deleted(111,1,True)
        self.store.set_deleted(111,1,False)
        self.assertIn('sudah berubah',self.click(f'editsave:{token}').text)
        self.assertEqual(self.store.get(111,1)['amount'],1000)

    def test_receipt_failure_rolls_back_edit_and_keeps_draft(self):
        self.send('1000 kopi'); token=self.draft(); self.field(token,'amount','2000')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError): self.click(f'editsave:{token}')
        self.assertEqual(self.store.get(111,1)['amount'],1000)
        self.assertIsNotNone(self.store.pending(111))
        self.assertIn('Perubahan disimpan',self.click(f'editsave:{token}').text)

    def test_budget_thresholds_and_remaining_match_example(self):
        self.send('/anggaran 1,5jt')
        self.assertNotIn('Batas 80%',self.send('1199999 pertama').text)
        self.assertIn('Batas 80%',self.send('1 batas').text)
        self.assertIn('Sisa anggaran: Rp300.000',self.send('/anggaran').text)
        self.assertNotIn('Batas 80%',self.send('10000 berikut').text)
        self.assertIn('Batas 100%',self.send('290000 batas penuh').text)
        self.assertNotIn('Batas 100%',self.send('1000 lebih').text)
        self.assertIn('Melebihi anggaran: Rp1.000',self.send('/anggaran').text)

    def test_budget_single_jump_only_warns_highest_threshold(self):
        self.send('/anggaran 1000')
        text=self.send('1200 lebih').text
        self.assertIn('Batas 100%',text); self.assertNotIn('Batas 80%',text)

    def test_budget_is_scoped_per_month_and_user_and_copies_previous(self):
        self.send('/anggaran 2026-08 100000')
        self.send('/anggaran 900000',uid=222)
        self.click('budgetcopy:2026-09')
        self.assertEqual(self.store.budget(111,'2026-09')['amount'],100000)
        self.assertEqual(self.store.budget(222,'2026-09')['amount'],900000)
        self.assertIsNone(self.store.budget(111,'2026-10'))
        self.send('2026-08-31 80000 agustus')
        self.assertEqual(self.store.budget(111,'2026-09')['alert_level'],0)

    def test_budget_invalid_input_and_receipt_rollback(self):
        self.click('budgetset:2026-09')
        self.assertIn('Kirim ulang',self.send('0').text)
        self.assertIsNone(self.store.budget(111,'2026-09'))
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): self.send('1500000')
        self.assertIsNone(self.store.budget(111,'2026-09'))
        self.assertIsNotNone(self.store.pending(111))

    def test_budget_edit_and_restore_update_total_and_warn_once(self):
        self.send('/anggaran 100000')
        self.send('70000 makan'); token=self.draft()
        self.field(token,'amount','80000')
        self.assertIn('Batas 80%',self.click(f'editsave:{token}').text)
        self.click('deleteyes:1:0')
        self.assertIn('Terpakai: Rp0',self.send('/anggaran').text)
        self.assertNotIn('Batas 80%',self.click('restore:1:0').text)
        self.restart()
        self.assertNotIn('Batas 80%',self.send('1000 kopi').text)

    def test_budget_alert_survives_message_delivery_retry(self):
        self.send('/anggaran 1000')
        first=self.send('800 belanja',mid=800)
        self.restart()
        retry=self.send('800 belanja',mid=800)
        self.assertEqual(first.text,retry.text)
        self.assertIn('Batas 80%',retry.text)
        self.assertEqual(len(self.store.history(111)),1)

    def test_search_combines_keyword_category_and_inclusive_dates(self):
        self.send('2026-09-01 10000 BENSIN satu | Transportasi\n2026-09-20 20000 bensin dua | Transportasi\n2026-09-21 30000 bensin tiga | Lainnya\n2026-08-31 40000 bensin lama | Transportasi')
        self.send('999999 bensin rahasia',uid=222)
        self.assertIn('Total hasil: Rp100.000',self.send('/cari bensin').text)
        categories=self.click('findcats:0')
        selected=next(b['callback_data'] for line in categories.buttons for b in line if b['text']=='Transportasi')
        self.click(selected)
        self.click('findinput:dates')
        result=self.send('2026-09-01 2026-09-20')
        self.assertIn('Jumlah: 2 catatan',result.text)
        self.assertIn('Total hasil: Rp30.000',result.text)
        self.assertNotIn('rahasia',result.text)
        self.assertIn('EDIT PENGELUARAN',self.click(result.buttons[0][0]['callback_data']).text)

    def test_search_literal_symbols_unicode_deleted_and_empty_results(self):
        self.send('1000 diskon 100% | A\n2000 diskon biasa | B\n3000 CAFÉ sore | B')
        self.assertIn('Jumlah: 1 catatan',self.send('/cari %').text)
        self.assertIn('Total hasil: Rp3.000',self.send('/cari café').text)
        self.click('deleteyes:3:0')
        self.assertIn('Total hasil: Rp0',self.send('/cari café').text)
        self.assertIn('Tidak ada',self.send('/cari tidak ditemukan').text)

    def test_search_pagination_total_is_all_results_and_filters_survive_restart(self):
        self.send('\n'.join(f'1000 bensin {i}' for i in range(14)))
        first=self.send('/cari bensin')
        self.assertIn('Total hasil: Rp14.000',first.text)
        self.assertIn('7. bensin',self.click('search:1').text)
        self.restart()
        self.assertIn('Kata: bensin',self.send('/cari').text)
        self.click('findinput:dates')
        self.assertIn('awal tidak boleh',self.send('2026-09-21 2026-09-01').text)
        self.assertIsNotNone(self.store.pending(111))

    def test_reminder_opt_in_and_custom_time_validation(self):
        self.assertIn('Status: Nonaktif',self.send('/pengingat').text)
        self.click('remindertime')
        self.assertIn('format 24 jam',self.send('25:00').text)
        self.assertFalse(self.store.reminder(111)['enabled'])
        self.assertIn('Status: Aktif',self.send('21:15').text)
        expected=datetime(2026,9,21,14,15,tzinfo=timezone.utc)
        self.assertEqual(self.store.reminder(111)['next_due'],int(expected.timestamp()))
        self.click('reminderenable:0')
        self.assertFalse(self.store.reminder(111)['enabled'])

    def test_reminders_honor_timezones_and_survive_restart_without_duplicates(self):
        self.send('/pengingat 21:00')
        self.click('zone:WIT',uid=222)
        self.send('/pengingat 22:00',uid=222)
        self.current=datetime(2026,9,21,12,59,tzinfo=timezone.utc)
        class Fake:
            def __init__(self): self.sent=[]
            def send(self,*args): self.sent.append(args)
        api=Fake(); send_due_reminders(api,self.bot)
        self.assertEqual(api.sent,[])
        self.current+=timedelta(minutes=1)
        send_due_reminders(api,self.bot)
        self.assertEqual([x[0] for x in api.sent],[222])
        self.current+=timedelta(hours=1)
        send_due_reminders(api,self.bot)
        self.assertEqual([x[0] for x in api.sent],[222,111])
        self.restart(); send_due_reminders(api,self.bot)
        self.assertEqual(len(api.sent),2)
        self.current+=timedelta(days=1)
        send_due_reminders(api,self.bot)
        self.assertEqual(len(api.sent),4)

    def test_reminder_offline_catches_up_today_only(self):
        self.send('/pengingat 21:00')
        self.current=datetime(2026,9,24,12,tzinfo=timezone.utc)
        api=unittest.mock.Mock()
        send_due_reminders(api,self.bot)
        api.send.assert_not_called()
        self.current+=timedelta(hours=3)
        send_due_reminders(api,self.bot)
        self.assertEqual(api.send.call_count,1)
        self.assertIn('24-09-2026',api.send.call_args.args[1])

    def test_reminder_failure_retries_and_blocked_users_are_disabled(self):
        self.send('/pengingat 21:00'); self.send('/pengingat 21:00',uid=222)
        self.current+=timedelta(hours=2)
        api=unittest.mock.Mock()
        api.send.side_effect=APIError(429)
        with self.assertRaises(APIError): send_due_reminders(api,self.bot)
        self.assertIsNone(self.store.reminder(111)['last_sent_day'])
        api.send.side_effect=[APIError(403),None]
        send_due_reminders(api,self.bot)
        self.assertFalse(self.store.reminder(111)['enabled'])
        self.assertEqual(self.store.reminder(222)['last_sent_day'],'2026-09-21')

    def test_disabled_and_removed_users_never_receive_reminders(self):
        self.send('/pengingat 21:00'); self.send('/pengingat 21:00',uid=222)
        self.click('reminderenable:0')
        self.bot.allowed_ids={111}
        self.current+=timedelta(hours=2)
        api=unittest.mock.Mock(); send_due_reminders(api,self.bot)
        api.send.assert_not_called()

    def test_scheduler_runs_while_chat_is_idle(self):
        self.send('/pengingat 21:00')
        self.current+=timedelta(hours=2)
        class Fake:
            def __init__(self): self.sent=[]
            def send(self,*args): self.sent.append(args)
            def call(self,method,payload): raise KeyboardInterrupt()
        api=Fake()
        with self.assertRaises(KeyboardInterrupt): run_polling(api,self.bot)
        self.assertEqual(len(api.sent),1)

    def test_comparison_current_month_uses_equal_dates_and_supports_full_month(self):
        self.send('2026-08-20 100000 bensin | Transportasi\n2026-08-31 200000 makan | Makanan\n2026-09-21 150000 makan | Makanan')
        self.send('999999 rahasia',uid=222)
        equal=self.send('/banding').text
        self.assertIn('Naik Rp50.000 (50,0%)',equal)
        self.assertIn('21 Agustus 2026',equal)
        self.assertIn('Makanan: Rp150.000',equal)
        full=self.click('compare:2026-09:full').text
        self.assertIn('Turun Rp150.000 (50,0%)',full)
        self.assertNotIn('rahasia',full)

    def test_comparison_year_boundary_and_zero_baseline(self):
        self.current=datetime(2026,1,20,12,tzinfo=timezone.utc)
        self.send('1000 baru')
        report=self.send('/banding').text
        self.assertIn('Desember 2025',report)
        self.assertIn('Persentase tidak dihitung',report)
        self.click('deleteyes:1:0')
        self.assertIn('tetap sama',self.send('/banding').text)

    def test_comparison_short_previous_month_is_capped_correctly(self):
        self.current=datetime(2024,3,31,12,tzinfo=timezone.utc)
        self.send('2024-02-29 1000 lalu\n2024-03-31 2000 kini')
        report=self.send('/banding').text
        self.assertIn('29 Februari 2024',report)
        self.assertIn('Naik Rp1.000 (100,0%)',report)

    def test_all_new_commands_reject_unauthorized_users(self):
        for command in ['/edit','/anggaran 1jt','/cari bensin','/pengingat 21:00','/banding']:
            self.assertIn('belum diberi akses',self.send(command,uid=333).text)
        self.assertIsNone(self.store.budget(333,'2026-09'))
        self.assertFalse(self.store.reminder(333)['enabled'])

    def test_callback_payloads_fit_telegram_limit_for_unicode_categories(self):
        self.send('1000 sesuatu | '+'界'*32)
        for reply in [self.send('/menu'),self.click('findcats:0'),self.send('/anggaran'),self.send('/edit'),self.send('/pengingat'),self.send('/banding')]:
            for row in reply.buttons:
                for item in row: self.assertLessEqual(len(item['callback_data'].encode()),64)


class MigrationTests(unittest.TestCase):
    def test_v2_database_adds_features_without_changing_records_or_zone(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'v2.db'
            db=sqlite3.connect(path)
            db.executescript('''CREATE TABLE expenses(id INTEGER PRIMARY KEY,user_id INTEGER,chat_id INTEGER,message_id INTEGER,
                line_no INTEGER,spent_on TEXT,amount INTEGER,note TEXT,category TEXT,created_at TEXT,deleted INTEGER);
                CREATE TABLE preferences(user_id INTEGER PRIMARY KEY,zone TEXT);
                INSERT INTO preferences VALUES(111,'WITA');
                INSERT INTO expenses VALUES(17,111,111,10,0,'2026-09-01',50000,'bensin','Transportasi','2026-09-01T00:00:00+07:00',0);
                INSERT INTO expenses VALUES(18,111,111,10,1,'2026-09-01',20000,'makan','Makanan','2026-09-01T00:00:00+07:00',1);''')
            db.close()
            store=Store(path)
            self.assertEqual(store.get(111,17)['amount'],50000)
            self.assertTrue(store.get(111,18)['deleted'])
            self.assertEqual(store.get(111,17)['revision'],0)
            self.assertEqual(store.get_zone(111,ZONES['WIB']),ZONES['WITA'])
            self.assertFalse(store.reminder(111)['enabled'])
            store.close()


if __name__=='__main__': unittest.main(verbosity=2)
