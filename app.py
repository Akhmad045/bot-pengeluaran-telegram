"""Menu, laporan, dan tindakan pengguna untuk bot pengeluaran."""
from datetime import datetime, timedelta, timezone
import re

from core import Store, ZONES, MONTHS, day_label, month_range, read_day, rupiah, parse_batch
from excel_export import build_excel
from v24 import WalletFeatures
from ui import Document, Reply, button, navigation

PAGE_SIZE = 6
WEEKDAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


HELP = """CARA MENCATAT
Kirim satu atau beberapa baris sekaligus:
50000 bensin
20000 makan
15000 minum

Kategori opsional:
15rb makan siang | Makanan

Tanggal lain:
/catat 2026-09-19 15rb makan siang
Untuk beberapa tanggal, tulis tanggal di setiap baris.

MENU
/menu — ringkasan dan tombol fitur
/riwayat — catatan dan koreksi
/laporan — laporan dan Excel
/pengaturan — pengingat, zona, bantuan, dan cadangan
/riwayatedit — nilai sebelum/sesudah edit dan urungkan
/pilih — hapus atau ganti kategori beberapa catatan
/cadangan — unduh cadangan lengkap (pemilik bot)
/kategoriotomatis — atur kata untuk kategori otomatis
/favorit — catat dari template favorit
/rekapotomatis — jadwal rekap mingguan/bulanan
/anggarankategori — batas pengeluaran per kategori
/tagihan — pengingat tagihan rutin dan pencatatan pembayaran
/pemasukan — catat pemasukan, pilih dompet, lalu konfirmasi
/saldo — saldo dan arus kas bulanan
/dompet — dompet, saldo awal, dan sumber pembayaran bawaan
/transfer — pindahkan saldo antardompet melalui tombol
/hariini — rincian hari ini
/harian 2026-09-19 — tanggal tertentu
/bulanini — rekap bulan ini
/bulanan 2026-09 — bulan tertentu
/excel — Excel bulan ini
/excel 2026-09 — Excel bulan tertentu
/excel 2026-09-19 — Excel satu hari
/hapus — pilih pengeluaran yang ingin dihapus
/pulihkan — kembalikan pengeluaran yang dihapus
/edit — ubah nominal, keterangan, kategori, atau tanggal
/anggaran — atur batas pengeluaran bulanan
/anggaran 1,5jt — anggaran bulan ini
/cari bensin — cari pengeluaran dan atur filter
/pengingat — aktif/nonaktif dan jam pengingat
/banding — perbandingan antarbulan
/batal — batalkan input atau draf yang sedang dibuka
/clear — bersihkan pesan, catatan tetap tersimpan
/zona — pilih WIB, WITA, atau WIT
/id — ID akun Telegram

Mengedit atau menghapus chat lewat Telegram tidak mengubah catatan pengeluaran."""


class ExpenseBot(WalletFeatures):
    def __init__(self, store: Store, allowed_ids: set[int], zone: timezone, clock=None, owner_id=None, backups=None):
        self.store, self.allowed_ids, self.zone = store, allowed_ids, zone
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.owner_id = owner_id if owner_id is not None else (next(iter(allowed_ids)) if len(allowed_ids)==1 else None)
        if self.owner_id is not None and self.owner_id not in allowed_ids:
            raise ValueError('Pemilik bot harus tercantum dalam daftar pengguna yang diizinkan.')
        self.backups = backups

    def now(self, user_id):
        return self.clock().astimezone(self.store.get_zone(user_id, self.zone))

    def base_menu(self, user):
        uid, now = user["id"], self.now(user["id"])
        name = ("@" + user["username"]) if user.get("username") else (
            " ".join(filter(None, [user.get("first_name"),user.get("last_name")])) or "teman")
        today = self.store.rows(uid, now.date(), now.date() + timedelta(days=1))
        start, end = month_range(now.strftime("%Y-%m"))
        monthly = self.store.rows(uid, start, end)
        text = (f"Halo! {name}\nZona waktu: {now.tzname()} (UTC+{int(now.utcoffset().total_seconds()//3600)})\n"
                f"{WEEKDAYS[now.weekday()]}, {day_label(now.date())}\nWaktu sekarang: {now:%H:%M:%S}\n\n"
                f"Hari ini: {rupiah(sum(r['amount'] for r in today))}\n"
                f"{len(today)} catatan hari ini\n"
                f"Bulan {MONTHS[now.month]}: {rupiah(sum(r['amount'] for r in monthly))}\n\n"
                "Pilih menu di bawah atau langsung kirim pengeluaran.")
        if self.store.budget(uid,now.strftime('%Y-%m')):
            text += '\n\n'+self.budget_text(uid,now.strftime('%Y-%m'))
        return Reply(text, [
            [button("➕ Catat", "add"),button("📖 Riwayat", "history")],
            [button("📊 Laporan", "reports"),button("💰 Anggaran", f"budget:{now:%Y-%m}")],
            [button("⚙ Pengaturan", "settings"),button("🔄 Perbarui", "menu")]])

    def base_add_prompt(self):
        return Reply("TAMBAH PENGELUARAN\n\nKirim satu atau beberapa baris:\n"
                     "50000 bensin\n20000 makan\n15000 minum\n\n"
                     "Boleh memakai 50rb atau 50.000.\nKategori opsional: 50rb bensin | Transportasi\n"
                     "Maksimal 100 baris per pesan.")

    def daily(self, user_id, day, page=0):
        rows = self.store.rows(user_id,day,day+timedelta(days=1))
        page = max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        offset = page*PAGE_SIZE
        lines = [f"PENGELUARAN {day_label(day)}",f"Total: {rupiah(sum(r['amount'] for r in rows))}",
                 f"Jumlah: {len(rows)} catatan", ""]
        for i,r in enumerate(rows[offset:offset+PAGE_SIZE],offset+1):
            lines.append(f"{i}. {r['note']} — {rupiah(r['amount'])} ({r['category']})\n   Dompet: {self.wallet_label(user_id,r['wallet_id'])}")
        if not rows:
            lines.append("Belum ada pengeluaran pada tanggal ini.")
        buttons = []
        pages = []
        if page:
            pages.append(button("‹ Daftar sebelumnya",f"daily:{day}:{page-1}"))
        if offset+PAGE_SIZE < len(rows):
            pages.append(button("Daftar berikutnya ›",f"daily:{day}:{page+1}"))
        if pages:
            buttons.append(pages)
        buttons += [[button("‹ Hari sebelumnya",f"daily:{day-timedelta(days=1)}:0"),
                     button("Hari berikutnya ›",f"daily:{day+timedelta(days=1)}:0")],
                    [button("📁 Excel tanggal ini",f"xlsx:{day}"),button("🗑 Hapus", "deletelist:0")]]
        return Reply("\n".join(lines), buttons+[[button('✏ Edit','editlist:0'),button('🔎 Cari & filter','search:0')]]+navigation())

    def monthly(self, user_id, month):
        start,end = month_range(month)
        rows = self.store.rows(user_id,start,end)
        lines = [f"PENGELUARAN {MONTHS[start.month]} {start.year}",
                 f"Total: {rupiah(sum(r['amount'] for r in rows))}",f"Jumlah: {len(rows)} catatan"]
        days,categories = {},{}
        for r in rows:
            days[r['spent_on']] = days.get(r['spent_on'],0)+r['amount']
            categories[r['category']] = categories.get(r['category'],0)+r['amount']
        if not rows:
            lines += ["", "Belum ada pengeluaran pada bulan ini."]
        else:
            lines += ["", "PER HARI"]+[f"{i}. {d}: {rupiah(v)}" for i,(d,v) in enumerate(sorted(days.items()),1)]
            ordered = sorted(categories.items(),key=lambda x:(-x[1],x[0]))
            lines += ["", "PER KATEGORI"]+[f"{i}. {c}: {rupiah(v)}" for i,(c,v) in enumerate(ordered[:6],1)]
            if len(ordered)>6:
                lines.append("Seluruh kategori tersedia di Excel.")
        if self.store.budget(user_id,month):
            lines += ['',self.budget_text(user_id,month)]
        return Reply("\n".join(lines),[
            [button("‹ Bulan sebelumnya",f"monthly:{(start-timedelta(days=1)):%Y-%m}"),
             button("Bulan berikutnya ›",f"monthly:{end:%Y-%m}")],
            [button("📁 Excel bulan ini",f"xlsx:{month}"),button("🗑 Hapus","deletelist:0")],
            [button('💰 Anggaran',f'budget:{month}'),button('📈 Bandingkan',f'compare:{month}:equal')]]+navigation())

    def expense_list(self, user_id, page=0, deleted=False):
        rows = self.store.history(user_id,deleted)
        page = max(0,min(page,max(0,(len(rows)-1)//PAGE_SIZE)))
        prefix = "restorelist" if deleted else "deletelist"
        title = "PULIHKAN PENGELUARAN" if deleted else "HAPUS PENGELUARAN"
        lines = [title,"Pilih pengeluaran melalui tombol di bawah.",""]
        buttons=[]
        for i,row in enumerate(rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page*PAGE_SIZE+1):
            lines.append(f"{i}. {row['note']} — {rupiah(row['amount'])}\n   {row['spent_on']}")
            label=f"{i}. {row['note'][:25]} — {rupiah(row['amount'])}"
            action="restore" if deleted else "deleteask"
            buttons.append([button(label,f"{action}:{row['id']}:{page}")])
        if not rows:
            lines.append("Tidak ada pengeluaran yang bisa dipulihkan." if deleted else "Belum ada pengeluaran.")
        pages=[]
        if page:
            pages.append(button("‹ Sebelumnya",f"{prefix}:{page-1}"))
        if (page+1)*PAGE_SIZE<len(rows):
            pages.append(button("Berikutnya ›",f"{prefix}:{page+1}"))
        if pages:
            buttons.append(pages)
        return Reply("\n".join(lines),buttons+navigation())

    def delete_prompt(self, user_id, record_id, page=0):
        row=self.store.get(user_id,record_id)
        if row is None or row['deleted']:
            return Reply("Pengeluaran tidak ditemukan atau sudah dihapus.",
                         [[button("Kembali ke daftar",f"deletelist:{page}")]]+navigation())
        return Reply(f"HAPUS PENGELUARAN INI?\n\n{row['note']}\n"
                     f"Nominal: {rupiah(row['amount'])}\nKategori: {row['category']}\n"
                     f"Tanggal: {row['spent_on']}\n\nPengeluaran yang dihapus dapat dipulihkan.",
                     [[button("Ya, hapus",f"deleteyes:{record_id}:{page}"),
                       button("Batal",f"deletelist:{page}")]])

    def zone_menu(self, user_id):
        return Reply(f"ZONA WAKTU INDONESIA\nSaat ini: {self.now(user_id).tzname()}\n\n"
                     "Pilih zona waktumu. Tanggal catatan yang sudah tersimpan tetap sama.",
                     [[button("WIB (UTC+7)","zone:WIB")], [button("WITA (UTC+8)","zone:WITA")],
                      [button("WIT (UTC+9)","zone:WIT")]]+navigation())

    def clear_prompt(self):
        return Reply("BERSIHKAN CHAT?\n\nBot akan menghapus pesan yang dikenali dan masih dapat dihapus "
                     "dalam 48 jam terakhir.\nData pengeluaran tetap tersimpan.\n\n"
                     "Pesan lebih lama atau pesan dari versi bot lama mungkin perlu dibersihkan "
                     "melalui fitur Hapus Riwayat di Telegram.",
                     [[button("Bersihkan chat", "clear:yes"),button("Batal", "menu")]])

    def excel_menu(self, user_id, month=None):
        month = month or self.now(user_id).strftime("%Y-%m")
        start,end=month_range(month)
        return Reply(f"EKSPOR EXCEL\nPeriode: {MONTHS[start.month]} {start.year}\n\n"
                     "File berisi total, rekap per hari dan kategori, serta rincian transaksi.",
                     [[button("📥 Unduh Excel",f"xlsx:{month}")],
                      [button("‹ Bulan sebelumnya",f"excelpick:{(start-timedelta(days=1)):%Y-%m}"),
                       button("Bulan berikutnya ›",f"excelpick:{end:%Y-%m}")]]+navigation())

    def excel(self, user_id, period):
        if len(period)==10:
            start=read_day(period)
            end=start+timedelta(days=1)
            label=day_label(start)
        else:
            start,end=month_range(period)
            label=f"{MONTHS[start.month]} {start.year}"
        rows=self.store.rows(user_id,start,end)
        data=build_excel(rows,start,end,label,self.now(user_id).tzname())
        return Reply(f"Excel {label} siap.\nJumlah: {len(rows)} catatan\n"
                     f"Total: {rupiah(sum(r['amount'] for r in rows))}",
                     document=Document(f"pengeluaran-{period}.xlsx",data,
                                       f"Pengeluaran {label}. Data pada saat ekspor."))

    def record(self, message, text):
        uid=message['from']['id']
        zone=self.store.get_zone(uid,self.zone)
        stamp=datetime.fromtimestamp(message['date'],zone)
        expenses=self.categorize_expenses(uid,parse_batch(text,stamp.date()),text)
        rows,added=self.store.add_many(uid,message,expenses,stamp)
        if not added:
            return Reply(f"Pesan ini sudah tercatat ({len(rows)} pengeluaran).\n"
                         "Tidak ada catatan ganda yang ditambahkan.",
                         [[button("Lihat hari ini","today"),button("🗑 Hapus","deletelist:0")]]+navigation())
        lines=[f"Tercatat {len(rows)} pengeluaran",""]
        for i,row in enumerate(rows,1):
            lines += [f"{i}. {row['note']} — {rupiah(row['amount'])}",
                      f"   Kategori: {row['category']}",f"   Dompet: {self.wallet_label(uid,row['wallet_id'])}",f"   Tanggal: {day_label(read_day(row['spent_on']))}"]
        days=sorted({r['spent_on'] for r in rows})
        lines += ["",f"Total ditambahkan: {rupiah(sum(r['amount'] for r in rows))}"]
        # Beberapa periode dalam satu pesan tetap masuk ke tanggal dan bulan yang tepat.
        for d in days:
            day=read_day(d)
            total=sum(r['amount'] for r in self.store.rows(uid,day,day+timedelta(days=1)))
            lines.append(f"Total {day_label(day)}: {rupiah(total)}")
        for m in sorted({d[:7] for d in days}):
            start,end=month_range(m)
            total=sum(r['amount'] for r in self.store.rows(uid,start,end))
            lines.append(f"Total {MONTHS[start.month]} {start.year}: {rupiah(total)}")
        reply = Reply("\n".join(lines),[[button("📅 Hari ini","today"),button("✏ Edit","editlist:0")]]+navigation())
        return self.with_budget_notices(uid,reply,{d[:7] for d in days})

    def handle(self, message):
        uid = message.get('from',{}).get('id')
        if (uid not in self.allowed_ids or message.get('chat',{}).get('type')!='private'
                or not isinstance(message.get('text'),str)):
            return self._handle(message)
        key = f"m:{message['chat']['id']}:{message['message_id']}"
        with self.store.transaction():
            saved = self.store.get_receipt(key,uid)
            if saved: return Reply.from_json(saved)
            reply = self._handle(message)
            if reply and reply.document is None:
                self.store.save_receipt(key,uid,reply.to_json(),self.stamp())
            return reply

    def _handle(self, message):
        if (message.get('chat',{}).get('type')!='private' or not message.get('from')
                or not isinstance(message.get('text'),str)):
            return None
        user=message['from']; uid=user['id']; text=message['text'].strip()
        text={"Hari ini":"/hariini","Bulan ini":"/bulanini","Catat pengeluaran":"/catat",
              "Bantuan":"/bantuan"}.get(text,text)
        bits=text.split(maxsplit=1)
        command=bits[0].split('@')[0].lower() if bits and text.startswith('/') else ''
        arg=bits[1].strip() if command and len(bits)>1 else ''
        if command=='/id':
            return Reply(f"ID Telegram kamu: {uid}\nMasukkan ID ini ke allowed_user_ids (laptop) "
                         "atau ALLOWED_USER_IDS (hosting).",[])
        if uid not in self.allowed_ids:
            return Reply("Akun ini belum diberi akses. Kirim /id, masukkan ID ke pengaturan bot, "
                         "lalu mulai ulang program.",[])
        try:
            now=self.now(uid)
            if command:
                self.store.cancel_pending(uid)
                feature = self.feature_command(uid,command,arg)
                if feature is not None: return feature
            else:
                pending = self.pending_input(uid,text)
                if pending is not None: return pending
            if command in ('/start','/menu'):
                return self.menu(user)
            if command in ('/help','/bantuan'):
                return Reply(HELP)
            if command=='/catat' and not arg:
                return self.add_prompt(uid)
            if command in ('/hariini','/harian'):
                if command=='/hariini' and arg:
                    raise ValueError("Untuk tanggal lain gunakan /harian YYYY-MM-DD.")
                return self.daily(uid,read_day(arg) if arg else now.date())
            if command in ('/bulanini','/bulanan'):
                if command=='/bulanini' and arg:
                    raise ValueError("Untuk bulan lain gunakan /bulanan YYYY-MM.")
                return self.monthly(uid,arg or now.strftime('%Y-%m'))
            if command=='/excel':
                return self.excel(uid,arg or now.strftime('%Y-%m'))
            if command=='/hapus':
                if not arg:
                    return self.expense_list(uid)
                if not re.fullmatch(r'[0-9]{1,18}',arg):
                    return Reply("Gunakan tombol pada daftar untuk menghapus pengeluaran.",
                                 [[button("Buka daftar pengeluaran","deletelist:0")]])
                return self.delete_prompt(uid,int(arg))
            if command=='/pulihkan':
                if not arg:
                    return self.expense_list(uid,deleted=True)
                if not re.fullmatch(r'[0-9]{1,18}',arg) or self.store.get(uid,int(arg)) is None:
                    return Reply("Catatan tidak ditemukan di akunmu.")
                self.store.set_deleted(uid,int(arg),False)
                return self.with_budget_notices(uid,Reply("Pengeluaran dipulihkan dan kembali masuk ke rekap."),
                                                {self.store.get(uid,int(arg))['spent_on'][:7]})
            if command=='/clear':
                return self.clear_prompt()
            if command=='/zona':
                return self.zone_menu(uid)
            if command and command!='/catat':
                return Reply("Perintah tidak dikenal. Buka Menu atau Bantuan.")
            return self.record(message,arg if command else text)
        except ValueError as exc:
            return Reply(str(exc))

    def handle_callback(self, query):
        uid = query.get('from',{}).get('id')
        msg = query.get('message',{})
        if (uid not in self.allowed_ids or msg.get('chat',{}).get('type')!='private'
                or msg.get('chat',{}).get('id')!=uid):
            return None
        key = 'c:'+query['id']
        if query.get('data','').split(':')[0] in ('backup','backupdownload','backuprestore') and uid!=self.owner_id:
            return Reply('Cadangan lengkap hanya dapat diakses pemilik bot.')
        with self.store.transaction():
            saved = self.store.get_receipt(key,uid)
            if saved: return Reply.from_json(saved)
            reply = self._handle_callback(query)
            if reply and reply.document is None:
                self.store.save_receipt(key,uid,reply.to_json(),self.stamp())
            return reply

    def _handle_callback(self, query):
        user=query.get('from',{}); uid=user.get('id'); msg=query.get('message',{})
        if (uid not in self.allowed_ids or msg.get('chat',{}).get('type')!='private'
                or msg.get('chat',{}).get('id')!=uid):
            return None
        parts=query.get('data','').split(':'); action=parts[0]
        try:
            now=self.now(uid)
            if action not in ('editfield','editback','editsave','formsave','quickcommit','quickfield','quickback',
                              'wpick','wset','wsave','mf','mback','msave') and not (action.startswith('bulk') and action!='bulkstart'):
                self.store.cancel_pending(uid)
            feature = self.feature_callback(uid,parts)
            if feature is not None: return feature
            if action=='menu': return self.menu(user)
            if action=='add': return self.add_prompt(uid)
            if action=='help': return Reply(HELP)
            if action=='today': return self.daily(uid,now.date())
            if action=='month': return self.monthly(uid,now.strftime('%Y-%m'))
            if action=='daily': return self.daily(uid,read_day(parts[1]),int(parts[2]))
            if action=='monthly': return self.monthly(uid,parts[1])
            if action=='deletelist': return self.expense_list(uid,int(parts[1]))
            if action=='restorelist': return self.expense_list(uid,int(parts[1]),True)
            if action=='deleteask': return self.delete_prompt(uid,int(parts[1]),int(parts[2]))
            if action in ('deleteyes','restore'):
                rid,page=int(parts[1]),int(parts[2])
                row=self.store.get(uid,rid)
                if row is None: return Reply("Catatan tidak ditemukan di akunmu.")
                self.store.set_deleted(uid,rid,action=='deleteyes',query['id'])
                if action=='deleteyes':
                    return Reply(f"Pengeluaran dihapus dari rekap.\n{row['note']} — {rupiah(row['amount'])}",
                                 [[button("Urungkan",f"restore:{rid}:{page}"),
                                   button("Kembali ke daftar",f"deletelist:{page}")]]+navigation())
                return self.with_budget_notices(uid,Reply("Pengeluaran dipulihkan dan kembali masuk ke rekap.",
                             [[button("Lihat pengeluaran","deletelist:0")]]+navigation()),{row['spent_on'][:7]})
            if action=='zones': return self.zone_menu(uid)
            if action=='zone':
                self.store.set_zone(uid,parts[1])
                if self.store.reminder(uid)['enabled']:
                    self.configure_reminder(uid)
                return self.menu(user)
            if action=='clearprompt': return self.clear_prompt()
            if action=='clear' and parts[1]=='yes':
                return Reply("Pembersihan selesai. Data pengeluaran tetap tersimpan.\n\n"
                             "Untuk pesan lama yang tersisa, gunakan Hapus Riwayat di Telegram.",
                             clear_cutoff=max(msg['message_id'],self.store.latest_message_id(uid)))
            if action=='excelmenu': return self.excel_menu(uid)
            if action=='excelpick': return self.excel_menu(uid,parts[1])
            if action=='xlsx': return self.excel(uid,parts[1])
            return Reply("Menu tidak dikenali. Silakan buka Menu kembali.")
        except ValueError as exc:
            return Reply('Pilihan tidak valid. '+str(exc))
        except (IndexError, OverflowError):
            return Reply("Pilihan tidak valid. Silakan buka Menu kembali.")
