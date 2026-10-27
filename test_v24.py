"""Uji perilaku versi 2.4 dengan data sementara, tanpa koneksi Telegram."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app import ExpenseBot
from backups import backup_before_upgrade, readonly, restore_database, snapshot_database
from core import Store, ZONES, parse_expense
from storage_v24 import MONEY_FIELDS
from test_bot import message, callback, xml_sheet, cell, NS
import test_v23


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); self.path=self.root/'data.db'
        self.store=Store(self.path); self.store.bind_bot(99)
        self.current=datetime(2026,9,24,12,tzinfo=timezone.utc)
        self.bot=ExpenseBot(self.store,{111,222},ZONES['WIB'],clock=lambda:self.current,owner_id=111)
        self.mid=100; self.qid=0
        self.common=self.store.default_wallet(111)['id']

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def send(self,text,uid=111,mid=None):
        self.mid+=1
        return self.bot.handle(message(text,mid or self.mid,uid,stamp=self.current))

    def click(self,data,uid=111,qid=None):
        self.qid+=1
        return self.bot.handle_callback(callback(data,uid,qid=qid or f'wallet{self.qid}'))

    def action(self,reply,prefix):
        return next(b['callback_data'] for row in reply.buttons for b in row if b['callback_data'].startswith(prefix))

    favorite=test_v23.SmartTests.favorite
    bill=test_v23.SmartTests.bill
    restart=test_v23.SmartTests.restart

    def wallet(self,name='Bank',opening=None,uid=111):
        row=self.store.create_wallet(uid,name)
        if opening is not None: row=self.store.update_wallet(uid,row['id'],row['revision'],opening=opening)
        return row['id']

    def income(self,text='2jt gaji | Gaji',uid=111):
        preview=self.send('/pemasukan '+text,uid)
        reply=self.click(self.action(preview,'msave:'),uid)
        return self.store.money_rows(uid,'income')[0],reply

    def transfer(self,origin,target,text='100rb top up'):
        self.send('/transfer'); token=self.store.pending(111)['token']
        self.click(f'wset:{token}:wallet:{origin}'); self.click(f'wset:{token}:to:{target}')
        preview=self.send(text); reply=self.click(self.action(preview,'msave:'))
        return self.store.money_rows(111,'transfer')[0],reply

    def totals(self,wid=None,uid=111): return self.store.wallet_totals(uid,wid or self.common)

    def test_wallet_setup_requires_confirmation_and_distinguishes_zero_from_unknown(self):
        self.assertFalse(self.totals()['configured'])
        self.click('wform:new:0'); preview=self.send('Tunai')
        self.assertEqual(len(self.store.wallets(111)),1)
        self.click(self.action(preview,'wsave:')); self.assertEqual(len(self.store.wallets(111)),2)
        self.click(f'wform:opening:{self.common}'); preview=self.send('0')
        self.assertFalse(self.totals()['configured'])
        self.click(self.action(preview,'wsave:')); self.assertTrue(self.totals()['configured'])
        self.assertEqual(self.totals()['balance'],0)

    def test_opening_balance_is_replaced_and_does_not_become_income(self):
        self.income(); self.send('50rb makan')
        for amount in ('500rb','700rb'):
            self.click(f'wform:opening:{self.common}'); p=self.send(amount); self.click(self.action(p,'wsave:'))
        self.assertEqual(self.totals()['balance'],2650000)
        self.assertEqual(self.totals()['income'],2000000)
        self.assertEqual(len(self.store.money_rows(111)),1)
        self.assertIn('Saldo awal periode: Rp700.000',self.send('/saldo').text)

    def test_names_casefold_and_limit_and_rename_preserve_ids(self):
        bank=self.wallet('Bank'); self.store.set_default_wallet(111,bank)
        self.send('50rb bensin | | bAnK')
        self.assertEqual(self.store.get(111,1)['wallet_id'],bank)
        self.assertEqual(self.store.get(111,1)['category'],'Transportasi')
        self.click(f'wform:name:{bank}'); preview=self.send('BCA'); self.click(self.action(preview,'wsave:'))
        self.assertEqual(self.store.default_wallet(111)['name'],'BCA')
        self.assertEqual(self.totals(bank)['expense'],50000)
        with self.assertRaises(ValueError): self.wallet('bca')
        with self.assertRaises(ValueError): self.wallet('Nama | Salah')
        for i in range(18): self.wallet('Dompet '+str(i))
        with self.assertRaises(ValueError): self.wallet('Melebihi batas')

    def test_stale_wallet_confirmation_and_receipt_rollback(self):
        self.click(f'wform:opening:{self.common}'); old=self.send('10rb'); new=self.send('20rb')
        self.assertIn('terbaru',self.click(self.action(old,'wsave:')).text)
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError): self.click(self.action(new,'wsave:'))
        self.assertIsNone(self.store.wallet(111,self.common)['opening_balance'])
        self.click(self.action(new,'wsave:')); self.assertEqual(self.totals()['opening'],20000)

    def test_batch_can_select_different_wallets_and_unknown_wallet_is_atomic(self):
        bank=self.wallet('Bank'); cash=self.wallet('Tunai')
        self.send('50rb bensin | Transportasi | Bank\n20rb makan | | Tunai\n15rb minum')
        self.assertEqual([self.totals(w)['expense'] for w in (bank,cash,self.common)],[50000,20000,15000])
        reply=self.send('10rb kopi | Makanan | Bank\n5rb roti | Makanan | Hilang')
        self.assertIn('belum ada',reply.text)
        self.assertEqual(len(self.store.history(111)),3)
        self.assertEqual(self.totals(bank)['expense'],50000)

    def test_default_wallet_is_used_by_expenses_and_income_and_survives_restart(self):
        bank=self.wallet('Bank'); self.click(f'wdefault:{bank}'); self.restart()
        self.send('25rb makan'); self.income('300rb uang saku')
        self.assertEqual(self.totals(bank)['balance'],275000)
        self.assertEqual(self.totals()['balance'],0)
        self.assertIn('Dompet bawaan: Bank',self.send('/catat').text)

    def test_income_confirm_cancel_repeat_and_user_isolation(self):
        p=self.send('/pemasukan 2jt gaji'); self.assertEqual(self.store.money_rows(111),[])
        self.click('cancel'); self.assertEqual(self.store.money_rows(111),[])
        p=self.send('/pemasukan 2jt gaji'); action=self.action(p,'msave:')
        reply=self.click(action,qid='incomeonce'); self.click(action,qid='incomeonce'); self.click(action)
        self.assertIn('Tercatat 1 pemasukan',reply.text)
        self.assertEqual(self.totals()['income'],2000000)
        self.assertEqual(self.store.history(111),[])
        self.assertEqual(self.store.money_rows(222),[])

    def test_income_wallet_selection_backdate_and_local_timezone(self):
        bank=self.wallet('Bank'); self.current=datetime(2026,9,24,17,30,tzinfo=timezone.utc)
        p=self.send('/pemasukan 100rb hadiah'); token=self.store.pending(111)['token']
        self.click(f'wpick:{token}:wallet:0'); p=self.click(f'wset:{token}:wallet:{bank}')
        self.click(self.action(p,'msave:'))
        row=self.store.money_rows(111)[0]
        self.assertEqual((row['occurred_on'],row['wallet_id']),('2026-09-25',bank))
        row,_=self.income('2026-08-31 50rb uang saku | Hadiah | Bank')
        self.assertEqual(self.totals(bank)['income'],150000)
        self.assertEqual(self.store.cash_period(111,date(2026,9,1),date(2026,10,1))['beginning'],50000)

    def test_income_invalid_batch_future_zero_and_foreign_wallet_never_writes(self):
        for text in ('0 gaji','100 gaji\n100 saku','2026-09-25 100 gaji','10rb uang | Lainnya | Tidak ada'):
            reply=self.send('/pemasukan '+text)
            self.assertIn('Belum disimpan',reply.text)
        foreign=self.wallet('Asing',uid=222)
        self.send('/pemasukan 100 gaji'); token=self.store.pending(111)['token']
        self.assertIn('tidak ditemukan',self.click(f'wset:{token}:wallet:{foreign}').text)
        self.assertEqual(self.store.money_rows(111),[])
        self.assertEqual(self.store.history(111),[])

    def test_income_expiry_commands_cancel_and_restart_pending(self):
        p=self.send('/pemasukan 1000 uang saku'); self.restart()
        self.click(self.action(p,'msave:')); self.assertEqual(self.totals()['income'],1000)
        self.send('/pemasukan'); self.current+=timedelta(minutes=31)
        self.assertIn('habis',self.send('5000 uang saku').text)
        self.assertEqual(self.store.history(111),[])
        p=self.send('/pemasukan 1000 uang saku'); self.send('/menu'); self.click(self.action(p,'msave:'))
        self.assertEqual(self.totals()['income'],1000)

    def test_money_preview_nonce_and_active_field_block_old_confirmation(self):
        p=self.send('/pemasukan 1000 gaji'); old=self.action(p,'msave:'); token=self.store.pending(111)['token']
        self.click(f'mf:{token}:amount'); self.assertIn('terbaru',self.click(old).text)
        new=self.send('2000'); self.assertIn('terbaru',self.click(old).text)
        self.click(self.action(new,'msave:')); self.assertEqual(self.totals()['income'],2000)

    def test_income_edit_amount_date_wallet_delete_restore_updates_balances(self):
        bank=self.wallet('Bank'); row,_=self.income('100rb saku')
        p=self.click(f"medit:{row['id']}"); token=self.store.pending(111)['token']
        self.click(f'mf:{token}:amount'); self.send('200rb')
        self.click(f'mf:{token}:occurred_on'); self.send('2026-08-31')
        p=self.click(f'wset:{token}:wallet:{bank}'); self.click(self.action(p,'msave:'))
        self.assertEqual((self.totals()['balance'],self.totals(bank)['balance']),(0,200000))
        self.assertEqual(self.store.cash_period(111,date(2026,9,1),date(2026,10,1))['beginning'],200000)
        p=self.click(f"mstatusask:{row['id']}"); self.assertEqual(self.totals(bank)['income'],200000)
        self.click(self.action(p,'mstatus:')); self.assertEqual(self.totals(bank)['income'],0)
        p=self.click(f"mstatusask:{row['id']}"); self.click(self.action(p,'mstatus:'))
        self.assertEqual(self.totals(bank)['income'],200000)

    def test_stale_income_edit_and_delete_buttons_do_not_change_new_values(self):
        row,_=self.income('100rb saku'); old=self.click(f"mstatusask:{row['id']}")
        p=self.click(f"medit:{row['id']}"); token=self.store.pending(111)['token']
        self.click(f'mf:{token}:amount'); p=self.send('200rb'); self.click(self.action(p,'msave:'))
        self.assertIn('sudah berubah',self.click(self.action(old,'mstatus:')).text)
        self.assertEqual(self.totals()['income'],200000)

    def test_transfer_requires_two_wallets_and_different_source_destination(self):
        self.assertIn('minimal dua dompet',self.send('/transfer').text)
        bank=self.wallet('Bank'); self.send('/transfer'); token=self.store.pending(111)['token']
        self.click(f'wset:{token}:wallet:{bank}')
        self.assertIn('harus berbeda',self.click(f'wset:{token}:to:{bank}').text)
        self.assertEqual(self.store.money_rows(111),[])

    def test_transfer_moves_both_sides_preserves_total_and_does_not_consume_budget(self):
        bank=self.wallet('Bank',500000); cash=self.wallet('Tunai',100000)
        self.store.set_budget(111,'2026-09',50000)
        self.store.set_category_limit(111,'2026-09','Transfer',50000)
        row,reply=self.transfer(bank,cash,'200rb tarik tunai')
        self.assertEqual((self.totals(bank)['balance'],self.totals(cash)['balance']),(300000,300000))
        self.assertEqual(self.store.cash_period(111,date(2026,9,1),date(2026,10,1))['balance'],600000)
        self.assertEqual(self.store.history(111),[])
        self.assertIsNone(self.store.budget_notice(111,'2026-09'))
        self.assertEqual(self.store.category_notices(111,'2026-09'),[])
        self.assertNotIn('Batas 100%',reply.text)
        self.assertEqual(row['kind'],'transfer')

    def test_transfer_is_only_recorded_after_confirmation_and_repeated_click_is_safe(self):
        bank=self.wallet('Bank'); self.send('/transfer'); token=self.store.pending(111)['token']
        self.click(f'wset:{token}:wallet:{bank}'); self.click(f'wset:{token}:to:{self.common}')
        p=self.send('100rb'); self.assertEqual(self.store.money_rows(111),[])
        key=self.action(p,'msave:'); self.click(key); self.click(key)
        self.assertEqual(len(self.store.money_rows(111)),1)
        self.assertEqual((self.totals(bank)['balance'],self.totals()['balance']),(-100000,100000))

    def test_transfer_edit_delete_and_restore_keep_both_sides_consistent(self):
        bank=self.wallet('Bank',500000); cash=self.wallet('Tunai',0); dana=self.wallet('DANA',0)
        row,_=self.transfer(bank,cash)
        self.click(f"medit:{row['id']}"); token=self.store.pending(111)['token']
        self.click(f'mf:{token}:amount'); self.send('150rb'); p=self.click(f'wset:{token}:to:{dana}')
        self.click(self.action(p,'msave:'))
        self.assertEqual([self.totals(w)['balance'] for w in (bank,cash,dana)],[350000,0,150000])
        p=self.click(f"mstatusask:{row['id']}"); key=self.action(p,'mstatus:'); self.click(key); self.click(key)
        self.assertEqual([self.totals(w)['balance'] for w in (bank,cash,dana)],[500000,0,0])
        p=self.click(f"mstatusask:{row['id']}"); self.click(self.action(p,'mstatus:'))
        self.assertEqual([self.totals(w)['balance'] for w in (bank,cash,dana)],[350000,0,150000])

    def test_backdated_transfer_affects_month_opening_without_becoming_income(self):
        bank=self.wallet('Bank',200000)
        self.transfer(bank,self.common,'2026-08-31 100rb tarik tunai')
        self.assertEqual(self.store.wallet_totals(111,self.common,date(2026,9,1))['balance'],100000)
        t=self.store.cash_period(111,date(2026,9,1),date(2026,10,1))
        self.assertEqual((t['beginning'],t['income'],t['expense'],t['balance']),(200000,0,0,200000))

    def test_money_commit_and_transfer_roll_back_if_receipt_write_fails(self):
        bank=self.wallet('Bank'); self.send('/transfer'); token=self.store.pending(111)['token']
        self.click(f'wset:{token}:wallet:{bank}'); self.click(f'wset:{token}:to:{self.common}'); p=self.send('100rb')
        with patch.object(self.store,'save_receipt',side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError): self.click(self.action(p,'msave:'))
        self.assertEqual(self.store.money_rows(111),[])
        self.assertEqual((self.totals(bank)['balance'],self.totals()['balance']),(0,0))
        self.click(self.action(p,'msave:')); self.assertEqual(len(self.store.money_rows(111)),1)

    def test_store_permanent_source_identity_survives_deleted_record(self):
        row,_=self.income('1000 uang')
        self.store.set_money_deleted(111,row['id'],row['revision'],True)
        again,added=self.store.save_money(111,{k:row[k] for k in MONEY_FIELDS},row['source_key'],self.current.isoformat())
        self.assertFalse(added); self.assertEqual(again['id'],row['id']); self.assertTrue(again['deleted'])
        self.assertEqual(self.totals()['income'],0)

    def test_expense_wallet_edit_history_and_undo_move_spending_between_wallets(self):
        bank=self.wallet('Bank'); self.send('50rb bensin')
        self.click('editopen:1'); token=self.store.pending(111)['token']
        p=self.click(f'wset:{token}:wallet:{bank}'); self.assertIn('PERUBAHAN DOMPET',p.text)
        self.assertEqual(self.totals()['expense'],50000)
        saved=self.click(self.action(p,'editsave:'))
        self.assertEqual((self.totals()['expense'],self.totals(bank)['expense']),(0,50000))
        change=self.store.changes(111)[0]
        self.assertIn('Sebelum: Umum',self.click(f"change:{change['id']}").text)
        p=self.click(f"undoask:{change['id']}"); self.click(self.action(p,'undoyes:'))
        self.assertEqual((self.totals()['expense'],self.totals(bank)['expense']),(50000,0))

    def test_expense_delete_restore_and_bulk_category_changes_do_not_lose_wallet(self):
        bank=self.wallet('Bank'); self.send('50rb bensin | Transportasi | Bank\n20rb makan | Makanan | Bank')
        self.click('deleteyes:1:0'); self.assertEqual(self.totals(bank)['expense'],20000)
        self.click('restore:1:0'); self.assertEqual(self.totals(bank)['expense'],70000)
        selected={str(r['id']):r['revision'] for r in self.store.history(111)}
        self.store.apply_bulk(111,selected,'category','Kantor',self.current.isoformat())
        self.assertEqual(self.totals(bank)['expense'],70000)
        self.assertTrue(all(r['wallet_id']==bank for r in self.store.history(111)))

    def test_favorite_and_bill_templates_keep_wallet_and_allow_one_time_override(self):
        bank=self.wallet('Bank'); cash=self.wallet('Tunai')
        rid=self.favorite(expense='50rb bensin | Transportasi | Bank')
        p=self.click(f'favuse:{rid}'); self.assertIn('Dompet pembayaran: Bank',p.text)
        token=self.store.pending(111)['token']; p=self.click(f'wset:{token}:wallet:{cash}'); self.click(self.action(p,'quickcommit:'))
        self.assertEqual(self.totals(cash)['expense'],50000)
        self.assertEqual(self.store.owned('favorites',111,rid)['wallet_id'],bank)
        bid=self.bill(expense='300rb internet | Tagihan | Bank',day='25')
        p=self.click(f'billpay:{bid}:2026-09'); self.click(self.action(p,'quickcommit:')); self.click(f'billpay:{bid}:2026-09')
        self.assertEqual(self.totals(bank)['expense'],300000)

    def test_quick_wallet_picker_prevents_text_becoming_expense_and_old_commit(self):
        self.wallet('Bank'); rid=self.favorite()
        p=self.click(f'favuse:{rid}'); old=self.action(p,'quickcommit:'); token=self.store.pending(111)['token']
        self.click(f'wpick:{token}:wallet:0'); self.assertIn('Selesaikan',self.click(old).text)
        self.assertIn('Pilih dompet',self.send('50000 bensin').text)
        self.assertEqual(self.store.history(111),[])

    def test_monthly_cash_balance_and_expense_budget_are_distinct(self):
        self.store.update_wallet(111,self.common,0,opening=500000)
        self.income('2026-08-20 1jt gaji'); self.send('2026-08-21 200rb makan')
        self.income('2026-09-01 2jt gaji'); self.send('2026-09-05 50rb bensin')
        self.store.set_budget(111,'2026-09',100000)
        t=self.store.cash_period(111,date(2026,9,1),date(2026,10,1))
        self.assertEqual(t,dict(beginning=1300000,income=2000000,expense=50000,balance=3250000,configured=True))
        self.assertIn('Sisa anggaran: Rp50.000',self.send('/anggaran').text)
        self.assertIn('Saldo tercatat: Rp3.250.000',self.send('/menu').text)

    def test_all_new_commands_and_actions_are_scoped_to_owner(self):
        bank=self.wallet('Bank'); row,_=self.income()
        for command in ('/dompet','/saldo','/transfer','/pemasukan'):
            self.assertIn('belum diberi akses',self.send(command,uid=333).text)
        for action in (f'wallet:{bank}',f'whistory:{bank}:0',f'wdefault:{bank}',f'wform:opening:{bank}',
                       f"money:{row['id']}",f"medit:{row['id']}",f"mstatus:{row['id']}:0:1"):
            self.assertIn('tidak ditemukan',self.click(action,uid=222).text)
        self.assertEqual(self.totals()['income'],2000000)
        self.assertNotIn('gaji',self.click('mhistory:income:0:0',uid=222).text)

    def test_pagination_and_callback_byte_limits(self):
        for i in range(8): self.wallet(str(i)+'字'*30)
        reply=self.click('wallets:1'); self.assertIn('Sebelumnya',str(reply.buttons))
        self.income('1 uang')
        replies=[reply,self.send('/saldo'),self.send('/menu'),self.click('wallet:'+str(self.common)),self.send('/pemasukan 1 uang')]
        token=self.store.pending(111)['token']; replies.append(self.click(f'wpick:{token}:wallet:1'))
        for reply in replies:
            for row in reply.buttons:
                for b in row: self.assertLessEqual(len(b['callback_data'].encode()),64)

    def test_cash_excel_values_formulas_wallets_types_and_privacy(self):
        bank=self.wallet('Bank',500000); cash=self.wallet('Tunai',0)
        self.income('2jt gaji | Gaji | Bank'); self.transfer(bank,cash,'200rb tarik tunai'); self.send('50rb makan | Makanan | Tunai')
        self.income('999999 rahasia orang lain',uid=222)
        result=self.click('cashxlsx:2026-09'); self.assertEqual(result.document.filename,'arus-kas-2026-09.xlsx')
        summary=xml_sheet(result.document.content,1); detail=xml_sheet(result.document.content,2)
        for address,value in [('B5',500000),('B6',2000000),('B7',50000),('B8',2450000)]:
            self.assertEqual(int(cell(summary,address).find('s:v',NS).text),value)
            self.assertIsNotNone(cell(summary,address).find('s:f',NS))
        data=ET.tostring(detail,encoding='unicode'); self.assertNotIn('rahasia',data)
        self.assertIn('Transfer',data); self.assertIn('Tunai',data); self.assertIn('Bank',data)
        self.assertEqual(detail.find('s:autoFilter',NS).get('ref'),'A7:H10')
        self.assertEqual(cell(detail,'H8').get('t'),None)
        self.assertEqual(self.send('/excel').document.filename,'pengeluaran-2026-09.xlsx')
        expense_detail=xml_sheet(self.send('/excel').document.content,2)
        self.assertEqual(cell(expense_detail,'F8').find('s:is/s:t',NS).text,'Tunai')

    def test_cash_excel_empty_deleted_records_and_formula_like_notes_are_safe(self):
        result=self.click('cashxlsx:2026-09'); self.assertEqual(cell(xml_sheet(result.document.content,1),'B8').find('s:v',NS).text,'0')
        row,_=self.income('100 =HYPERLINK("x")')
        detail=xml_sheet(self.click('cashxlsx:2026-09').document.content,2)
        self.assertEqual(cell(detail,'F8').get('t'),'inlineStr'); self.assertIsNone(cell(detail,'F8').find('s:f',NS))
        self.store.set_money_deleted(111,row['id'],0,True)
        summary=xml_sheet(self.click('cashxlsx:2026-09').document.content,1)
        self.assertEqual(cell(summary,'B6').find('s:v',NS).text,'0')

    def test_backup_roundtrip_preserves_all_balances_wallets_and_deleted_money(self):
        bank=self.wallet('Bank',500000); cash=self.wallet('Tunai',0)
        income,_=self.income('2jt gaji | Gaji | Bank'); transfer,_=self.transfer(bank,cash)
        self.store.set_money_deleted(111,income['id'],0,True)
        self.send('20rb makan | Makanan | Tunai')
        self.store.set_default_wallet(111,bank)
        backup=self.root/'snapshot.db'; target=self.root/'restored.db'; snapshot_database(self.store.db,backup)
        result=restore_database(backup,target,lambda s:True)
        self.assertEqual(result['summary']['transfers'],1)
        restored=Store(target)
        try:
            self.assertEqual(restored.default_wallet(111)['id'],bank)
            for wid in (self.common,bank,cash): self.assertEqual(restored.wallet_totals(111,wid),self.totals(wid))
            self.assertTrue(restored.money_entry(111,income['id'])['deleted'])
            restored.set_money_deleted(111,income['id'],1,False)
            self.assertEqual(restored.wallet_totals(111,bank)['balance'],2400000)
            new=dict(restored.money_entry(111,transfer['id'])); values={k:new[k] for k in MONEY_FIELDS}
            row,_=restored.save_money(111,values,'money:111111111111',self.current.isoformat())
            self.assertGreater(row['id'],transfer['id'])
        finally: restored.close()

    def test_restore_rejects_foreign_wallet_and_keeps_target_bytes(self):
        self.income(); self.wallet('Asing',uid=222)
        backup=self.root/'bad.db'; snapshot_database(self.store.db,backup)
        db=sqlite3.connect(backup); foreign=db.execute('SELECT id FROM wallets WHERE user_id=222').fetchone()[0]
        db.execute('UPDATE money_entries SET wallet_id=?',(foreign,)); db.commit(); db.close()
        target=self.root/'target.db'; target.write_bytes(b'keep me')
        with self.assertRaises(ValueError): restore_database(backup,target,lambda s:True)
        self.assertEqual(target.read_bytes(),b'keep me')

    def test_v23_migration_assigns_legacy_records_to_common_without_guessing(self):
        legacy=self.root/'v23.db'; db=sqlite3.connect(legacy)
        db.executescript('''CREATE TABLE expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,
          message_id INTEGER NOT NULL,line_no INTEGER NOT NULL DEFAULT 0,spent_on TEXT NOT NULL,
          amount INTEGER NOT NULL CHECK(amount>0),note TEXT NOT NULL,category TEXT NOT NULL,
          created_at TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,
          UNIQUE(chat_id,message_id,line_no));
          INSERT INTO expenses VALUES(17,111,111,100,0,'2026-09-01',50000,'bensin','Transportasi','2026-09-01T00:00:00+07:00',0,0);
          INSERT INTO expenses VALUES(18,111,111,100,1,'2026-09-01',20000,'makan','Makanan','2026-09-01T00:00:00+07:00',1,0);
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          INSERT INTO metadata VALUES('schema_version','2.3');''')
        db.commit(); db.close()
        snapshot=backup_before_upgrade(legacy); self.assertIn('before-v2.4',snapshot.name)
        store=Store(legacy)
        try:
            wallet=store.default_wallet(111); self.assertEqual(wallet['name'],'Umum'); self.assertIsNone(wallet['opening_balance'])
            self.assertEqual(store.get(111,17)['wallet_id'],wallet['id'])
            self.assertEqual(store.get(111,18)['deleted'],1)
            self.assertEqual(store.wallet_totals(111,wallet['id'])['balance'],-50000)
            self.assertIsNone(backup_before_upgrade(legacy))
        finally: store.close()
        restored=self.root/'old-restored.db'; restore_database(snapshot,restored,lambda s:True)
        store=Store(restored)
        try: self.assertEqual(store.wallet_totals(111,store.default_wallet(111)['id'])['expense'],50000)
        finally: store.close()


if __name__=='__main__': unittest.main(verbosity=2)
