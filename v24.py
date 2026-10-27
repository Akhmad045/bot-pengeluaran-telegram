"""Pemasukan, saldo, dan pemilihan dompet melalui tombol Telegram."""
from dataclasses import replace
from datetime import timedelta
import json
import re
import secrets

from core import day_label, month_range, parse_amount, parse_expense, read_day, rupiah
from features import FIELD_NAMES, PAGE_SIZE, month_label
from storage_v24 import MONEY_FIELDS, wallet_name
from ui import Reply, button, navigation
from v23 import SmartFeatures, clean_label


class WalletFeatures(SmartFeatures):
    def feature_command(self, uid, command, arg):
        if command=='/dompet': return self.wallets_view(uid)
        if command=='/saldo': return self.cash_view(uid,arg or self.now(uid).strftime('%Y-%m'))
        if command=='/pemasukan':
            reply=self.begin_money(uid,'income')
            return self.pending_input(uid,arg) if arg else reply
        if command=='/transfer':
            if arg: raise ValueError('Gunakan /transfer tanpa isian, lalu pilih dompet melalui tombol.')
            return self.begin_money(uid,'transfer')
        return super().feature_command(uid,command,arg)

    def feature_callback(self, uid, parts):
        action=parts[0]
        if action=='wallets': return self.wallets_view(uid,int(parts[1]) if len(parts)>1 else 0)
        if action=='wallet': return self.wallet_view(uid,int(parts[1]))
        if action=='wdefault':
            self.store.set_default_wallet(uid,int(parts[1])); return self.wallet_view(uid,int(parts[1]))
        if action=='whistory': return self.wallet_history(uid,int(parts[1]),int(parts[2]))
        if action=='wform': return self.wallet_form(uid,parts[1],int(parts[2]))
        if action=='wsave': return self.save_wallet_form(uid,parts[1],parts[2])
        if action=='cash': return self.cash_view(uid,parts[1])
        if action=='cashxlsx': return self.cash_excel(uid,parts[1])
        if action=='moneynew': return self.begin_money(uid,parts[1])
        if action=='mhistory': return self.money_history(uid,parts[1],int(parts[2]),int(parts[3]))
        if action=='money': return self.money_view(uid,int(parts[1]))
        if action=='medit':
            row=self.store.money_entry(uid,int(parts[1]))
            if row['deleted']: raise ValueError('Pulihkan transaksi sebelum mengedit.')
            state=self.store.start_pending(uid,'money',{'values':{k:row[k] for k in MONEY_FIELDS},
                 'rid':row['id'],'revision':row['revision'],'step':'confirm'},self.stamp())
            return self.money_preview(state)
        if action=='mf':
            state=self.require_pending(uid,parts[1],'money')
            field=parts[2]
            if field not in ('amount','note','category','occurred_on'): raise ValueError('Kolom tidak dikenal.')
            if field=='category' and state['data']['values']['kind']=='transfer': raise ValueError('Kategori transfer tetap Transfer.')
            state['data']['step']=field
            self.store.update_pending(uid,parts[1],state['data'],self.stamp())
            example={'amount':'500rb','note':'Gaji bulan ini','category':'Gaji','occurred_on':'2026-09-24 (YYYY-MM-DD)'}[field]
            return Reply('Kirim '+{'amount':'nominal','note':'keterangan','category':'kategori','occurred_on':'tanggal'}[field]+' baru, misalnya '+example+'.',[
                [button('Kembali ke tinjauan',f'mback:{parts[1]}'),button('Batal','cancel')]])
        if action=='mback':
            state=self.require_pending(uid,parts[1],'money'); state['data']['step']='confirm'
            return self.money_preview(state)
        if action=='msave': return self.commit_money(uid,parts[1],parts[2])
        if action=='mstatusask':
            row=self.store.money_entry(uid,int(parts[1])); target=not bool(row['deleted'])
            title='HAPUS TRANSAKSI?' if target else 'PULIHKAN TRANSAKSI?'
            return Reply(title+'\n\n'+self.money_description(uid,row)+'\n\nSaldo dompet terkait akan dihitung ulang.',[
                [button('Ya, lanjutkan',f"mstatus:{row['id']}:{row['revision']}:{int(target)}"),button('Batal',f"money:{row['id']}")]])
        if action=='mstatus':
            if parts[3] not in ('0','1'): raise ValueError('Pilihan tidak valid.')
            row=self.store.set_money_deleted(uid,int(parts[1]),int(parts[2]),parts[3]=='1')
            reply=self.money_view(uid,row['id'])
            reply.text=('Transaksi dihapus dari perhitungan.' if row['deleted'] else 'Transaksi dipulihkan.')+'\n\n'+reply.text
            return reply
        if action=='wpick': return self.wallet_picker(uid,parts[1],parts[2],int(parts[3]))
        if action=='wset': return self.select_wallet(uid,parts[1],parts[2],int(parts[3]))
        return super().feature_callback(uid,parts)

    def menu(self, user):
        reply=self.base_menu(user); uid=user['id']
        wallets=self.store.wallets(uid)
        total=sum(self.store.wallet_totals(uid,w['id'])['balance'] for w in wallets)
        ready=all(w['opening_balance'] is not None for w in wallets)
        text=('Saldo tercatat: ' if ready else 'Saldo sementara: ')+rupiah(total)
        if not ready: text+='\nAtur saldo awal setiap dompet agar saldo lengkap.'
        reply.text+='\n\n'+text
        reply.buttons.insert(2,[button('👛 Saldo & dompet',f"cash:{self.now(uid):%Y-%m}")])
        return reply

    def add_prompt(self, uid=None):
        reply=super().add_prompt(uid)
        reply.buttons.insert(0,[button('💵 Pemasukan','moneynew:income'),button('↔ Transfer','moneynew:transfer')])
        if uid is not None:
            reply.text+='\nDompet bawaan: '+self.store.default_wallet(uid)['name']
            reply.text+='\nPilih sumber pembayaran: 50rb bensin | Transportasi | Tunai\nBuat nama dompet melalui /dompet terlebih dahulu.'
        reply.buttons.insert(1,[button('👛 Kelola dompet','wallets:0')])
        return reply

    def history_menu(self):
        reply=super().history_menu()
        reply.buttons.insert(0,[button('💵 Pemasukan','mhistory:income:0:0'),button('↔ Transfer','mhistory:transfer:0:0')])
        return reply

    def reports_menu(self, uid):
        reply=super().reports_menu(uid)
        reply.buttons.insert(0,[button('👛 Saldo & arus kas',f'cash:{self.now(uid):%Y-%m}')])
        return reply

    def settings_menu(self, uid):
        reply=super().settings_menu(uid)
        reply.buttons.insert(0,[button('👛 Dompet & saldo awal','wallets:0')])
        return reply

    def categorize_expenses(self, uid, expenses, text):
        lines=[line for line in text.splitlines() if line.strip()]
        return [expense if len(line.split('|'))>1 and line.split('|')[1].strip() else
                replace(expense,category=self.store.automatic_category(uid,expense.note))
                for expense,line in zip(expenses,lines)]

    def wallet_label(self, uid, wid):
        return self.store.wallet(uid,wid)['name']

    def wallets_view(self, uid, page=0):
        wallets=self.store.wallets(uid); default=self.store.default_wallet(uid)['id']
        page=max(0,min(page,(len(wallets)-1)//PAGE_SIZE))
        lines=['DOMPET','Saldo berdasarkan catatan bot. Pilih dompet untuk mengatur saldo awal.','']; buttons=[]
        for i,row in enumerate(wallets[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            totals=self.store.wallet_totals(uid,row['id'])
            lines.append(f"{i}. {row['name']}{' (bawaan)' if row['id']==default else ''} — {rupiah(totals['balance'])}"+
                         ('' if totals['configured'] else '\n   Sementara: saldo awal belum diatur.'))
            buttons.append([button(f"{i}. {row['name']}",f"wallet:{row['id']}")])
        return Reply('\n'.join(lines),buttons+self.pages('wallets',page,len(wallets))+[
            [button('Tambah dompet','wform:new:0')],[button('Saldo & arus kas',f'cash:{self.now(uid):%Y-%m}')]]+navigation())

    def wallet_view(self, uid, wid):
        wallet=self.store.wallet(uid,wid); t=self.store.wallet_totals(uid,wid)
        text=f"DOMPET {wallet['name']}\n\nSaldo awal: "+(rupiah(t['opening']) if t['configured'] else 'Belum diatur (sementara Rp0)')
        text+=f"\nPemasukan: {rupiah(t['income'])}\nPengeluaran: {rupiah(t['expense'])}\nTransfer masuk: {rupiah(t['transfer_in'])}\nTransfer keluar: {rupiah(t['transfer_out'])}\n\nSaldo {'tercatat' if t['configured'] else 'sementara'}: {rupiah(t['balance'])}"
        text+='\n\nSaldo awal adalah saldo sebelum seluruh transaksi dompet ini yang dicatat di bot. Saldo dihitung dari semua tanggal.'
        if t['balance']<0: text+='\nSaldo negatif: periksa kelengkapan saldo awal dan transaksi.'
        default=self.store.default_wallet(uid)['id']==wid
        buttons=[[button('Atur saldo awal',f'wform:opening:{wid}'),button('Ganti nama',f'wform:name:{wid}')],
                 [button('Riwayat dompet',f'whistory:{wid}:0')]]
        if not default: buttons.append([button('Jadikan dompet bawaan',f'wdefault:{wid}')])
        else: text+='\nDompet ini dipakai jika sumber pembayaran tidak ditulis.'
        return Reply(text,buttons+[[button('Daftar dompet','wallets:0')]]+navigation())

    def wallet_form(self, uid, field, wid):
        if field not in ('new','name','opening'): raise ValueError('Pilihan dompet tidak dikenal.')
        row=None if field=='new' else self.store.wallet(uid,wid)
        self.store.start_pending(uid,'wallet_form',{'field':field,'wid':wid,'revision':row['revision'] if row else None,'value':None},self.stamp())
        text=('Kirim nama dompet, misalnya Tunai, Bank, atau DANA. Maksimal 32 karakter.' if field!='opening' else
              'Kirim saldo awal, misalnya 500rb atau 0.\n\nIni saldo sebelum SELURUH transaksi dompet yang tercatat, bukan saldo saat ini. '
              'Nominal akan menggantikan saldo awal sebelumnya dan tidak dihitung sebagai pemasukan.')
        return Reply(('TAMBAH DOMPET' if field=='new' else 'ATUR '+row['name'])+'\n\n'+text,[[button('Batal','cancel')]])

    def wallet_form_preview(self, state):
        data=state['data']; uid=state['user_id']; data['confirmation']=secrets.token_hex(4)
        self.store.update_pending(uid,state['token'],data,self.stamp())
        if data['field']=='opening':
            row=self.store.wallet(uid,data['wid']); t=self.store.wallet_totals(uid,row['id'])
            text=f"SIMPAN SALDO AWAL?\n\nDompet: {row['name']}\nSebelumnya: "+(rupiah(t['opening']) if t['configured'] else 'Belum diatur')
            text+=f"\nSaldo awal baru: {rupiah(data['value'])}\nSaldo hasil perhitungan: {rupiah(t['balance']-t['opening']+data['value'])}\n\nPengeluaran dan pemasukan lama tetap ikut dihitung."
        else: text=('BUAT DOMPET?' if data['field']=='new' else 'GANTI NAMA DOMPET?')+'\n\nNama: '+data['value']
        return Reply(text,[[button('Ya, simpan',f"wsave:{state['token']}:{data['confirmation']}"),button('Batal','cancel')]])

    def save_wallet_form(self, uid, token, confirmation):
        state=self.require_pending(uid,token,'wallet_form'); data=state['data']
        if data.get('confirmation')!=confirmation or data['value'] is None: raise ValueError('Gunakan tombol pada tinjauan terbaru.')
        if data['field']=='new': row=self.store.create_wallet(uid,data['value'])
        else: row=self.store.update_wallet(uid,data['wid'],data['revision'],**{
            'opening' if data['field']=='opening' else 'name':data['value']})
        self.store.cancel_pending(uid)
        reply=self.wallet_view(uid,row['id']); reply.text='Pengaturan disimpan.\n\n'+reply.text
        return reply

    def cash_view(self, uid, month):
        start,end=month_range(month); t=self.store.cash_period(uid,start,end)
        text=f"SALDO & ARUS KAS\n{month_label(month)}\n\nSaldo awal periode: {rupiah(t['beginning'])}\nPemasukan: {rupiah(t['income'])}\nPengeluaran: {rupiah(t['expense'])}\nSelisih pemasukan − pengeluaran: {rupiah(t['income']-t['expense'])}\n\nSaldo akhir periode: {rupiah(t['balance'])}"
        if not t['configured']: text+='\nSementara: ada dompet yang saldo awalnya belum diatur.'
        text+='\n\nGabungan seluruh dompet. Transfer antardompet tidak mengubah jumlah uang gabungan atau anggaran pengeluaran.'
        if month==self.now(uid).strftime('%Y-%m'): text+='\nBulan berjalan mengikuti transaksi yang sudah dicatat.'
        return Reply(text,[[button('👛 Dompet & saldo awal','wallets:0')],
            [button('💵 Catat pemasukan','moneynew:income'),button('↔ Transfer','moneynew:transfer')],
            [button('Riwayat pemasukan','mhistory:income:0:0'),button('Riwayat transfer','mhistory:transfer:0:0')],
            [button('Excel arus kas',f'cashxlsx:{month}')],
            [button('‹ Bulan sebelumnya',f'cash:{(start-timedelta(days=1)):%Y-%m}'),button('Bulan berikutnya ›',f'cash:{end:%Y-%m}')]]+navigation())

    def begin_money(self, uid, kind):
        if kind not in ('income','transfer'): raise ValueError('Jenis transaksi tidak dikenal.')
        if kind=='transfer' and len(self.store.wallets(uid))<2: raise ValueError('Buat minimal dua dompet melalui /dompet sebelum melakukan transfer.')
        values=dict(kind=kind,wallet_id=self.store.default_wallet(uid)['id'],to_wallet_id=None,amount=0,
                    note='',category='Lainnya' if kind=='income' else 'Transfer',occurred_on=self.now(uid).date().isoformat())
        state=self.store.start_pending(uid,'money',dict(values=values,rid=None,revision=None,step='input'),self.stamp())
        if kind=='transfer': return self.wallet_picker(uid,state['token'],'wallet')
        return Reply('CATAT PEMASUKAN\n\nKirim nominal dan keterangan, misalnya:\n2jt gaji | Gaji\n\n'
                     'Tanggal lain: 2026-09-20 500rb uang saku\nDompet tertentu: 2jt gaji | Gaji | Bank\n'
                     'Satu transaksi per pesan; periksa lalu konfirmasi sebelum disimpan.',[[button('Batal','cancel')]])

    def money_description(self, uid, values):
        text=values['note']+' — '+rupiah(values['amount'])+'\nTanggal: '+day_label(read_day(values['occurred_on']))
        if values['kind']=='income': text+='\nKategori: '+values['category']+'\nDompet penerima: '+self.wallet_label(uid,values['wallet_id'])
        else: text+='\nDari: '+self.wallet_label(uid,values['wallet_id'])+'\nKe: '+self.wallet_label(uid,values['to_wallet_id'])
        return text

    def money_preview(self, state):
        uid,token,data=state['user_id'],state['token'],state['data']; values=data['values']
        self.store.validate_money(uid,values)
        data['step']='confirm'; data['confirmation']=secrets.token_hex(4)
        self.store.update_pending(uid,token,data,self.stamp())
        text=('SIMPAN PERUBAHAN?' if data['rid'] else ('CATAT PEMASUKAN?' if values['kind']=='income' else 'CATAT TRANSFER?'))+'\n\n'+self.money_description(uid,values)
        if values['kind']=='transfer': text+='\n\nTransfer memindahkan saldo dan tidak dihitung sebagai pengeluaran. Catat biaya admin secara terpisah sebagai pengeluaran.'
        text+='\n\nBelum disimpan. Periksa nominal, tanggal, dan dompet.'
        buttons=[[button('Ya, simpan',f"msave:{token}:{data['confirmation']}")],
                 [button('Nominal',f'mf:{token}:amount'),button('Tanggal',f'mf:{token}:occurred_on')],
                 [button('Keterangan',f'mf:{token}:note')]]
        if values['kind']=='income': buttons[-1].append(button('Kategori',f'mf:{token}:category'))
        buttons.append([button('Dompet penerima' if values['kind']=='income' else 'Dompet asal',f'wpick:{token}:wallet:0')])
        if values['kind']=='transfer': buttons[-1].append(button('Dompet tujuan',f'wpick:{token}:to:0'))
        buttons.append([button('Batal','cancel')])
        return Reply(text,buttons)

    def commit_money(self, uid, token, confirmation):
        state=self.require_pending(uid,token,'money'); data=state['data']; values=data['values']
        if data.get('confirmation')!=confirmation or data['step']!='confirm': raise ValueError('Gunakan tombol pada tinjauan terbaru.')
        if read_day(values['occurred_on'])>self.now(uid).date(): raise ValueError('Tanggal tidak boleh di masa depan.')
        row,added=self.store.save_money(uid,values,'money:'+token,self.clock().isoformat(),data['rid'],data['revision'])
        self.store.cancel_pending(uid)
        reply=self.money_view(uid,row['id'])
        reply.text=('Perubahan disimpan.' if data['rid'] else ('Tercatat 1 '+('pemasukan.' if values['kind']=='income' else 'transfer.') if added else 'Transaksi sudah tercatat.'))+'\n\n'+reply.text
        return reply

    def money_view(self, uid, rid):
        row=self.store.money_entry(uid,rid)
        text=('PEMASUKAN' if row['kind']=='income' else 'TRANSFER ANTARDOMPET')+'\n\n'+self.money_description(uid,row)
        if row['deleted']: text+='\n\nDihapus; tidak dihitung dalam saldo.'
        else:
            for wid in dict.fromkeys([row['wallet_id']]+([row['to_wallet_id']] if row['kind']=='transfer' else [])):
                totals=self.store.wallet_totals(uid,wid)
                text+='\nSaldo '+self.wallet_label(uid,wid)+': '+rupiah(totals['balance'])+('' if totals['configured'] else ' (sementara)')
        buttons=[] if row['deleted'] else [[button('Edit transaksi',f'medit:{rid}')]]
        buttons.append([button('Pulihkan' if row['deleted'] else 'Hapus transaksi',f'mstatusask:{rid}')])
        buttons.append([button('Kembali ke riwayat',f"mhistory:{row['kind']}:{row['deleted']}:0")])
        return Reply(text,buttons+navigation())

    def money_history(self, uid, kind, deleted=0, page=0):
        if deleted not in (0,1): raise ValueError('Pilihan tidak valid.')
        rows=self.store.money_rows(uid,kind,deleted=bool(deleted)); page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        lines=[('RIWAYAT PEMASUKAN' if kind=='income' else 'RIWAYAT TRANSFER')+(' TERHAPUS' if deleted else ''),
               f'Jumlah: {len(rows)} catatan',f"Total nominal: {rupiah(sum(r['amount'] for r in rows))}",'']; buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f'{i}. '+self.money_description(uid,row)); buttons.append([button(f"{i}. {row['note'][:32]}",f"money:{row['id']}")])
        if not rows: lines.append('Belum ada transaksi pada daftar ini.')
        return Reply('\n'.join(lines),buttons+self.pages(f'mhistory:{kind}:{deleted}',page,len(rows))+[
            [button('Lihat aktif' if deleted else 'Pulihkan terhapus',f'mhistory:{kind}:{1-deleted}:0')],
            [button('Catat baru',f'moneynew:{kind}')]]+navigation())

    def wallet_history(self, uid, wid, page=0):
        wallet=self.store.wallet(uid,wid); items=[]
        for r in self.store.history(uid):
            if r['wallet_id']==wid: items.append((r['spent_on'],r['id'],'Pengeluaran',-r['amount'],r['note'],f"editopen:{r['id']}"))
        for r in self.store.money_rows(uid):
            if r['wallet_id']==wid or r['to_wallet_id']==wid:
                incoming=r['kind']=='income' or r['to_wallet_id']==wid
                items.append((r['occurred_on'],r['id'],'Pemasukan' if r['kind']=='income' else 'Transfer masuk' if incoming else 'Transfer keluar',
                              r['amount'] if incoming else -r['amount'],r['note'],f"money:{r['id']}"))
        items.sort(key=lambda r:(r[0],r[1],r[2]),reverse=True)
        page=max(0,min(page,max(0,(len(items)-1)//PAGE_SIZE)))
        lines=['RIWAYAT DOMPET '+wallet['name'],f'Jumlah: {len(items)} catatan','']; buttons=[]
        for i,(day,rid,kind,amount,note,action) in enumerate(items[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f'{i}. {note} — {rupiah(amount)}\n   {kind}, {day}')
            buttons.append([button(f'{i}. {note[:32]}',action)])
        if not items: lines.append('Belum ada transaksi aktif.')
        return Reply('\n'.join(lines),buttons+self.pages(f'whistory:{wid}',page,len(items))+[[button('Kembali',f'wallet:{wid}')]]+navigation())

    def wallet_picker(self, uid, token, field, page=0):
        state=self.store.pending(uid)
        if not state or state['kind'] not in ('money','quick','edit'): raise ValueError('Draf tidak tersedia.')
        state=self.require_pending(uid,token,state['kind'])
        if field not in ('wallet','to') or (field=='to' and (state['kind']!='money' or state['data']['values']['kind']!='transfer')):
            raise ValueError('Pilihan dompet tidak dikenal.')
        # Membuka pemilih menonaktifkan konfirmasi lama sampai tinjauan terbaru ditampilkan.
        if state['kind']=='money': state['data']['step']='wallet'
        elif state['kind']=='quick': state['data']['field']='wallet'
        else: state['data']['field']='wallet'
        self.store.update_pending(uid,token,state['data'],self.stamp())
        rows=self.store.wallets(uid)
        if state['kind']=='money' and state['data']['values']['kind']=='transfer':
            other=state['data']['values']['wallet_id' if field=='to' else 'to_wallet_id']
            rows=[r for r in rows if r['id']!=other]
        page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        title='PILIH DOMPET TUJUAN' if field=='to' else 'PILIH DOMPET'
        buttons=[[button(row['name'],f"wset:{token}:{field}:{row['id']}")] for row in rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE]]
        return Reply(title+'\n\nPilih sumber/penerima yang sesuai transaksi.',buttons+self.pages(f'wpick:{token}:{field}',page,len(rows))+[[button('Batal','cancel')]])

    def select_wallet(self, uid, token, field, wid):
        state=self.store.pending(uid)
        if not state or state['kind'] not in ('money','quick','edit'): raise ValueError('Draf tidak tersedia.')
        state=self.require_pending(uid,token,state['kind']); data=state['data']
        self.store.wallet(uid,wid)
        if field not in ('wallet','to') or (field=='to' and (state['kind']!='money' or data['values']['kind']!='transfer')):
            raise ValueError('Pilihan dompet tidak dikenal.')
        if state['kind']=='money' and data['values']['kind']=='transfer':
            other=data['values']['wallet_id' if field=='to' else 'to_wallet_id']
            if wid==other: raise ValueError('Dompet asal dan tujuan harus berbeda.')
        data['values']['wallet_id' if field=='wallet' else 'to_wallet_id']=wid
        if state['kind']=='money':
            self.store.update_pending(uid,token,data,self.stamp())
            if data['values']['kind']=='transfer' and data['values']['to_wallet_id'] is None: return self.wallet_picker(uid,token,'to')
            if not data['values']['amount']:
                data['step']='input'; self.store.update_pending(uid,token,data,self.stamp())
                return Reply('Kirim nominal transfer dan keterangan, misalnya 100rb top up.\nBoleh nominal saja: 100rb.',[[button('Batal','cancel')]])
            return self.money_preview(state)
        data['field']=None
        state=self.store.update_pending(uid,token,data,self.stamp())
        return self.quick_view(state) if state['kind']=='quick' else self.edit_view(state)

    def open_edit(self, uid, record_id):
        row=self.store.get(uid,record_id)
        if row is None or row['deleted']: return Reply('Pengeluaran tidak ditemukan atau sudah dihapus.')
        values={key:row[key] for key in tuple(FIELD_NAMES)+('wallet_id',)}
        state=self.store.start_pending(uid,'edit',{'id':record_id,'revision':row['revision'],'original':values,'values':dict(values),'field':None},self.stamp())
        return self.edit_view(state)

    def edit_view(self, state):
        reply=super().edit_view(state); uid=state['user_id']; data=state['data']; token=state['token']
        if 'wallet_id' not in data['values']:
            row=self.store.get(uid,data['id']); data['values']['wallet_id']=row['wallet_id']; data['original']['wallet_id']=row['wallet_id']
            self.store.update_pending(uid,token,data,self.stamp())
        reply.text+='\nDompet: '+self.wallet_label(uid,data['values']['wallet_id'])
        if data['values']['wallet_id']!=data['original']['wallet_id']:
            reply.text+='\nPERUBAHAN DOMPET BELUM DISIMPAN\n'+self.wallet_label(uid,data['original']['wallet_id'])+' → '+self.wallet_label(uid,data['values']['wallet_id'])
            if not any(b['callback_data'].startswith('editsave:') for row in reply.buttons for b in row):
                reply.buttons.insert(0,[button('✅ Simpan perubahan',f'editsave:{token}')])
        reply.buttons.insert(2,[button('Dompet pembayaran',f'wpick:{token}:wallet:0')])
        return reply

    def change_text(self, uid, change):
        text=super().change_text(uid,change)
        before,after=json.loads(change['before_json']),json.loads(change['after_json'])
        if 'wallet_id' in before and 'wallet_id' in after and before['wallet_id']!=after['wallet_id']:
            text+='\n\nDompet\nSebelum: '+self.wallet_label(uid,before['wallet_id'])+'\nSesudah: '+self.wallet_label(uid,after['wallet_id'])
        return text

    def quick_view(self, state):
        data=state['data']; uid=state['user_id']
        if 'wallet_id' not in data['values']:
            template=self.require_owned('favorites' if data['kind']=='favorite' else 'bills',uid,data['rid'])
            data['values']['wallet_id']=template['wallet_id'] or self.store.default_wallet(uid)['id']
        reply=super().quick_view(state)
        reply.text+='\nDompet pembayaran: '+self.wallet_label(uid,data['values']['wallet_id'])
        reply.buttons.insert(-1,[button('Ubah dompet',f"wpick:{state['token']}:wallet:0")])
        return reply

    def object_form_view(self, state):
        reply=super().object_form_view(state); wid=state['data']['values'].get('wallet_id')
        reply.text+='\nDompet: '+(self.wallet_label(state['user_id'],wid) if wid else 'Mengikuti dompet bawaan saat dicatat')
        return reply

    def favorite_view(self, uid, rid):
        reply=super().favorite_view(uid,rid); row=self.require_owned('favorites',uid,rid)
        reply.text+='\nDompet: '+(self.wallet_label(uid,row['wallet_id']) if row['wallet_id'] else 'Mengikuti dompet bawaan')
        return reply

    def bill_view(self, uid, rid, period=None):
        reply=super().bill_view(uid,rid,period); row=self.require_owned('bills',uid,rid)
        reply.text+='\nDompet template: '+(self.wallet_label(uid,row['wallet_id']) if row['wallet_id'] else 'Mengikuti dompet bawaan')
        return reply

    def pending_input(self, uid, text):
        state=self.store.pending(uid)
        if not state or state['expires_at']<=self.stamp(): return super().pending_input(uid,text)
        data=state['data']; token=state['token']
        if state['kind'] in ('edit','quick') and data.get('field')=='wallet':
            return Reply('Pilih dompet melalui tombol atau batalkan draf.',[[button('Pilih dompet',f'wpick:{token}:wallet:0'),button('Batal','cancel')]])
        if state['kind'] not in ('money','wallet_form'): return super().pending_input(uid,text)
        try:
            if state['kind']=='wallet_form':
                if data['field']=='opening': data['value']=0 if re.fullmatch(r'(?:Rp\s*)?0',text,re.I) else parse_amount(re.sub(r'^rp\s+','Rp',text,flags=re.I))
                else: data['value']=wallet_name(text)
                return self.wallet_form_preview(state)
            values=data['values']; step=data['step']
            if step=='wallet': return Reply('Pilih dompet melalui tombol atau kembali ke fitur.',[[button('Pilih dompet',f'wpick:{token}:wallet:0'),button('Batal','cancel')]])
            if step=='confirm': return self.money_preview(state)
            if step=='input':
                if len(text.splitlines())!=1: raise ValueError('Kirim satu transaksi pemasukan/transfer per pesan.')
                if values['kind']=='transfer' and len(text.split())==1: text+=' Transfer antardompet'
                expense=parse_expense(text,self.now(uid).date())
                values.update(amount=expense.amount,note=expense.note,occurred_on=expense.spent_on.isoformat())
                if values['kind']=='income':
                    values['category']=expense.category
                    if expense.wallet is not None: values['wallet_id']=self.store.resolve_wallet(uid,expense.wallet)
                elif '|' in text: raise ValueError('Untuk transfer cukup nominal dan keterangan; pilih dompet melalui tombol.')
            elif step=='amount': values['amount']=parse_amount(re.sub(r'^rp\s+','Rp',text,flags=re.I))
            elif step=='occurred_on':
                value=read_day(text)
                if value>self.now(uid).date(): raise ValueError('Tanggal tidak boleh di masa depan.')
                values['occurred_on']=str(value)
            elif step in ('note','category'):
                value=clean_label(text,160 if step=='note' else 32,'Keterangan' if step=='note' else 'Kategori')
                values[step]=value if step=='note' else value.capitalize()
            else: raise ValueError('Draf tidak dikenal. Batalkan lalu buka kembali fitur.')
            return self.money_preview(state)
        except ValueError as exc:
            return Reply(str(exc)+'\n\nBelum disimpan. Perbaiki nilai atau tekan Batal.',[[button('Batal','cancel')]])

    def cash_excel(self, uid, month):
        from excel_cash import build_cash_excel
        from ui import Document
        start,end=month_range(month)
        content=build_cash_excel(self.store,uid,start,end,self.now(uid).tzname())
        if len(content)>49*1024*1024: raise ValueError('File terlalu besar. Kurangi jumlah catatan dalam periode laporan.')
        return Reply('Excel arus kas '+month_label(month)+'. Saldo mengikuti transaksi dan saldo awal yang dicatat.',
                     document=Document(f'arus-kas-{month}.xlsx',content,'Arus kas '+month_label(month)))
