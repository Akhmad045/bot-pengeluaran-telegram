"""Alur pengguna versi 2.3; setiap pencatatan lewat tombol dikonfirmasi dahulu."""
from dataclasses import replace
from datetime import timedelta
import re
import secrets

from core import day_label, month_range, parse_amount, parse_expense, read_day, rupiah
from features import month_label, parse_time, PAGE_SIZE
from schedule_v23 import (REPORT_NAMES, bill_due, first_bill_month, make_summary,
                          next_report_time, report_window)
from ui import Reply, button, navigation
from v22 import NewFeatures


def clean_label(value, maximum, name):
    value=' '.join(value.split())
    if not 1<=len(value)<=maximum: raise ValueError(f'{name} wajib diisi, maksimal {maximum} karakter.')
    return value


class SmartFeatures(NewFeatures):
    def feature_command(self, uid, command, arg):
        if command in ('/kategoriotomatis','/aturan'): return self.rules_view(uid)
        if command=='/favorit': return self.favorites_view(uid)
        if command=='/rekapotomatis': return self.report_schedule_view(uid)
        if command=='/anggarankategori': return self.category_budget_view(uid,arg or self.now(uid).strftime('%Y-%m'))
        if command=='/tagihan': return self.bills_view(uid)
        return super().feature_command(uid,command,arg)

    def feature_callback(self, uid, parts):
        action=parts[0]
        if action=='rules': return self.rules_view(uid,int(parts[1]) if len(parts)>1 else 0)
        if action=='ruletoggle':
            if parts[1] not in ('0','1'): raise ValueError('Pilihan tidak valid.')
            self.store.toggle_rules(uid,parts[1]=='1'); return self.rules_view(uid)
        if action=='ruleview': return self.rule_view(uid,int(parts[1]))
        if action=='ruleform':
            row=self.require_owned('category_rules',uid,int(parts[1])) if int(parts[1]) else None
            self.store.start_pending(uid,'rule_form',{'rid':row['id'] if row else None,'revision':row['revision'] if row else None},self.stamp())
            return Reply('ATUR KATEGORI OTOMATIS\n\nKirim kata dan kategori, misalnya:\nbensin | Transportasi\n\n'
                         'Kata/frasa utuh dicocokkan tanpa membedakan huruf besar. Kata maksimal 40 karakter.',[[button('Batal','cancel')]])
        if action in ('ruledeleteask','favdeleteask'):
            table='category_rules' if action=='ruledeleteask' else 'favorites'
            row=self.require_owned(table,uid,int(parts[1])); label=row['keyword'] if table=='category_rules' else row['title']
            prefix='rule' if table=='category_rules' else 'fav'
            return Reply(f'HAPUS {"ATURAN" if prefix=="rule" else "FAVORIT"}?\n\n{label}\nCatatan pengeluaran yang sudah tersimpan tetap ada.',[
                [button('Ya, hapus',f"{prefix}delete:{row['id']}:{row['revision']}"),button('Batal',f"{prefix}view:{row['id']}")]])
        if action in ('ruledelete','favdelete'):
            table='category_rules' if action=='ruledelete' else 'favorites'
            if not self.store.remove_owned(table,uid,int(parts[1]),int(parts[2])): raise ValueError('Pilihan sudah berubah atau dihapus. Muat kembali daftar.')
            return self.rules_view(uid) if table=='category_rules' else self.favorites_view(uid)
        if action=='favorites': return self.favorites_view(uid,int(parts[1]) if len(parts)>1 else 0)
        if action=='favview': return self.favorite_view(uid,int(parts[1]))
        if action in ('favform','billform'): return self.start_object_form(uid,'favorite_form' if action=='favform' else 'bill_form',int(parts[1]))
        if action=='formsave': return self.save_object_form(uid,parts[1])
        if action=='favuse': return self.begin_quick(uid,'favorite',int(parts[1]))
        if action=='quickcommit': return self.commit_quick(uid,parts[1],parts[2])
        if action in ('quickfield','quickback'):
            state=self.require_pending(uid,parts[1],'quick')
            field=parts[2] if action=='quickfield' else None
            if field not in (None,'amount','spent_on'): raise ValueError('Kolom tidak tersedia.')
            state['data']['field']=field
            self.store.update_pending(uid,parts[1],state['data'],self.stamp())
            if not field: return self.quick_view(state)
            return Reply('Kirim nominal baru, misalnya 50rb.' if field=='amount' else 'Kirim tanggal bayar YYYY-MM-DD, maksimal hari ini.',[
                [button('Kembali',f"quickback:{parts[1]}"),button('Batal','cancel')]])
        if action=='catbudgets': return self.category_budget_view(uid,parts[1],int(parts[2]) if len(parts)>2 else 0)
        if action=='catbudgetview': return self.category_budget_detail(uid,int(parts[1]))
        if action=='catbudgetnew':
            month_range(parts[1]); self.store.start_pending(uid,'category_form',{'month':parts[1],'category':None},self.stamp())
            return Reply('ANGGARAN PER KATEGORI\n\nKirim nama kategori, misalnya Makanan. Maksimal 32 karakter.',[[button('Batal','cancel')]])
        if action=='catbudgetedit':
            row=self.require_owned('category_budgets',uid,int(parts[1]))
            self.store.start_pending(uid,'category_form',{'month':row['month'],'category':row['category']},self.stamp())
            return Reply('Kirim batas untuk '+row['category']+', misalnya 500rb.',[[button('Batal','cancel')]])
        if action=='catbudgetdelask':
            row=self.require_owned('category_budgets',uid,int(parts[1]))
            return Reply(f"HAPUS BATAS KATEGORI?\n\n{row['category']} — {rupiah(row['amount'])}\n{month_label(row['month'])}\n"
                         'Catatan pengeluaran tetap tersimpan.',[[button('Ya, hapus',f"catbudgetdel:{row['id']}:{row['amount']}"),
                                                               button('Batal',f"catbudgetview:{row['id']}")]])
        if action=='catbudgetdel':
            row=self.require_owned('category_budgets',uid,int(parts[1]))
            if row['amount']!=int(parts[2]): raise ValueError('Nominal sudah berubah. Konfirmasi kembali.')
            self.store.db.execute('DELETE FROM category_budgets WHERE user_id=? AND id=?',(uid,row['id']))
            return self.category_budget_view(uid,row['month'])
        if action=='catbudgetcopy': return self.copy_category_budgets(uid,parts[1])
        if action=='reportschedule': return self.report_schedule_view(uid)
        if action=='reportsetting': return self.report_setting_view(uid,parts[1])
        if action in ('reporttoggle','reportexcel'):
            setting=self.store.report_setting(uid,parts[1])
            if parts[2] not in ('0','1'): raise ValueError('Pilihan tidak valid.')
            self.store.set_report_setting(uid,setting['kind'],self.stamp(),**{
                'enabled' if action=='reporttoggle' else 'with_excel':parts[2]=='1'})
            return self.report_setting_view(uid,parts[1])
        if action=='reporttime':
            self.store.report_setting(uid,parts[1])
            self.store.start_pending(uid,'report_time',{'kind':parts[1]},self.stamp())
            return Reply('JAM REKAP OTOMATIS\n\nKirim HH:MM, misalnya 07:00. Zona waktu: '+self.now(uid).tzname()+'.',[[button('Batal','cancel')]])
        if action=='reportpreview':
            setting=self.store.report_setting(uid,parts[1]); start,end=report_window(parts[1],self.now(uid))
            return make_summary(self,uid,parts[1],start,end,bool(setting['with_excel']))
        if action=='bills': return self.bills_view(uid,int(parts[1]) if len(parts)>1 else 0)
        if action=='billview': return self.bill_view(uid,int(parts[1]),parts[2] if len(parts)>2 else None)
        if action=='billtoggle':
            row=self.require_owned('bills',uid,int(parts[1]))
            if parts[2] not in ('0','1') or not self.store.set_bill_enabled(uid,row['id'],parts[2]=='1',int(parts[3])):
                raise ValueError('Tagihan sudah berubah. Muat kembali.')
            return self.bill_view(uid,row['id'])
        if action=='billpay': return self.begin_quick(uid,'bill',int(parts[1]),parts[2])
        return super().feature_callback(uid,parts)

    def require_owned(self, table, uid, rid):
        row=self.store.owned(table,uid,rid)
        if row is None: raise ValueError('Data tidak ditemukan di akunmu.')
        return row

    def categorize_expenses(self, uid, expenses, text):
        lines=[line for line in text.splitlines() if line.strip()]
        return [replace(expense,category=self.store.automatic_category(uid,expense.note)) if '|' not in line else expense
                for expense,line in zip(expenses,lines)]

    def add_prompt(self, uid=None):
        reply=self.base_add_prompt()
        reply.buttons.insert(0,[button('⭐ Favorit','favorites:0'),button('🧾 Tagihan rutin','bills:0')])
        reply.buttons.insert(1,[button('🏷 Atur kategori otomatis','rules:0')])
        if uid is not None:
            reply.text+='\n\nKategori otomatis: '+('Aktif' if self.store.rule_settings(uid)['enabled'] else 'Nonaktif')+'. '
            reply.text+='Kategori yang ditulis setelah | selalu diutamakan.'
        return reply

    def settings_menu(self, uid):
        reply=super().settings_menu(uid)
        reply.buttons.insert(1,[button('🏷 Kategori otomatis','rules:0'),button('📬 Rekap otomatis','reportschedule')])
        reply.buttons.insert(2,[button('🧾 Tagihan rutin','bills:0')])
        return reply

    def reports_menu(self, uid):
        reply=super().reports_menu(uid)
        reply.buttons.insert(-1,[button('📬 Rekap otomatis','reportschedule')])
        return reply

    def budget_view(self, uid, month):
        reply=super().budget_view(uid,month)
        reply.buttons.insert(1,[button('🏷 Anggaran per kategori',f'catbudgets:{month}:0')])
        return reply

    def with_budget_notices(self, uid, reply, months):
        reply=super().with_budget_notices(uid,reply,months)
        for month in sorted(months):
            for category,level,used,limit in self.store.category_notices(uid,month):
                reply.text+=f'\n\n🔔 KATEGORI {category} — {month_label(month)}\nBatas {level}% tercapai.\nTerpakai {rupiah(used)} dari {rupiah(limit)}.'
        return reply

    def rules_view(self, uid, page=0):
        rows=self.store.rules(uid); page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        enabled=self.store.rule_settings(uid)['enabled']
        lines=['KATEGORI OTOMATIS','Status: '+('Aktif' if enabled else 'Nonaktif'),
               'Berlaku untuk catatan baru tanpa kategori setelah |. Aturan dengan frasa terpanjang didahulukan.','']
        buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['keyword']} → {row['category']}")
            buttons.append([button(f"{i}. {row['keyword']}",f"ruleview:{row['id']}")])
        if not rows: lines.append('Belum ada aturan. Catatan tanpa kategori masuk Lainnya.')
        buttons+=self.pages('rules',page,len(rows))
        buttons += [[button('Tambah aturan','ruleform:0'),button('Nonaktifkan' if enabled else 'Aktifkan',f'ruletoggle:{0 if enabled else 1}')]]
        return Reply('\n'.join(lines),buttons+navigation())

    def pages(self, prefix, page, count):
        buttons=[]
        if page: buttons.append(button('‹ Sebelumnya',f'{prefix}:{page-1}'))
        if (page+1)*PAGE_SIZE<count: buttons.append(button('Berikutnya ›',f'{prefix}:{page+1}'))
        return [buttons] if buttons else []

    def rule_view(self, uid, rid):
        row=self.require_owned('category_rules',uid,rid)
        return Reply(f"ATURAN KATEGORI\n\nKata/frasa: {row['keyword']}\nKategori: {row['category']}\n\nCatatan lama tetap memakai kategori yang tersimpan.",[
            [button('Edit aturan',f'ruleform:{rid}'),button('Hapus aturan',f'ruledeleteask:{rid}')],
            [button('Kembali','rules:0')]])

    def favorites_view(self, uid, page=0):
        rows=self.store.favorite_rows(uid); page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        lines=['PENGELUARAN FAVORIT','Pilih template, tinjau nominal/tanggal, lalu konfirmasi pencatatan.','']; buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['title']} — {rupiah(row['amount'])} ({row['category']})")
            buttons.append([button(f"{i}. {row['title']}",f"favview:{row['id']}")])
        if not rows: lines.append('Belum ada favorit. Tambahkan transaksi yang sering dipakai.')
        return Reply('\n'.join(lines),buttons+self.pages('favorites',page,len(rows))+[[button('➕ Tambah favorit','favform:0')]]+navigation())

    def expense_description(self, values):
        return f"{values['note']} — {rupiah(values['amount'])}\nKategori: {values['category']}"

    def favorite_view(self, uid, rid):
        row=self.require_owned('favorites',uid,rid)
        return Reply(f"FAVORIT: {row['title']}\n\n"+self.expense_description(row),[
            [button('➕ Catat dari favorit',f'favuse:{rid}')],
            [button('Edit template',f'favform:{rid}'),button('Hapus template',f'favdeleteask:{rid}')],
            [button('Kembali','favorites:0')]])

    def start_object_form(self, uid, kind, rid):
        table='favorites' if kind=='favorite_form' else 'bills'
        row=self.require_owned(table,uid,rid) if rid else None
        data={'rid':rid or None,'revision':row['revision'] if row else None,'values':dict(row) if row else {},'step':'title'}
        self.store.start_pending(uid,kind,data,self.stamp())
        return Reply(('EDIT' if rid else 'TAMBAH')+(' FAVORIT' if kind=='favorite_form' else ' TAGIHAN RUTIN')+
                     '\n\nKirim nama singkat, maksimal 40 karakter. Contoh: Bensin motor atau Internet rumah.'+
                     (f"\nNama saat ini: {row['title']}" if row else ''),[[button('Batal','cancel')]])

    def object_form_view(self, state):
        values=state['data']['values']; is_bill=state['kind']=='bill_form'
        text=('SIMPAN TAGIHAN RUTIN?' if is_bill else 'SIMPAN FAVORIT?')+f"\n\nNama: {values['title']}\n"+self.expense_description(values)
        if is_bill:
            text+=f"\nJadwal: tanggal {values['day_of_month']} setiap bulan, pukul {values['at_time']} {self.now(state['user_id']).tzname()}\nMulai periode: {values['start_month']}"
            text+='\nTanggal 29–31 mengikuti hari terakhir jika bulan lebih pendek. Pengeluaran hanya dicatat setelah konfirmasi pembayaran.'
        return Reply(text,[[button('Simpan',f"formsave:{state['token']}"),button('Batal','cancel')]])

    def save_object_form(self, uid, token):
        state=self.store.pending(uid)
        if not state or state['kind'] not in ('favorite_form','bill_form'): raise ValueError('Draf sudah tidak aktif.')
        state=self.require_pending(uid,token,state['kind']); data=state['data']
        if data['step']!='confirm': raise ValueError('Selesaikan isian terlebih dahulu.')
        if state['kind']=='favorite_form':
            rid=self.store.save_favorite(uid,data['values'],data['rid'],data['revision'])
            reply=self.favorite_view(uid,rid)
        else:
            rid=self.store.save_bill(uid,data['values'],data['rid'],data['revision'])
            reply=self.bill_view(uid,rid)
        self.store.cancel_pending(uid)
        reply.text='Pengaturan disimpan.\n\n'+reply.text
        return reply

    def begin_quick(self, uid, kind, rid, period=None):
        row=self.require_owned('favorites' if kind=='favorite' else 'bills',uid,rid)
        if kind=='bill':
            month_range(period)
            if period<row['start_month']: raise ValueError('Periode lebih awal dari awal tagihan.')
            due=bill_due(row,period,self.now(uid).tzinfo)
            cycle=self.store.ensure_cycle(uid,row,period,due.date())
            if cycle['expense_id'] is not None: return self.bill_view(uid,rid,period)
        values={key:row[key] for key in ('amount','note','category')}; values['spent_on']=self.now(uid).date().isoformat()
        state=self.store.start_pending(uid,'quick',{'kind':kind,'rid':rid,'revision':row['revision'],'period':period,
                                                  'title':row['title'],'values':values,'field':None},self.stamp())
        return self.quick_view(state)

    def quick_view(self, state):
        data=state['data']; token=state['token']
        data['confirmation']=secrets.token_hex(4)
        self.store.update_pending(state['user_id'],token,data,self.stamp())
        text='CATAT PENGELUARAN INI?\n\n'+data['title']+'\n'+self.expense_description(data['values'])
        text+='\nTanggal pengeluaran: '+day_label(read_day(data['values']['spent_on']))
        if data['kind']=='bill': text+='\nPeriode tagihan: '+data['period']
        text+='\n\nBelum dicatat. Perubahan nominal di sini hanya berlaku untuk pencatatan ini.'
        return Reply(text,[[button('Ya, catat pengeluaran',f"quickcommit:{token}:{data['confirmation']}")],
                           [button('Ubah nominal',f'quickfield:{token}:amount'),button('Ubah tanggal',f'quickfield:{token}:spent_on')],
                           [button('Batal','cancel')]])

    def commit_quick(self, uid, token, confirmation):
        state=self.require_pending(uid,token,'quick'); data=state['data']
        if data.get('confirmation')!=confirmation: raise ValueError('Tinjauan sudah berubah. Gunakan tombol pada tinjauan terbaru.')
        if data['field']: raise ValueError('Selesaikan perubahan nilai atau kembali ke tinjauan.')
        if read_day(data['values']['spent_on'])>self.now(uid).date(): raise ValueError('Tanggal pengeluaran tidak boleh di masa depan.')
        row=self.require_owned('favorites' if data['kind']=='favorite' else 'bills',uid,data['rid'])
        if row['revision']!=data['revision']: raise ValueError('Template/tagihan sudah berubah. Buka kembali dan konfirmasi ulang.')
        if data['kind']=='favorite': expense,added=self.store.add_confirmed(uid,data['values'],'fav:'+token,self.clock().isoformat())
        else: expense,added=self.store.pay_bill(uid,row,data['period'],data['values'],self.clock().isoformat())
        self.store.cancel_pending(uid)
        if not added:
            return Reply('Pembayaran ini sudah pernah dicatat. Jika catatannya dihapus, pulihkan melalui Riwayat.',[
                [button('Lihat tagihan',f"billview:{data['rid']}:{data['period']}")]]+navigation())
        reply=Reply('Tercatat 1 pengeluaran\n\n1. '+self.expense_description(expense)+
                    '\nTanggal: '+day_label(read_day(expense['spent_on'])),[
                        [button('✏ Edit catatan',f"editopen:{expense['id']}"),button('📅 Hari ini','today')]]+navigation())
        return self.with_budget_notices(uid,reply,{expense['spent_on'][:7]})

    def category_budget_view(self, uid, month, page=0):
        start,end=month_range(month); rows=self.store.category_limits(uid,month)
        page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        totals={}
        for r in self.store.rows(uid,start,end): totals[r['category']]=totals.get(r['category'],0)+r['amount']
        lines=['ANGGARAN PER KATEGORI',month_label(month),'']; buttons=[]
        for i,r in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            used=totals.get(r['category'],0)
            lines.append(f"{i}. {r['category']}: {rupiah(used)} / {rupiah(r['amount'])}")
            buttons.append([button(f"{i}. {r['category']}",f"catbudgetview:{r['id']}")])
        if not rows: lines.append('Belum ada batas kategori pada bulan ini.')
        lines += ['',f"Jumlah batas kategori: {rupiah(sum(r['amount'] for r in rows))}",
                  'Batas kategori dan anggaran total diperiksa terpisah. Kategori lain tidak dibatasi oleh menu ini.']
        buttons+=self.pages('catbudgets:'+month,page,len(rows))
        previous=(start-timedelta(days=1)).strftime('%Y-%m')
        buttons += [[button('Tambah kategori',f'catbudgetnew:{month}')],
                    [button('Salin batas bulan lalu',f'catbudgetcopy:{month}')],
                    [button('‹ Bulan sebelumnya',f'catbudgets:{previous}:0'),button('Bulan berikutnya ›',f'catbudgets:{end:%Y-%m}:0')],
                    [button('Anggaran total',f'budget:{month}')]]
        return Reply('\n'.join(lines),buttons+navigation())

    def category_budget_detail(self, uid, rid):
        row=self.require_owned('category_budgets',uid,rid); start,end=month_range(row['month'])
        used=sum(r['amount'] for r in self.store.rows(uid,start,end) if r['category']==row['category'])
        remaining=row['amount']-used
        return Reply(f"ANGGARAN {row['category']}\n{month_label(row['month'])}\n\nBatas: {rupiah(row['amount'])}\n"
                     f"Terpakai: {rupiah(used)} ({used*100/row['amount']:.1f}%)\n"+
                     (f'Sisa: {rupiah(remaining)}' if remaining>=0 else f'Melebihi: {rupiah(-remaining)}')+
                     '\n\nPemberitahuan pada 80% dan 100%. Batas ini berlaku untuk bulan yang dipilih.',[
                         [button('Ubah batas',f'catbudgetedit:{rid}'),button('Hapus batas',f'catbudgetdelask:{rid}')],
                         [button('Kembali',f"catbudgets:{row['month']}:0")]])

    def copy_category_budgets(self, uid, month):
        start,_=month_range(month); previous=(start-timedelta(days=1)).strftime('%Y-%m')
        rows=self.store.category_limits(uid,previous); existing={r['category'] for r in self.store.category_limits(uid,month)}
        missing=[r for r in rows if r['category'] not in existing]
        if len(existing)+len(missing)>50: raise ValueError('Hasil salinan melebihi 50 kategori; tambahkan kategori yang diperlukan saja.')
        for row in missing: self.store.set_category_limit(uid,month,row['category'],row['amount'])
        reply=self.category_budget_view(uid,month)
        reply.text=f'{len(missing)} batas kategori disalin. Nominal yang sudah ada tetap dipertahankan.\n\n'+reply.text
        return self.with_budget_notices(uid,reply,{month})

    def report_schedule_view(self, uid):
        lines=['REKAP OTOMATIS','Aktifkan periode yang ingin diterima. Jam mengikuti zona '+self.now(uid).tzname()+'.','']; buttons=[]
        for kind,label in REPORT_NAMES.items():
            row=self.store.report_setting(uid,kind)
            schedule='Senin' if kind=='weekly' else 'Tanggal 1'
            lines.append(f"{label}: {'Aktif' if row['enabled'] else 'Nonaktif'} — {schedule}, {row['at_time']}")
            buttons.append([button('Atur '+label.lower(),f'reportsetting:{kind}')])
        lines+=['','Mingguan merangkum Senin–Minggu sebelumnya. Bulanan merangkum bulan sebelumnya. Lampiran Excel opsional.']
        return Reply('\n'.join(lines),buttons+navigation())

    def report_setting_view(self, uid, kind):
        row=self.store.report_setting(uid,kind); now=self.now(uid)
        text=f"REKAP {REPORT_NAMES[kind].upper()}\nStatus: {'Aktif' if row['enabled'] else 'Nonaktif'}\n"
        text+=('Setiap Senin' if kind=='weekly' else 'Setiap tanggal 1')+f", pukul {row['at_time']} {now.tzname()}\n"
        text+='Lampiran Excel: '+('Ya' if row['with_excel'] else 'Tidak')
        if row['enabled']:
            next_due=next_report_time(kind,row['at_time'],now)
            text+=f'\nJadwal berikutnya: {day_label(next_due.date())}, {next_due:%H:%M}'
        text+='\n\nBot harus tetap hidup. Jika sempat offline, hanya periode terjadwal terbaru yang menyusul.'
        return Reply(text,[[button('Nonaktifkan' if row['enabled'] else 'Aktifkan',f"reporttoggle:{kind}:{0 if row['enabled'] else 1}"),
                            button('Ubah jam',f'reporttime:{kind}')],
                          [button('Matikan Excel' if row['with_excel'] else 'Sertakan Excel',f"reportexcel:{kind}:{0 if row['with_excel'] else 1}")],
                          [button('Lihat contoh rekap terakhir',f'reportpreview:{kind}')],
                          [button('Kembali','reportschedule')]])

    def bills_view(self, uid, page=0):
        rows=self.store.bill_rows(uid); page=max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        lines=['TAGIHAN RUTIN','Pengingat bulanan. Pembayaran masuk pengeluaran setelah kamu konfirmasi.','']; buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['title']} — {rupiah(row['amount'])}\n   Tanggal {row['day_of_month']}, {row['at_time']} · {'Aktif' if row['enabled'] else 'Nonaktif'}")
            buttons.append([button(f"{i}. {row['title']}",f"billview:{row['id']}")])
        if not rows: lines.append('Belum ada tagihan. Tambahkan kos, internet, atau langgananmu.')
        return Reply('\n'.join(lines),buttons+self.pages('bills',page,len(rows))+[[button('Tambah tagihan','billform:0')]]+navigation())

    def bill_view(self, uid, rid, period=None):
        bill=self.require_owned('bills',uid,rid)
        period=period or max(self.now(uid).strftime('%Y-%m'),bill['start_month'])
        start,end=month_range(period)
        if period<bill['start_month']: raise ValueError('Periode lebih awal dari awal tagihan.')
        due=bill_due(bill,period,self.now(uid).tzinfo)
        cycle=self.store.bill_cycle(uid,rid,period)
        expense=self.store.get(uid,cycle['expense_id']) if cycle and cycle['expense_id'] else None
        text=f"TAGIHAN {bill['title']}\nPeriode: {month_label(period)}\n"+self.expense_description(bill)
        text+='\nJatuh tempo: '+day_label(read_day(cycle['due_on']) if cycle else due.date())
        text+=f"\nPengingat: {'Aktif' if bill['enabled'] else 'Nonaktif'}, {bill['at_time']} {self.now(uid).tzname()}\n"
        buttons=[]
        if expense:
            if expense['deleted']:
                text+='\nPembayaran pernah dicatat, tetapi catatannya dihapus. Pulihkan untuk memasukkannya kembali ke laporan.'
                buttons.append([button('Pulihkan catatan pembayaran',f"restore:{expense['id']}:0")])
            else:
                text+=f"\nSudah dicatat: {rupiah(expense['amount'])}, {day_label(read_day(expense['spent_on']))}."
                buttons.append([button('Edit catatan pembayaran',f"editopen:{expense['id']}")])
        else:
            text+='\nPembayaran belum dicatat di bot.'
            buttons.append([button('Sudah dibayar → Catat',f'billpay:{rid}:{period}')])
        pages=[]
        previous=(start-timedelta(days=1)).strftime('%Y-%m')
        if previous>=bill['start_month']: pages.append(button('‹ Periode sebelumnya',f'billview:{rid}:{previous}'))
        pages.append(button('Periode berikutnya ›',f'billview:{rid}:{end:%Y-%m}'))
        buttons += [pages,[button('Edit tagihan',f'billform:{rid}'),
                            button('Nonaktifkan' if bill['enabled'] else 'Aktifkan',f"billtoggle:{rid}:{0 if bill['enabled'] else 1}:{bill['revision']}")],
                    [button('Kembali ke tagihan','bills:0')]]
        return Reply(text,buttons+navigation())

    def pending_input(self, uid, text):
        state=self.store.pending(uid)
        kinds=('rule_form','favorite_form','bill_form','category_form','report_time','quick')
        if not state or state['kind'] not in kinds or state['expires_at']<=self.stamp():
            return super().pending_input(uid,text)
        data=state['data']; token=state['token']
        try:
            if state['kind']=='rule_form':
                fields=text.split('|')
                if len(fields)!=2: raise ValueError('Kirim kata | kategori, misalnya bensin | Transportasi.')
                word=clean_label(fields[0],40,'Kata/frasa'); category=clean_label(fields[1],32,'Kategori').capitalize()
                self.store.save_rule(uid,word,category,data['rid'],data['revision'])
                self.store.cancel_pending(uid)
                return self.rules_view(uid)
            if state['kind'] in ('favorite_form','bill_form'):
                step=data['step']; values=data['values']
                if step=='confirm': return self.object_form_view(state)
                if step=='title':
                    values['title']=clean_label(text,40,'Nama'); data['step']='expense'
                    prompt='Kirim nominal dan keterangan, misalnya:\n50000 bensin | Transportasi\n\nSatu baris tanpa tanggal.'
                elif step=='expense':
                    if len(text.splitlines())!=1 or re.match(r'^\d{4}-\d{2}-\d{2}',text): raise ValueError('Kirim satu pengeluaran tanpa tanggal.')
                    expense=parse_expense(text,self.now(uid).date())
                    fields=text.split('|')
                    category=expense.category if len(fields)>1 and fields[1].strip() else self.store.automatic_category(uid,expense.note)
                    wallet_id=self.store.resolve_wallet(uid,expense.wallet) if expense.wallet is not None else None
                    values.update(amount=expense.amount,note=expense.note,category=category,wallet_id=wallet_id)
                    data['step']='day' if state['kind']=='bill_form' else 'confirm'
                    prompt='Kirim tanggal tagihan setiap bulan, berupa angka 1–31. Tanggal 29–31 mengikuti akhir bulan yang lebih pendek.'
                elif step=='day':
                    if not re.fullmatch(r'[0-9]{1,2}',text) or not 1<=int(text)<=31: raise ValueError('Tanggal bulanan harus angka 1–31.')
                    values['day_of_month']=int(text); data['step']='time'
                    prompt='Kirim jam pengingat HH:MM, misalnya 09:00. Zona waktu: '+self.now(uid).tzname()+'.'
                elif step=='time':
                    values['at_time']=parse_time(text)
                    if not data['rid']: values['start_month']=first_bill_month(values,self.now(uid))
                    data['step']='confirm'; prompt=''
                else: raise ValueError('Draf tidak dikenal. Buka ulang fitur.')
                state=self.store.update_pending(uid,token,data,self.stamp())
                return self.object_form_view(state) if data['step']=='confirm' else Reply(prompt,[[button('Batal','cancel')]])
            if state['kind']=='category_form':
                if data['category'] is None:
                    data['category']=clean_label(text,32,'Kategori').capitalize()
                    self.store.update_pending(uid,token,data,self.stamp())
                    return Reply('Kirim batas '+data['category']+', misalnya 500rb.',[[button('Batal','cancel')]])
                amount=parse_amount(re.sub(r'^rp\s+','Rp',text,flags=re.I))
                self.store.set_category_limit(uid,data['month'],data['category'],amount)
                self.store.cancel_pending(uid)
                return self.with_budget_notices(uid,self.category_budget_view(uid,data['month']),{data['month']})
            if state['kind']=='report_time':
                self.store.set_report_setting(uid,data['kind'],self.stamp(),at_time=parse_time(text))
                self.store.cancel_pending(uid)
                return self.report_setting_view(uid,data['kind'])
            if state['kind']=='quick':
                field=data['field']
                if field is None: return self.quick_view(state)
                if field=='amount': data['values']['amount']=parse_amount(re.sub(r'^rp\s+','Rp',text,flags=re.I))
                else:
                    day=read_day(text)
                    if day>self.now(uid).date(): raise ValueError('Tanggal pengeluaran tidak boleh di masa depan.')
                    data['values']['spent_on']=day.isoformat()
                data['field']=None
                return self.quick_view(self.store.update_pending(uid,token,data,self.stamp()))
        except ValueError as exc:
            return Reply(str(exc)+'\n\nKirim ulang nilai yang benar atau tekan Batal.',[[button('Batal','cancel')]])
