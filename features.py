"""Edit, anggaran, pencarian, pengingat, dan perbandingan yang dipakai bersama oleh versi 2.2."""
from datetime import datetime, timedelta
import hashlib
import re

from core import MONTHS, day_label, month_range, parse_amount, read_day, rupiah
from ui import Reply, button, navigation

PAGE_SIZE = 6
FIELD_NAMES = {'amount':'Nominal','note':'Keterangan','category':'Kategori','spent_on':'Tanggal'}


def month_label(month):
    start,_ = month_range(month)
    return f'{MONTHS[start.month]} {start.year}'


def parse_time(value):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):
        raise ValueError('Jam harus HH:MM dalam format 24 jam, misalnya 21:00 atau 07:30.')
    return value


def next_reminder_time(at_time, now):
    hour,minute = map(int,parse_time(at_time).split(':'))
    target = now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if target<=now:
        target += timedelta(days=1)
    return int(target.timestamp())


def category_key(category):
    return hashlib.sha256(category.encode('utf-8')).hexdigest()[:16]


class ExtraFeatures:
    def stamp(self):
        return int(self.clock().timestamp())

    def feature_command(self, uid, command, arg):
        month = self.now(uid).strftime('%Y-%m')
        if command=='/edit':
            return self.edit_list(uid)
        if command=='/batal':
            return Reply('Input dibatalkan. Kamu bisa memilih menu atau mencatat pengeluaran lagi.')
        if command=='/anggaran':
            if not arg:
                return self.budget_view(uid,month)
            pieces = arg.split(maxsplit=1)
            if re.fullmatch(r'[0-9]{4}-[0-9]{2}',pieces[0]):
                month_range(pieces[0])
                month = pieces[0]
                if len(pieces)==1:
                    return self.budget_view(uid,month)
                arg = pieces[1]
            return self.save_budget(uid,month,arg)
        if command=='/cari':
            if arg:
                if len(arg)>160:
                    raise ValueError('Kata pencarian maksimal 160 karakter.')
                self.store.set_filters(uid,{'keyword':arg,'category':None,'start':None,'end':None})
            return self.search_view(uid)
        if command=='/pengingat':
            if arg:
                if arg.lower()=='off':
                    self.configure_reminder(uid,enabled=False)
                else:
                    self.configure_reminder(uid,at_time=parse_time(arg),enabled=True)
            return self.reminder_view(uid)
        if command=='/banding':
            return self.compare_months(uid,arg or month)
        return None

    def feature_callback(self, uid, parts):
        action = parts[0]
        if action=='cancel':
            self.store.cancel_pending(uid)
            return Reply('Input dibatalkan. Tidak ada draf pengeluaran yang disimpan.')
        if action=='editlist': return self.edit_list(uid,int(parts[1]))
        if action=='editopen': return self.open_edit(uid,int(parts[1]))
        if action=='editfield': return self.edit_field_prompt(uid,parts[1],parts[2])
        if action=='editback':
            state = self.require_pending(uid,parts[1],'edit')
            state['data']['field'] = None
            state = self.store.update_pending(uid,parts[1],state['data'],self.stamp())
            return self.edit_view(state)
        if action=='editsave': return self.commit_edit(uid,parts[1])
        if action=='budget': return self.budget_view(uid,parts[1])
        if action=='budgetset':
            month_range(parts[1])
            self.store.start_pending(uid,'budget',{'month':parts[1]},self.stamp())
            return Reply(f'ATUR ANGGARAN {month_label(parts[1])}\n\nKirim nominal, misalnya 1500000 atau 1,5jt.\n'
                         'Anggaran berlaku untuk bulan ini saja.',[[button('Batal','cancel')]])
        if action=='budgetcopy':
            start,_ = month_range(parts[1])
            previous = (start-timedelta(days=1)).strftime('%Y-%m')
            budget = self.store.budget(uid,previous)
            if budget is None: return Reply('Belum ada anggaran bulan sebelumnya.')
            return self.save_budget(uid,parts[1],str(budget['amount']))
        if action=='search': return self.search_view(uid,int(parts[1]))
        if action=='findreset':
            self.store.set_filters(uid,{'keyword':'','category':None,'start':None,'end':None})
            return self.search_view(uid)
        if action=='findinput':
            if parts[1] not in ('keyword','dates'): raise ValueError('Filter tidak dikenal.')
            self.store.start_pending(uid,'search',{'field':parts[1]},self.stamp())
            prompt = ('Kirim kata yang dicari dalam keterangan, misalnya bensin.\nKirim - untuk mengosongkan kata.'
                      if parts[1]=='keyword' else
                      'Kirim tanggal awal dan akhir, misalnya:\n2026-09-01 2026-09-21\n\n'
                      'Atau satu bulan: 2026-09. Kedua tanggal termasuk dalam pencarian.')
            return Reply('ATUR PENCARIAN\n\n'+prompt,[[button('Batal','cancel')]])
        if action=='findcats': return self.search_categories(uid,int(parts[1]))
        if action=='findcat':
            values = self.store.filters(uid)
            if parts[1]=='all': values['category'] = None
            else:
                matches = [c for c in self.store.categories(uid) if category_key(c)==parts[1]]
                if not matches: raise ValueError('Kategori tidak tersedia. Buka pilihan kategori lagi.')
                values['category'] = matches[0]
            self.store.set_filters(uid,values)
            return self.search_view(uid)
        if action=='finddates':
            values = self.store.filters(uid)
            if parts[1]=='all': values.update(start=None,end=None)
            elif parts[1]=='month':
                start,end = month_range(self.now(uid).strftime('%Y-%m'))
                values.update(start=start.isoformat(),end=(end-timedelta(days=1)).isoformat())
            else: raise ValueError('Periode tidak dikenal.')
            self.store.set_filters(uid,values)
            return self.search_view(uid)
        if action=='reminder': return self.reminder_view(uid)
        if action=='reminderenable':
            if parts[1] not in ('0','1'): raise ValueError('Pilihan tidak valid.')
            self.configure_reminder(uid,enabled=parts[1]=='1')
            return self.reminder_view(uid)
        if action=='remindertime':
            self.store.start_pending(uid,'reminder',{},self.stamp())
            return Reply('JAM PENGINGAT\n\nKirim jam dalam format 24 jam, misalnya 21:00.\n'
                         f'Zona waktu: {self.now(uid).tzname()}. Menyimpan jam akan mengaktifkan pengingat.',
                         [[button('Batal','cancel')]])
        if action=='compare': return self.compare_months(uid,parts[1],parts[2] if len(parts)>2 else 'equal')
        return None

    def require_pending(self, uid, token, kind):
        state = self.store.pending(uid)
        if not state or state['token']!=token or state['kind']!=kind or state['expires_at']<=self.stamp():
            raise ValueError('Tombol ini sudah tidak aktif. Buka menu fitur kembali.')
        return state

    def pending_input(self, uid, text):
        state = self.store.pending(uid)
        if not state: return None
        if state['expires_at']<=self.stamp():
            self.store.cancel_pending(uid)
            return Reply('Waktu pengisian habis setelah 30 menit. Pesan ini belum disimpan. Buka fitur kembali.')
        try:
            data = state['data']
            if state['kind']=='edit':
                field = data.get('field')
                if not field:
                    return Reply('Draf edit masih terbuka. Pilih kolom yang ingin diubah, simpan, atau batalkan.',
                                 self.edit_view(state).buttons)
                if field=='amount': value = parse_amount(re.sub(r'^rp\s+','Rp',text,flags=re.I))
                elif field=='spent_on':
                    value = read_day(text)
                    if value>self.now(uid).date(): raise ValueError('Tanggal pengeluaran tidak boleh di masa depan.')
                    value = value.isoformat()
                else:
                    value = ' '.join(text.split())
                    limit = 160 if field=='note' else 32
                    if not 1<=len(value)<=limit:
                        raise ValueError(f'{FIELD_NAMES[field]} wajib diisi, maksimal {limit} karakter.')
                    if field=='category': value = value.capitalize()
                data['values'][field] = value
                data['field'] = None
                return self.edit_view(self.store.update_pending(uid,state['token'],data,self.stamp()))
            if state['kind']=='budget':
                reply = self.save_budget(uid,data['month'],text)
            elif state['kind']=='search':
                values = self.store.filters(uid)
                if data['field']=='keyword':
                    if len(text)>160: raise ValueError('Kata pencarian maksimal 160 karakter.')
                    values['keyword'] = '' if text=='-' else text
                else:
                    if re.fullmatch(r'[0-9]{4}-[0-9]{2}',text):
                        start,end = month_range(text)
                        end -= timedelta(days=1)
                    else:
                        parts = text.split()
                        if len(parts)!=2: raise ValueError('Kirim YYYY-MM-DD YYYY-MM-DD, atau YYYY-MM.')
                        start,end = map(read_day,parts)
                    if start>end: raise ValueError('Tanggal awal tidak boleh sesudah tanggal akhir.')
                    values.update(start=start.isoformat(),end=end.isoformat())
                self.store.set_filters(uid,values)
                reply = self.search_view(uid)
            elif state['kind']=='reminder':
                self.configure_reminder(uid,at_time=parse_time(text),enabled=True)
                reply = self.reminder_view(uid)
            else: raise ValueError('Input tidak dikenal. Batalkan dan buka menu kembali.')
            self.store.cancel_pending(uid)
            return reply
        except ValueError as exc:
            return Reply(str(exc)+'\n\nKirim ulang nilai yang benar atau tekan Batal.',[[button('Batal','cancel')]])

    def edit_list(self, uid, page=0):
        rows = self.store.history(uid)
        page = max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        lines = ['EDIT PENGELUARAN','Pilih catatan yang ingin diubah.','']
        buttons = []
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['note']} — {rupiah(row['amount'])}\n   {row['spent_on']} ({row['category']})")
            buttons.append([button(f"{i}. {row['note'][:30]}",f"editopen:{row['id']}")])
        if not rows: lines.append('Belum ada pengeluaran yang dapat diedit.')
        pages = []
        if page: pages.append(button('‹ Sebelumnya',f'editlist:{page-1}'))
        if (page+1)*PAGE_SIZE<len(rows): pages.append(button('Berikutnya ›',f'editlist:{page+1}'))
        if pages: buttons.append(pages)
        return Reply('\n'.join(lines),buttons+[[button('🔎 Cari catatan','search:0')]]+navigation())

    def open_edit(self, uid, record_id):
        row = self.store.get(uid,record_id)
        if row is None or row['deleted']: return Reply('Pengeluaran tidak ditemukan atau sudah dihapus.')
        values = {key:row[key] for key in FIELD_NAMES}
        state = self.store.start_pending(uid,'edit',{'id':record_id,'revision':row['revision'],
                  'original':values,'values':dict(values),'field':None},self.stamp())
        return self.edit_view(state)

    def edit_view(self, state):
        data,token = state['data'],state['token']
        values = data['values']
        lines = ['EDIT PENGELUARAN',f"Keterangan: {values['note']}",f"Nominal: {rupiah(values['amount'])}",
                 f"Kategori: {values['category']}",f"Tanggal: {day_label(read_day(values['spent_on']))}",'']
        changed = [key for key in FIELD_NAMES if data['original'][key]!=values[key]]
        if changed:
            lines.append('PERUBAHAN BELUM DISIMPAN')
            for key in changed:
                before,after = data['original'][key],values[key]
                if key=='amount': before,after = rupiah(before),rupiah(after)
                lines.append(f'{FIELD_NAMES[key]}: {before} → {after}')
        else: lines.append('Pilih bagian yang ingin diubah.')
        buttons = [[button('Nominal',f'editfield:{token}:amount'),button('Keterangan',f'editfield:{token}:note')],
                   [button('Kategori',f'editfield:{token}:category'),button('Tanggal',f'editfield:{token}:spent_on')]]
        if changed: buttons.append([button('✅ Simpan perubahan',f'editsave:{token}')])
        buttons.append([button('🕘 Riwayat edit catatan ini',f"changes:{data['id']}:0")])
        buttons.append([button('Batal','cancel')])
        return Reply('\n'.join(lines),buttons)

    def edit_field_prompt(self, uid, token, field):
        if field not in FIELD_NAMES: raise ValueError('Kolom tidak dikenal.')
        state = self.require_pending(uid,token,'edit')
        data = state['data']; data['field'] = field
        self.store.update_pending(uid,token,data,self.stamp())
        examples = {'amount':'25000 atau 25rb','note':'makan siang','category':'Makanan','spent_on':'2026-09-21 (YYYY-MM-DD)'}
        return Reply(f'UBAH {FIELD_NAMES[field].upper()}\n\nKirim nilai baru, misalnya {examples[field]}.\n'
                     'Perubahan akan ditinjau sebelum disimpan.',
                     [[button('Kembali ke draf',f'editback:{token}'),button('Batal','cancel')]])

    def commit_edit(self, uid, token):
        state = self.require_pending(uid,token,'edit')
        data = state['data']
        if read_day(data['values']['spent_on'])>self.now(uid).date():
            raise ValueError('Tanggal pengeluaran tidak boleh di masa depan.')
        if not self.store.edit_expense(uid,data['id'],data['revision'],data['values'],self.clock().isoformat()):
            self.store.cancel_pending(uid)
            return Reply('Catatan sudah berubah atau dihapus. Buka daftar Edit kembali untuk memuat data terbaru.')
        self.store.cancel_pending(uid)
        values = data['values']
        reply = Reply(f"Perubahan disimpan.\n{values['note']} — {rupiah(values['amount'])}\n"
                      f"Kategori: {values['category']}\nTanggal: {day_label(read_day(values['spent_on']))}\n\n"
                      'Laporan dan ekspor Excel berikutnya memakai data terbaru.',
                      [[button('Edit catatan lain','editlist:0'),button('Lihat tanggal ini',f"daily:{values['spent_on']}:0")]]+navigation())
        changes = self.store.changes(uid,data['id'])
        if changes and self.store.can_undo(uid,changes[0]):
            reply.buttons.insert(0,[button('↩ Urungkan edit',f"undoask:{changes[0]['id']}"),
                                    button('🕘 Riwayat edit',f"changes:{data['id']}:0")])
        return self.with_budget_notices(uid,reply,{data['original']['spent_on'][:7],values['spent_on'][:7]})

    def budget_text(self, uid, month):
        budget = self.store.budget(uid,month)
        if budget is None: return 'Anggaran belum diatur.'
        start,end = month_range(month)
        used = sum(row['amount'] for row in self.store.rows(uid,start,end))
        remaining = budget['amount']-used
        percent = f"{used*100/budget['amount']:.1f}".replace('.',',')
        balance = f'Sisa anggaran: {rupiah(remaining)}' if remaining>=0 else f'Melebihi anggaran: {rupiah(-remaining)}'
        return f"Anggaran: {rupiah(budget['amount'])}\nTerpakai: {rupiah(used)} ({percent}%)\n{balance}"

    def budget_view(self, uid, month):
        start,end = month_range(month)
        previous = (start-timedelta(days=1)).strftime('%Y-%m')
        buttons = [[button('✏ Atur nominal',f'budgetset:{month}')]]
        if self.store.budget(uid,previous) and not self.store.budget(uid,month):
            buttons.append([button('Salin anggaran bulan lalu',f'budgetcopy:{month}')])
        buttons += [[button('‹ Bulan sebelumnya',f'budget:{previous}'),button('Bulan berikutnya ›',f'budget:{end:%Y-%m}')]]
        return Reply(f'ANGGARAN {month_label(month)}\n\n'+self.budget_text(uid,month)+
                     '\n\nPemberitahuan pada 80% dan 100%. Anggaran diatur per bulan.',buttons+navigation())

    def save_budget(self, uid, month, text):
        month_range(month)
        amount = parse_amount(re.sub(r'^rp\s+','Rp',text.strip(),flags=re.I))
        self.store.set_budget(uid,month,amount)
        return self.with_budget_notices(uid,self.budget_view(uid,month),{month})

    def with_budget_notices(self, uid, reply, months):
        for month in sorted(months):
            result = self.store.budget_notice(uid,month)
            if result:
                level,used,limit = result
                reply.text += (f'\n\n🔔 ANGGARAN {month_label(month)}\nBatas {level}% tercapai.\n'
                               f'Terpakai {rupiah(used)} dari {rupiah(limit)}.')
                if used>limit: reply.text += f'\nMelebihi anggaran: {rupiah(used-limit)}.'
        return reply

    def search_view(self, uid, page=0):
        values = self.store.filters(uid)
        rows = self.store.search_expenses(uid,values)
        page = max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        period = f"{values['start']} s.d. {values['end']}" if values['start'] else 'Semua tanggal'
        lines = ['CARI PENGELUARAN',f"Kata: {values['keyword'] or 'Semua'}",f"Kategori: {values['category'] or 'Semua'}",
                 f'Periode: {period}',f'Jumlah: {len(rows)} catatan',f"Total hasil: {rupiah(sum(r['amount'] for r in rows))}",'']
        buttons = []
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['note']} — {rupiah(row['amount'])}\n   {row['spent_on']} ({row['category']})")
            buttons.append([button(f"✏ {i}. {row['note'][:25]}",f"editopen:{row['id']}")])
        if not rows: lines.append('Tidak ada pengeluaran yang sesuai.')
        pages = []
        if page: pages.append(button('‹ Sebelumnya',f'search:{page-1}'))
        if (page+1)*PAGE_SIZE<len(rows): pages.append(button('Berikutnya ›',f'search:{page+1}'))
        if pages: buttons.append(pages)
        buttons += [[button('Kata pencarian','findinput:keyword'),button('Kategori','findcats:0')],
                    [button('Rentang tanggal','findinput:dates'),button('Bulan ini','finddates:month')],
                    [button('Semua tanggal','finddates:all'),button('Reset pencarian','findreset')]]
        if rows: buttons.append([button('☑ Pilih beberapa hasil','bulkstart:search')])
        return Reply('\n'.join(lines),buttons+navigation())

    def search_categories(self, uid, page=0):
        categories = self.store.categories(uid)
        page = max(0,min(page,max(0,(len(categories)-1)//PAGE_SIZE)))
        buttons = [[button(c,f'findcat:{category_key(c)}')] for c in categories[page*PAGE_SIZE:(page+1)*PAGE_SIZE]]
        pages = []
        if page: pages.append(button('‹ Sebelumnya',f'findcats:{page-1}'))
        if (page+1)*PAGE_SIZE<len(categories): pages.append(button('Berikutnya ›',f'findcats:{page+1}'))
        if pages: buttons.append(pages)
        return Reply('FILTER KATEGORI\nPilih kategori untuk digabung dengan kata dan tanggal pencarian.',
                     buttons+[[button('Semua kategori','findcat:all'),button('Kembali','search:0')]])

    def configure_reminder(self, uid, at_time=None, enabled=None):
        current = self.store.reminder(uid)
        at_time = current['at_time'] if at_time is None else parse_time(at_time)
        enabled = bool(current['enabled']) if enabled is None else enabled
        self.store.set_reminder(uid,at_time,enabled,next_reminder_time(at_time,self.now(uid)) if enabled else 0)

    def reminder_view(self, uid):
        data = self.store.reminder(uid)
        now = self.now(uid)
        text = (f"PENGINGAT HARIAN\nStatus: {'Aktif' if data['enabled'] else 'Nonaktif'}\n"
                f"Jam: {data['at_time']} {now.tzname()}\n\nPengingat untuk memeriksa dan mencatat pengeluaran setiap hari.")
        if data['enabled']:
            due = datetime.fromtimestamp(data['next_due'],now.tzinfo)
            text += f'\nBerikutnya: {day_label(due.date())}, {due:%H:%M}.'
        text += '\n\nBot harus tetap berjalan agar pengingat terkirim.'
        toggle = button('🔕 Nonaktifkan','reminderenable:0') if data['enabled'] else button('🔔 Aktifkan','reminderenable:1')
        return Reply(text,[[toggle,button('Ubah jam','remindertime')]]+navigation())

    def compare_months(self, uid, month, mode='equal'):
        if mode not in ('equal','full'): raise ValueError('Periode perbandingan tidak valid.')
        start,end = month_range(month)
        previous_start,_ = month_range((start-timedelta(days=1)).strftime('%Y-%m'))
        previous_end = start
        current_end = end
        now = self.now(uid)
        current = month==now.strftime('%Y-%m')
        if current and mode=='equal':
            current_end = now.date()+timedelta(days=1)
            previous_end = min(start,previous_start+timedelta(days=now.day))
        rows = self.store.rows(uid,start,current_end)
        old_rows = self.store.rows(uid,previous_start,previous_end)
        used,old = sum(r['amount'] for r in rows),sum(r['amount'] for r in old_rows)
        delta = used-old
        lines = ['PERBANDINGAN PENGELUARAN',f'{day_label(start)} – {day_label(current_end-timedelta(days=1))}: {rupiah(used)}',
                 f'{day_label(previous_start)} – {day_label(previous_end-timedelta(days=1))}: {rupiah(old)}','']
        if delta==0: lines.append('Total pengeluaran tetap sama.')
        else:
            change = 'Naik' if delta>0 else 'Turun'
            lines.append(f'{change} {rupiah(abs(delta))}'+(f" ({abs(delta)*100/old:.1f}%).".replace('.',',',1) if old else '.'))
        if old==0: lines.append('Persentase tidak dihitung karena total periode sebelumnya nol.')
        if current:
            lines.append('Bulan berjalan belum selesai. '+('Perbandingan memakai tanggal yang setara.' if mode=='equal' else 'Pembanding memakai satu bulan penuh.'))
        for title,records in [('KATEGORI TERBESAR PERIODE INI',rows),('KATEGORI TERBESAR PERIODE SEBELUMNYA',old_rows)]:
            totals = {}
            for row in records: totals[row['category']] = totals.get(row['category'],0)+row['amount']
            lines += ['',title]
            lines += [f'{i}. {name}: {rupiah(amount)}' for i,(name,amount) in enumerate(sorted(totals.items(),key=lambda x:(-x[1],x[0]))[:3],1)] or ['Belum ada pengeluaran.']
        buttons = [[button('‹ Bulan sebelumnya',f'compare:{previous_start:%Y-%m}:equal'),button('Bulan berikutnya ›',f'compare:{end:%Y-%m}:equal')]]
        if current: buttons.append([button('Bandingkan bulan penuh' if mode=='equal' else 'Bandingkan tanggal setara',f"compare:{month}:{'full' if mode=='equal' else 'equal'}")])
        return Reply('\n'.join(lines),buttons+navigation())
