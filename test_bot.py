"""Uji lokal tanpa token asli, tanpa jaringan, dan tanpa mengubah data pengguna."""
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from bot import (APIError, ExpenseBot, Store, Telegram, ZONES, load_config, parse_amount,
                 parse_expense, parse_batch, month_range, run_polling, split_text, clear_chat, deliver)
from app import Document
from excel_export import excel_date

NOW=datetime(2026,9,20,6,tzinfo=timezone.utc)
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def message(text, message_id=1, user_id=111, stamp=None, kind='private', **user):
    return {'message_id':message_id,'date':int((stamp or NOW).timestamp()),
            'chat':{'id':user_id if kind=='private' else -10,'type':kind},
            'from':{'id':user_id,**user},'text':text}


def callback(data, uid=111, mid=50, qid=None):
    return {'id':qid or 'q'+data,'data':data,'from':{'id':uid,'username':'iyan'},
            'message':{'message_id':mid,'date':int(NOW.timestamp()),'chat':{'id':uid,'type':'private'}}}


def xml_sheet(content, index):
    with ZipFile(io.BytesIO(content)) as z:
        return ET.fromstring(z.read(f'xl/worksheets/sheet{index}.xml'))


def cell(root, address):
    return root.find(f'.//s:c[@r="{address}"]',NS)


class AmountTests(unittest.TestCase):
    def test_supported_rupiah_forms(self):
        for text,expected in [('15000',15000),('15.000',15000),('Rp15.000',15000),('15rb',15000),
                              ('15K',15000),('15,5rb',15500),('1,5jt',1500000),('0,001rb',1)]:
            with self.subTest(text=text): self.assertEqual(parse_amount(text),expected)

    def test_invalid_amounts(self):
        for text in ['0','-10','NaN','inf','1.5','15,000','15.00','1e6','0,0001rb','1000000000001','']:
            with self.subTest(text=text),self.assertRaises(ValueError): parse_amount(text)

    def test_backdate_and_category(self):
        result=parse_expense('2026-09-19 Rp 15.000 makan siang | MAKANAN',date(2026,9,20))
        self.assertEqual((result.spent_on,result.amount,result.note,result.category),
                         (date(2026,9,19),15000,'makan siang','Makanan'))

    def test_invalid_expenses(self):
        for text in ['15000','15000 | Makanan','15000 makan |','1 kopi | X | Y | Z',
                     '2026-02-30 1 kopi','2026-09-21 1 kopi','1 '+'x'*161]:
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_expense(text,date(2026,9,20))

    def test_month_edges(self):
        self.assertEqual(month_range('2026-12'),(date(2026,12,1),date(2027,1,1)))
        self.assertEqual(month_range('2024-02'),(date(2024,2,1),date(2024,3,1)))
        for text in ['2026-13','2026-9','abc','9999-12']:
            with self.subTest(text=text),self.assertRaises(ValueError): month_range(text)

    def test_multiline_whitespace_and_limits(self):
        rows=parse_batch('\n50000 bensin\r\n20000 makan\n\n15000 minum',date(2026,9,20))
        self.assertEqual([r.amount for r in rows],[50000,20000,15000])
        with self.assertRaises(ValueError): parse_batch('\n'.join(['1 kopi']*101),date(2026,9,20))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'test.db'
        self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:NOW)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def send(self,text,mid=None,uid=111,**kwargs):
        if mid is None:
            mid=getattr(self,'next_mid',0)+1
        self.next_mid=max(getattr(self,'next_mid',0),mid)
        self.last=self.bot.handle(message(text,mid,uid,**kwargs))
        return self.last.text if self.last else None

    def click(self,data,uid=111,**kwargs):
        return self.bot.handle_callback(callback(data,uid,**kwargs))

    def test_daily_monthly_totals(self):
        self.send('15rb makan | Makanan\n5rb minum | makanan',1)
        self.send('/catat 2026-09-19 20rb ojek | Transportasi',2)
        self.send('/catat 2026-08-31 999rb luar bulan',3)
        self.assertIn('Total: Rp20.000\n',self.send('/hariini',4))
        self.assertIn('Jumlah: 2 catatan',self.last.text)
        self.assertIn('1. makan — Rp15.000',self.last.text)
        self.assertNotIn('#',self.last.text); self.assertNotIn('·',self.last.text)
        self.assertIn('Total: Rp40.000\n',self.send('/bulanini',5))
        self.assertIn('Makanan: Rp20.000',self.last.text)
        self.assertNotIn('999.000',self.last.text)

    def test_requested_batch_example_and_atomic_validation(self):
        result=self.send('50000 bensin\n20000 makan\n15000 minum')
        self.assertIn('Tercatat 3 pengeluaran',result)
        self.assertIn('Total ditambahkan: Rp85.000',result)
        self.assertIn('3. minum',result)
        result=self.send('1000 kopi\nbukan nominal\n5000 minum',2)
        self.assertIn('Baris 2',result)
        self.assertEqual(len(self.store.history(111)),3)

    def test_persistence_and_batch_retry_after_restart(self):
        first=self.send('10rb kopi\n20rb makan',10)
        self.store.close(); self.store=Store(self.path)
        self.bot=ExpenseBot(self.store,{111},ZONES['WIB'],clock=lambda:NOW)
        self.assertEqual(first,self.send('10rb kopi\n20rb makan',10))
        self.assertIn('Jumlah: 2 catatan',self.send('/hariini',11))

    def test_delete_list_confirmation_restore(self):
        self.send('1000 kopi',1)
        self.send('/hapus',2)
        self.assertIn('1. kopi',self.last.text)
        target=self.last.buttons[0][0]['callback_data']
        prompt=self.click(target)
        self.assertIn('HAPUS PENGELUARAN INI?',prompt.text)
        self.assertEqual(len(self.store.history(111)),1)
        result=self.click(prompt.buttons[0][0]['callback_data'])
        self.assertEqual(len(self.store.history(111)),0)
        self.click(result.buttons[0][0]['callback_data'])
        self.assertEqual(len(self.store.history(111)),1)
        self.assertIn('Total: Rp1.000\n',self.send('/hariini',3))

    def test_duplicate_callback_cannot_delete_restored_record_again(self):
        self.send('1000 kopi')
        self.click('deleteyes:1:0',qid='same-delete')
        self.click('restore:1:0',qid='restore-once')
        self.click('deleteyes:1:0',qid='same-delete')
        self.assertFalse(self.store.get(111,1)['deleted'])

    def test_cross_user_data_and_callback_access(self):
        self.send('1000 rahasia satu',1,111)
        self.send('2000 rahasia dua',1,222)
        self.assertIn('Total: Rp2.000\n',self.send('/hariini',2,222))
        self.assertIn('tidak ditemukan',self.click('deleteyes:1:0',222).text)
        self.assertFalse(self.store.get(111,1)['deleted'])
        forged=callback('month',222); forged['message']['chat']['id']=111
        self.assertIsNone(self.bot.handle_callback(forged))
        self.assertIsNone(self.click('xlsx:2026-09',333))

    def test_unauthorized_group_and_onboarding(self):
        self.assertIn('belum diberi akses',self.send('1000 kopi',uid=333))
        self.assertIn('333',self.send('/id',uid=333))
        self.assertIsNone(self.send('1000 kopi',kind='group'))
        locked=ExpenseBot(self.store,set(),ZONES['WIB'])
        self.assertIn('belum diberi akses',locked.handle(message('1000 kopi')).text)
        self.assertEqual(len(self.store.history(111)),0)

    def test_username_live_clock_and_persistent_indonesian_zone(self):
        self.bot.clock=lambda:datetime(2026,9,20,16,30,45,tzinfo=timezone.utc)
        text=self.send('/start',username='iyan')
        self.assertIn('Halo! @iyan',text); self.assertIn('23:30:45',text)
        text=self.click('zone:WIT').text
        self.assertIn('21 September 2026',text); self.assertIn('01:30:45',text)
        self.assertIn('WIT',text)
        self.assertIn('Halo! Iyan Ahmad',self.send('/menu',first_name='Iyan',last_name='Ahmad'))
        self.assertEqual(self.store.get_zone(111,ZONES['WIB']),ZONES['WIT'])
        self.assertEqual(self.store.get_zone(222,ZONES['WIB']),ZONES['WIB'])

    def test_midnight_uses_record_message_timestamp(self):
        self.send('1000 sebelum',1,stamp=datetime(2026,8,31,16,59,59,tzinfo=timezone.utc))
        self.send('2000 sesudah',2,stamp=datetime(2026,8,31,17,tzinfo=timezone.utc))
        self.assertIn('Total: Rp1.000\n',self.send('/bulanan 2026-08',3))
        self.assertIn('Total: Rp2.000\n',self.send('/bulanan 2026-09',4))

    def test_daily_and_delete_pagination(self):
        self.send('\n'.join(f'1000 belanja {i}' for i in range(1,15)))
        first=self.bot.daily(111,date(2026,9,20))
        second=self.click('daily:2026-09-20:1')
        self.assertIn('6. belanja 6',first.text)
        self.assertNotIn('7. belanja 7',first.text)
        self.assertIn('7. belanja 7',second.text)
        self.assertIn('Jumlah: 14 catatan',second.text)
        self.assertIn('7. belanja 8',self.click('deletelist:1').text)

    def test_excel_values_formulas_dates_and_user_isolation(self):
        self.send('50000 bensin | Transportasi\n20000 makan | Makanan\n15000 minum | Makanan',1)
        self.send('999999999 rahasia pengguna lain',1,222)
        reply=self.bot.handle(message('/excel 2026-09',2))
        self.assertEqual(reply.document.filename,'pengeluaran-2026-09.xlsx')
        summary=xml_sheet(reply.document.content,1); detail=xml_sheet(reply.document.content,2)
        self.assertEqual(cell(summary,'B5').find('s:v',NS).text,'85000')
        self.assertIn('SUM(',cell(summary,'B5').find('s:f',NS).text)
        self.assertEqual(cell(summary,'B6').find('s:v',NS).text,'3')
        self.assertEqual(cell(detail,'E8').find('s:v',NS).text,'50000')
        self.assertEqual(cell(detail,'B8').find('s:v',NS).text,str(excel_date(date(2026,9,20))))
        self.assertNotIn('rahasia pengguna lain',ET.tostring(detail,encoding='unicode'))
        self.assertEqual(detail.find('s:autoFilter',NS).get('ref'),'A7:F10')

    def test_excel_empty_day_and_deleted_entries(self):
        self.send('1000 kopi')
        self.click('deleteyes:1:0')
        reply=self.bot.handle(message('/excel 2026-09-20',2))
        self.assertEqual(reply.document.filename,'pengeluaran-2026-09-20.xlsx')
        summary=xml_sheet(reply.document.content,1)
        self.assertEqual(cell(summary,'B5').find('s:v',NS).text,'0')
        self.assertEqual(cell(summary,'B6').find('s:v',NS).text,'0')

    def test_excel_formula_like_notes_stay_text(self):
        self.send('1000 =HYPERLINK("https://example.invalid","test") | A*B')
        reply=self.bot.handle(message('/excel',2))
        detail=xml_sheet(reply.document.content,2)
        self.assertEqual(cell(detail,'C8').get('t'),'inlineStr')
        self.assertIsNone(cell(detail,'C8').find('s:f',NS))
        self.assertIn('HYPERLINK',cell(detail,'C8').find('s:is/s:t',NS).text)

    def test_clear_is_confirmed_and_keeps_expenses(self):
        self.send('1000 kopi')
        self.send('/clear',2)
        self.assertIsNone(self.last.clear_cutoff)
        self.assertIn('48 jam',self.last.text)
        action=self.click('clear:yes',mid=50)
        self.assertEqual(action.clear_cutoff,50)
        self.assertEqual(len(self.store.history(111)),1)
        now=int(time.time())
        for chat,mid,stamp in [(111,10,now-10),(111,20,now-172900),(111,60,now-1),(222,12,now-1)]:
            self.store.track_message(chat,mid,stamp)
        calls=[]
        class Fake:
            def call(self,method,payload): calls.append((method,payload)); return True
        clear_chat(Fake(),self.store,111,50,now=now)
        self.assertEqual(calls,[('deleteMessages',{'chat_id':111,'message_ids':[10]})])
        self.assertEqual(len(self.store.history(111)),1)
        self.assertEqual(self.store.clear_candidates(111,100,now),[60])
        self.assertEqual(self.store.clear_candidates(222,100,now),[12])

    def test_empty_and_malformed_actions(self):
        self.assertIn('Total: Rp0',self.send('/hariini'))
        self.assertIn('Belum ada',self.send('/bulanini'))
        self.assertIn('tidak valid',self.send('/harian 2026-02-30'))
        self.assertIn('Untuk bulan lain',self.send('/bulanini 2026-08'))
        self.assertIn('tidak dikenal',self.send('/asing'))
        self.assertIn('tidak valid',self.click('daily:invalid').text)
        self.assertIn('tidak valid',self.click('deleteyes:NaN:0').text)

    def test_clear_from_old_menu_includes_newer_chat_messages(self):
        now=int(time.time())
        for uid,mid in [(111,10),(111,75),(111,80),(222,999)]:
            self.store.track_message(uid,mid,now-5)
        reply=self.click('clear:yes',mid=10)
        self.assertEqual(reply.clear_cutoff,80)
        self.assertEqual(self.store.clear_candidates(111,reply.clear_cutoff,now),[10,75,80])

    def test_bot_identity_stays_bound(self):
        self.store.bind_bot(1); self.store.bind_bot(1)
        with self.assertRaises(ValueError): self.store.bind_bot(2)

    @patch('bot.time.sleep')
    def test_network_retry_does_not_duplicate_batch(self,_sleep):
        update={'update_id':100,'message':message('15rb makan\n5rb minum')}
        class Fake:
            def __init__(self): self.polls=0; self.sends=0; self.payloads=[]
            def call(self,method,payload):
                self.polls+=1; self.payloads.append(payload)
                if self.polls>2: raise KeyboardInterrupt()
                return [update]
            def send(self,chat,text,markup=None):
                self.sends+=1
                if self.sends==1: raise APIError(0)
        api=Fake()
        with self.assertRaises(KeyboardInterrupt): run_polling(api,self.bot)
        self.assertNotIn('offset',api.payloads[1])
        self.assertEqual(api.payloads[2]['offset'],101)
        self.assertEqual(len(self.store.history(111)),2)


class IntegrationTests(unittest.TestCase):
    def test_old_database_migration_preserves_ids_deleted_and_amounts(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'old.db'
            db=sqlite3.connect(path)
            db.execute('''CREATE TABLE expenses(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,
                chat_id INTEGER,message_id INTEGER,spent_on TEXT,amount INTEGER,note TEXT,category TEXT,
                created_at TEXT,deleted INTEGER DEFAULT 0,UNIQUE(chat_id,message_id))''')
            db.execute('INSERT INTO expenses VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (12,111,111,1,'2026-09-20',15000,'makan siang 25000 bensin','Lainnya',NOW.isoformat(),1))
            db.commit(); db.close()
            store=Store(path)
            self.assertTrue(Path(str(path)+'.v1.bak').exists())
            old=store.get(111,12)
            self.assertEqual((old['amount'],old['note'],old['deleted']),
                             (15000,'makan siang 25000 bensin',1))
            bot=ExpenseBot(store,{111},ZONES['WIB'],clock=lambda:NOW)
            bot.handle(message('50000 bensin\n20000 makan\n15000 minum',2))
            self.assertEqual([r['id'] for r in store.rows(111,date(2026,9,1),date(2026,10,1))],[13,14,15])
            store.close()
            store=Store(path)
            self.assertEqual(store.get(111,12)['deleted'],1)
            store.close()

    def test_long_emoji_messages_fit_telegram_limits(self):
        parts=split_text(('😀'*160+'\n')*100)
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=4096 for p in parts))
        self.assertEqual(sum(p.count('😀') for p in parts),16000)

    @patch.dict(os.environ,{},clear=True)
    def test_config_file_env_override_and_persistent_volume_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            config=Path(temp)/'config.json'
            data={'bot_token':'123:'+'A'*35,'allowed_user_ids':[111],'timezone':'WIB'}
            config.write_text(json.dumps(data),encoding='utf-8')
            self.assertEqual(load_config(config)[1],{111})
            with patch.dict(os.environ,{'ALLOWED_USER_IDS':'222,333','BOT_TIMEZONE':'WIT'}):
                self.assertEqual(load_config(config)[1],{222,333})
                self.assertEqual(load_config(config)[2],ZONES['WIT'])
            with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'test'}):
                with self.assertRaises(ValueError): load_config(config)
            with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'test','RAILWAY_VOLUME_MOUNT_PATH':temp,
                                       'DB_PATH':str(Path(temp)/'pengeluaran.db')}):
                self.assertEqual(load_config(config)[3],Path(temp)/'pengeluaran.db')
            with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':data['bot_token'],'ALLOWED_USER_IDS':'111'}):
                self.assertEqual(load_config(Path(temp)/'missing.json')[1],{111})

    @patch('bot.urlopen')
    def test_http_errors_hide_tokens_and_upload_is_real_xlsx(self,urlopen):
        from urllib.error import HTTPError
        from http.client import IncompleteRead
        api=Telegram('SECRET_FOR_TEST')
        urlopen.return_value=io.BytesIO(b'{"ok":true,"result":[]}')
        self.assertEqual(api.call('getUpdates',{'timeout':30}),[])
        self.assertEqual(json.loads(urlopen.call_args.args[0].data),{'timeout':30})
        urlopen.side_effect=HTTPError('SECRET_FOR_TEST',429,'rate',{},
                                      io.BytesIO(b'{"parameters":{"retry_after":5}}'))
        with self.assertRaises(APIError) as error: api.call('getUpdates')
        self.assertEqual(error.exception.retry_after,5)
        self.assertNotIn('SECRET',str(error.exception))
        urlopen.side_effect=IncompleteRead(b'partial')
        with self.assertRaises(APIError): api.call('getUpdates')
        urlopen.side_effect=None
        urlopen.return_value=io.BytesIO(b'{"ok":true,"result":true}')
        doc=Document('pengeluaran-2026-09.xlsx',b'PK_FAKE_BYTES_FOR_MULTIPART_TEST','test')
        api.send_document(111,doc,'Rekap',{'inline_keyboard':[]})
        req=urlopen.call_args.args[0]
        self.assertTrue(req.full_url.endswith('/sendDocument'))
        self.assertIn(doc.content,req.data)
        self.assertIn(b'filename="pengeluaran-2026-09.xlsx"',req.data)
        self.assertIn('multipart/form-data',req.headers['Content-type'])

    def test_menu_callback_edits_in_place(self):
        calls=[]
        class Fake:
            def edit(self,*args): calls.append(('edit',args))
            def send(self,*args): calls.append(('send',args))
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'data.db')
            reply=ExpenseBot(store,{111},ZONES['WIB'],clock=lambda:NOW).menu({'id':111,'username':'iyan'})
            deliver(Fake(),store,111,reply,edit_id=50)
            self.assertEqual([c[0] for c in calls],['edit'])
            store.close()


if __name__=='__main__': unittest.main(verbosity=2)
