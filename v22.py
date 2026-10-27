"""Menu versi 2.2, riwayat edit, anggaran rutin, dan pilihan banyak catatan."""
from datetime import datetime
import json
import secrets

from core import day_label, month_range, read_day, rupiah
from features import ExtraFeatures, FIELD_NAMES, PAGE_SIZE, month_label
from ui import Reply, button, navigation


class NewFeatures(ExtraFeatures):
    def feature_command(self, uid, command, arg):
        if command=='/riwayat': return self.history_menu()
        if command=='/laporan': return self.reports_menu(uid)
        if command=='/pengaturan': return self.settings_menu(uid)
        if command=='/riwayatedit': return self.change_list(uid)
        if command=='/pilih': return self.begin_bulk(uid)
        if command=='/cadangan': return self.backup_menu(uid)
        return super().feature_command(uid,command,arg)

    def feature_callback(self, uid, parts):
        action = parts[0]
        if action=='history': return self.history_menu()
        if action=='reports': return self.reports_menu(uid)
        if action=='settings': return self.settings_menu(uid)
        if action=='changes': return self.change_list(uid,int(parts[1]),int(parts[2]))
        if action=='change': return self.change_view(uid,int(parts[1]))
        if action=='undoask': return self.undo_prompt(uid,int(parts[1]))
        if action=='undoyes': return self.undo_edit(uid,int(parts[1]))
        if action.startswith('repeat'): return self.recurring_callback(uid,parts)
        if action=='backup': return self.backup_menu(uid)
        if action=='backupdownload':
            self.require_owner(uid)
            return Reply('Cadangan lengkap database siap. Simpan file ini di tempat pribadi.',backup_request=True)
        if action=='backuprestore':
            self.require_owner(uid)
            return Reply('PULIHKAN CADANGAN DATABASE\n\n1. Unduh cadangan dan hentikan bot di hosting/laptop.\n'
                         '2. Di Windows, jalankan PULIHKAN_WINDOWS.bat; masukkan lokasi file cadangan.\n'
                         '3. Periksa ringkasan lalu ketik PULIHKAN untuk melanjutkan.\n'
                         '4. Jalankan bot kembali.\n\nUntuk hosting, ikuti bagian Pemulihan di README.html. '
                         'Data saat ini dicadangkan sebelum diganti. Token tetap memakai konfigurasi hosting tujuan.',
                         [[button('Kembali ke cadangan','backup')]]+navigation())
        if action=='bulkstart': return self.begin_bulk(uid,len(parts)>1 and parts[1]=='search')
        if action.startswith('bulk'): return self.bulk_callback(uid,parts)
        return super().feature_callback(uid,parts)

    def history_menu(self):
        return Reply('RIWAYAT PENGELUARAN\n\nLihat catatan, cari transaksi, atau lakukan koreksi.',[
            [button('📅 Hari ini','today'),button('🔎 Cari & filter','search:0')],
            [button('✏ Edit','editlist:0'),button('🗑 Hapus','deletelist:0')],
            [button('☑ Pilih beberapa','bulkstart:all')],
            [button('🕘 Riwayat edit','changes:0:0'),button('↩ Pulihkan terhapus','restorelist:0')]]+navigation())

    def reports_menu(self, uid):
        month = self.now(uid).strftime('%Y-%m')
        return Reply('LAPORAN PENGELUARAN\n\nPilih laporan atau unduh Excel.',[
            [button('📅 Harian','today'),button('📊 Bulanan','month')],
            [button('📁 Ekspor Excel','excelmenu')],
            [button('📈 Perbandingan bulan',f'compare:{month}:equal')]]+navigation())

    def settings_menu(self, uid):
        buttons = [[button('🔔 Pengingat','reminder'),button('🕒 Zona waktu','zones')],
                   [button('❓ Bantuan','help'),button('🧹 Bersihkan chat','clearprompt')]]
        if uid==self.owner_id: buttons.append([button('💾 Cadangan & pemulihan','backup')])
        return Reply('PENGATURAN\n\nSesuaikan pengingat, waktu, dan pengelolaan bot.',buttons+navigation())

    def require_owner(self, uid):
        if uid!=self.owner_id:
            raise ValueError('Cadangan lengkap hanya dapat diakses pemilik bot.')

    def backup_menu(self, uid):
        self.require_owner(uid)
        latest = self.backups.latest() if self.backups else None
        status = latest.name if latest else 'Belum tersedia; dibuat ketika bot dijalankan.'
        if self.backups and self.backups.last_error:
            status += '\nCadangan terakhir gagal. Periksa ruang/izin penyimpanan hosting; bot mencoba lagi setiap 5 menit.'
        return Reply('CADANGAN & PEMULIHAN\n\nCadangan harian otomatis pukul 03.00 '+self.now(uid).tzname()+
                     '. Disimpan 14 cadangan harian terakhir.\nCadangan terbaru: '+status+
                     '\n\nIsi: semua pengguna, pengeluaran aktif/terhapus, riwayat edit, anggaran bulanan/kategori, '
                     'pemasukan, dompet dan saldo awal, transfer, favorit, aturan kategori, jadwal rekap, '
                     'tagihan dan status pembayarannya, zona, serta pengingat. '
                     'Token bot tidak disertakan.\n\nUnduh salinan secara berkala; cadangan di hosting ikut hilang jika '
                     'penyimpanannya dihapus. File unduhan berisi data seluruh pengguna bot.',[
                         [button('📥 Buat & unduh cadangan','backupdownload')],
                         [button('↩ Cara memulihkan','backuprestore')],
                         [button('Kembali ke pengaturan','settings')]])

    def change_list(self, uid, record_id=0, page=0):
        rows = self.store.changes(uid,record_id or None)
        page = max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        lines,buttons = ['RIWAYAT PERUBAHAN','Pilih perubahan untuk melihat sebelum/sesudah.',''],[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            values = json.loads(row['after_json'])
            when = datetime.fromisoformat(row['changed_at']).astimezone(self.now(uid).tzinfo)
            kind = {'edit':'Edit','bulk_category':'Ubah kategori bersama','undo':'Urungkan edit'}[row['kind']]
            lines.append(f"{i}. {values['note']} — {kind}\n   {when:%d-%m-%Y %H:%M:%S} {when.tzname()}")
            buttons.append([button(f"{i}. {values['note'][:32]}",f"change:{row['id']}")])
        if not rows: lines.append('Belum ada perubahan. Riwayat mulai dicatat sejak versi 2.2.')
        pages=[]
        if page: pages.append(button('‹ Sebelumnya',f'changes:{record_id}:{page-1}'))
        if (page+1)*PAGE_SIZE<len(rows): pages.append(button('Berikutnya ›',f'changes:{record_id}:{page+1}'))
        if pages: buttons.append(pages)
        return Reply('\n'.join(lines),buttons+[[button('Kembali ke riwayat','history')]]+navigation())

    def change_text(self, uid, change):
        before,after = json.loads(change['before_json']),json.loads(change['after_json'])
        when = datetime.fromisoformat(change['changed_at']).astimezone(self.now(uid).tzinfo)
        lines = [f"Catatan: {after['note']}",f"Waktu: {when:%d-%m-%Y %H:%M:%S} {when.tzname()}",'']
        for key,name in FIELD_NAMES.items():
            if before[key]==after[key]: continue
            old,new = before[key],after[key]
            if key=='amount': old,new = rupiah(old),rupiah(new)
            if key=='spent_on': old,new = day_label(read_day(old)),day_label(read_day(new))
            lines += [name,f'Sebelum: {old}',f'Sesudah: {new}','']
        return '\n'.join(lines).rstrip()

    def change_view(self, uid, change_id):
        change = self.store.change(uid,change_id)
        if change is None: raise ValueError('Riwayat perubahan tidak ditemukan di akunmu.')
        buttons=[]
        if self.store.can_undo(uid,change): buttons.append([button('↩ Urungkan edit',f'undoask:{change_id}')])
        text = 'DETAIL PERUBAHAN\n\n'+self.change_text(uid,change)
        if change['undone_by'] is not None: text += '\n\nPerubahan ini sudah diurungkan.'
        elif not self.store.can_undo(uid,change): text += '\n\nUrungkan tersedia untuk edit terakhir pada catatan yang belum berubah lagi.'
        return Reply(text,buttons+[[button('Riwayat catatan ini',f"changes:{change['record_id']}:0")]]+navigation())

    def undo_prompt(self, uid, change_id):
        change = self.store.change(uid,change_id)
        if not self.store.can_undo(uid,change):
            raise ValueError('Edit tidak bisa diurungkan: catatan sudah berubah, dihapus, atau edit sudah diurungkan.')
        return Reply('URUNGKAN EDIT INI?\n\n'+self.change_text(uid,change)+
                     '\n\nCatatan akan dikembalikan ke nilai Sebelum. Laporan dan anggaran ikut diperbarui.',[
                         [button('Ya, urungkan',f'undoyes:{change_id}'),button('Batal',f'change:{change_id}')]])

    def undo_edit(self, uid, change_id):
        change = self.store.change(uid,change_id)
        if not self.store.undo_change(uid,change_id,self.clock().isoformat()):
            raise ValueError('Catatan sudah berubah atau edit sudah diurungkan. Muat kembali riwayat.')
        months = {json.loads(change[key])['spent_on'][:7] for key in ('before_json','after_json')}
        return self.with_budget_notices(uid,Reply('Edit berhasil diurungkan. Nilai sebelumnya sudah dipulihkan.',[
            [button('Lihat riwayat perubahan',f"changes:{change['record_id']}:0")]]+navigation()),months)

    def next_budget_month(self, uid):
        return month_range(self.now(uid).strftime('%Y-%m'))[1].strftime('%Y-%m')

    def budget_view(self, uid, month):
        reply = super().budget_view(uid,month)
        budget = self.store.budget(uid,month)
        next_month = self.next_budget_month(uid)
        rule = self.store.budget_rule(uid,next_month)
        if rule and rule['amount'] is not None:
            reply.text += f"\n\nAnggaran otomatis mulai {month_label(next_month)}: {rupiah(rule['amount'])} per bulan."
            reply.buttons.insert(1,[button('Nonaktifkan mulai bulan depan',f'repeatoffask:{next_month}')])
            if budget and budget['source']=='manual' and self.store.budget_rule(uid,month):
                active = self.store.budget_rule(uid,month)
                if active['amount'] is not None:
                    reply.buttons.insert(1,[button('Gunakan nominal otomatis bulan ini',f'repeatresetask:{month}')])
        else: reply.text += '\n\nAnggaran otomatis bulan berikutnya: Nonaktif.'
        if budget:
            reply.text += '\nSumber bulan ini: '+('anggaran otomatis.' if budget['source']=='auto' else 'nominal khusus bulan ini.')
            reply.buttons.insert(1,[button('Gunakan anggaran ini setiap bulan',f'repeatask:{month}')])
        return reply

    def recurring_callback(self, uid, parts):
        action = parts[0]
        next_month = self.next_budget_month(uid)
        if action=='repeatask':
            month_range(parts[1])
            budget = self.store.budget(uid,parts[1])
            if budget is None: raise ValueError('Atur nominal anggaran terlebih dahulu.')
            return Reply(f"GUNAKAN SETIAP BULAN?\n\n{rupiah(budget['amount'])} per bulan, mulai {month_label(next_month)}.\n"
                         'Nominal khusus yang sudah diatur untuk bulan tertentu tetap berlaku.',[
                             [button('Ya, gunakan',f"repeatyes:{parts[1]}:{budget['amount']}:{next_month}"),
                              button('Batal',f'budget:{parts[1]}')]])
        if action=='repeatyes':
            month_range(parts[1])
            if parts[3]!=next_month: raise ValueError('Bulan sudah berganti. Buka anggaran dan konfirmasi kembali.')
            self.store.set_budget_rule(uid,next_month,int(parts[2]),self.clock().isoformat())
            return self.budget_view(uid,parts[1])
        if action=='repeatoffask':
            return Reply(f'NONAKTIFKAN ANGGARAN OTOMATIS?\n\nMulai {month_label(next_month)}. '
                         'Anggaran bulan berjalan dan nominal khusus tetap tersimpan.',[
                             [button('Ya, nonaktifkan',f'repeatoff:{next_month}'),button('Batal',f'budget:{self.now(uid):%Y-%m}')]])
        if action=='repeatoff':
            if parts[1]!=next_month: raise ValueError('Bulan sudah berganti. Konfirmasi kembali.')
            self.store.set_budget_rule(uid,next_month,None,self.clock().isoformat())
            return self.budget_view(uid,self.now(uid).strftime('%Y-%m'))
        if action=='repeatresetask':
            month_range(parts[1])
            rule = self.store.budget_rule(uid,parts[1])
            if not rule or rule['amount'] is None: raise ValueError('Tidak ada nominal otomatis untuk bulan ini.')
            return Reply(f"GANTI NOMINAL KHUSUS?\n\nAnggaran {month_label(parts[1])} akan mengikuti nominal otomatis: "
                         f"{rupiah(rule['amount'])}.",[[button('Ya, ganti',f"repeatreset:{parts[1]}:{rule['amount']}"),
                                                   button('Batal',f'budget:{parts[1]}')]])
        if action=='repeatreset':
            month_range(parts[1]); rule = self.store.budget_rule(uid,parts[1])
            if not rule or rule['amount']!=int(parts[2]): raise ValueError('Nominal otomatis berubah. Konfirmasi kembali.')
            self.store.reset_budget_override(uid,parts[1])
            return self.with_budget_notices(uid,self.budget_view(uid,parts[1]),{parts[1]})
        raise ValueError('Pilihan anggaran tidak dikenal.')

    def begin_bulk(self, uid, filtered=False):
        filters = self.store.filters(uid) if filtered else {'keyword':'','category':None,'start':None,'end':None}
        state = self.store.start_pending(uid,'bulk',{'selected':{},'filters':filters,'page':0,
            'stage':'choose','action':None,'category':None,'confirm':None},self.stamp())
        return self.bulk_view(uid,state)

    def bulk_rows(self, uid, state):
        return self.store.search_expenses(uid,state['data']['filters'])

    def bulk_view(self, uid, state):
        data,token = state['data'],state['token']
        rows = self.bulk_rows(uid,state)
        page = max(0,min(data['page'],max(0,(len(rows)-1)//PAGE_SIZE)))
        selected = data['selected']
        lines = ['PILIH BEBERAPA CATATAN',f'Terpilih: {len(selected)} dari maksimal 50 catatan.',
                 'Tekan catatan untuk memilih/melepas. Pilihan tersimpan saat pindah halaman.','']
        f = data['filters']
        if any(f.values()): lines += [f"Filter: {f['keyword'] or 'semua kata'} | {f['category'] or 'semua kategori'}",
                                     f"Tanggal: {f['start'] or 'awal'} s.d. {f['end'] or 'terbaru'}",'']
        buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            mark = '☑' if str(row['id']) in selected else '☐'
            lines.append(f"{i}. {row['note']} — {rupiah(row['amount'])}\n   {row['spent_on']} ({row['category']}) {mark}")
            buttons.append([button(f"{mark} {i}. {row['note'][:28]}",f"bulktoggle:{token}:{row['id']}")])
        if not rows: lines.append('Tidak ada catatan yang sesuai.')
        pages=[]
        if page: pages.append(button('‹ Sebelumnya',f'bulkpage:{token}:{page-1}'))
        if (page+1)*PAGE_SIZE<len(rows): pages.append(button('Berikutnya ›',f'bulkpage:{token}:{page+1}'))
        if pages: buttons.append(pages)
        if rows: buttons.append([button('Pilih halaman ini',f'bulkall:{token}:{page}'),button('Lepas semua',f'bulkclear:{token}')])
        if selected:
            buttons.append([button('🗑 Hapus terpilih',f'bulkaction:{token}:delete'),
                            button('🏷 Ganti kategori',f'bulkaction:{token}:category')])
        buttons.append([button('Batal','cancel')])
        return Reply('\n'.join(lines),buttons)

    def bulk_callback(self, uid, parts):
        action,token = parts[:2]
        state = self.require_pending(uid,token,'bulk'); data = state['data']
        if action=='bulkapply':
            if data['stage']!='confirm' or not data['confirm'] or parts[2]!=data['confirm']:
                raise ValueError('Konfirmasi sudah tidak aktif. Periksa pilihan kembali.')
            months={self.store.get(uid,int(rid))['spent_on'][:7] for rid in data['selected'] if self.store.get(uid,int(rid))}
            changed = self.store.apply_bulk(uid,data['selected'],data['action'],data['category'],self.clock().isoformat())
            self.store.cancel_pending(uid)
            text = (f'{changed} catatan dihapus dari rekap. Kamu dapat memulihkannya melalui Riwayat → Pulihkan terhapus.'
                    if data['action']=='delete' else f"Kategori diperbarui pada {changed} catatan menjadi {data['category']}. "
                    'Catatan yang sudah memakai kategori tersebut tetap sama. Perubahan tersedia di Riwayat edit.')
            return self.with_budget_notices(uid,Reply(text,[[button('Kembali ke riwayat','history'),button('Riwayat edit','changes:0:0')]]+navigation()),months)
        data['confirm'] = None
        if action=='bulkaction':
            if not data['selected']: raise ValueError('Pilih setidaknya satu catatan.')
            if parts[2] not in ('delete','category'): raise ValueError('Tindakan tidak dikenal.')
            data['action'] = parts[2]
            if parts[2]=='delete': return self.bulk_preview(uid,state)
            data['stage'] = 'category'
            self.store.update_pending(uid,token,data,self.stamp())
            return Reply(f"GANTI KATEGORI {len(data['selected'])} CATATAN\n\nKirim kategori baru, maksimal 32 karakter. "
                         'Perubahan akan ditinjau sebelum disimpan.',[[button('Kembali ke pilihan',f'bulkback:{token}'),button('Batal','cancel')]])
        if action=='bulktoggle':
            rid = str(int(parts[2])); available = {str(r['id']):r for r in self.bulk_rows(uid,state)}
            if rid in data['selected']: del data['selected'][rid]
            elif rid not in available: raise ValueError('Catatan tidak tersedia. Muat pilihan kembali.')
            elif len(data['selected'])>=50: raise ValueError('Maksimal 50 catatan. Kurangi pilihan terlebih dahulu.')
            else: data['selected'][rid] = available[rid]['revision']
        elif action=='bulkall':
            page = max(0,int(parts[2])); rows = self.bulk_rows(uid,state)[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
            if len(set(data['selected'])|{str(r['id']) for r in rows})>50:
                raise ValueError('Pilihan akan melebihi 50 catatan. Pilih satu per satu atau kurangi pilihan.')
            for row in rows: data['selected'].setdefault(str(row['id']),row['revision'])
        elif action=='bulkclear': data['selected'] = {}
        elif action=='bulkpage': data['page'] = max(0,int(parts[2]))
        elif action!='bulkback': raise ValueError('Pilihan tidak dikenal.')
        data['stage'] = 'choose'
        return self.bulk_view(uid,self.store.update_pending(uid,token,data,self.stamp()))

    def bulk_preview(self, uid, state):
        data,token = state['data'],state['token']
        rows = [self.store.get(uid,int(rid)) for rid in data['selected']]
        if not rows or any(r is None or r['deleted'] or r['revision']!=data['selected'][str(r['id'])] for r in rows):
            raise ValueError('Pilihan sudah berubah. Batalkan lalu pilih ulang catatan; belum ada perubahan disimpan.')
        title = 'HAPUS CATATAN TERPILIH?' if data['action']=='delete' else 'GANTI KATEGORI CATATAN TERPILIH?'
        lines = [title,f"Jumlah: {len(rows)} catatan",f"Total: {rupiah(sum(r['amount'] for r in rows))}"]
        if data['action']=='category': lines.append('Kategori baru: '+data['category'])
        lines.append('')
        for i,row in enumerate(rows,1):
            lines.append(f"{i}. {row['note']} — {rupiah(row['amount'])}\n   {row['spent_on']} ({row['category']})")
        data['stage'],data['confirm'] = 'confirm',secrets.token_hex(4)
        self.store.update_pending(uid,token,data,self.stamp())
        return Reply('\n'.join(lines),[[button('Ya, lanjutkan',f"bulkapply:{token}:{data['confirm']}"),
                                      button('Kembali ke pilihan',f'bulkback:{token}')],[button('Batal','cancel')]])

    def pending_input(self, uid, text):
        state = self.store.pending(uid)
        if state and state['kind']=='bulk' and state['expires_at']>self.stamp():
            if state['data']['stage']!='category':
                return Reply('Pilihan beberapa catatan masih terbuka. Gunakan tombol untuk melanjutkan atau batalkan.',
                             self.bulk_view(uid,state).buttons)
            value = ' '.join(text.split()).capitalize()
            if not 1<=len(value)<=32:
                return Reply('Kategori wajib diisi, maksimal 32 karakter. Kirim ulang atau batalkan.',[[button('Batal','cancel')]])
            state['data']['category'] = value
            try: return self.bulk_preview(uid,state)
            except ValueError as exc: return Reply(str(exc),[[button('Batal','cancel')]])
        return super().pending_input(uid,text)
