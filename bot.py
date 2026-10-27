"""Bot pengeluaran Telegram v2.4. Python 3.10+, tanpa paket tambahan."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core import (Store, ZONES, parse_amount, parse_expense, parse_batch, month_range,
                  read_day, rupiah, Expense)
from app import ExpenseBot, Reply
from features import next_reminder_time
from backups import BackupManager, RuntimeLock, backup_before_upgrade
from ui import Document
from schedule_v23 import send_scheduled_reports, send_bill_reminders

ROOT = Path(__file__).resolve().parent


def split_text(text: str, limit: int = 1800):
    chunks=[]
    while len(text)>limit:
        cut=text.rfind('\n',0,limit+1)
        if cut<=0: cut=limit
        chunks.append(text[:cut])
        text=text[cut:]
        if text.startswith('\n'): text=text[1:]
    if text: chunks.append(text)
    return chunks


class APIError(Exception):
    def __init__(self, code: int, retry_after: int = 3, description: str = ''):
        self.code,self.retry_after,self.description=code,retry_after,description
        super().__init__(f'Telegram API error {code}')


class Telegram:
    def __init__(self, token: str, store: Store | None = None):
        self._base=f'https://api.telegram.org/bot{token}/'
        self._last_sent={}
        self.store=store

    def _request(self, method, data, content_type):
        request=Request(self._base+method,data=data,headers={'Content-Type':content_type},method='POST')
        try:
            with urlopen(request,timeout=45) as response:
                body=json.load(response)
        except HTTPError as exc:
            try: body=json.loads(exc.read().decode('utf-8'))
            except (ValueError,UnicodeError): body={}
            raise APIError(exc.code,body.get('parameters',{}).get('retry_after',3),
                           body.get('description','')) from None
        except (URLError,TimeoutError,OSError,HTTPException,ValueError):
            raise APIError(0) from None
        if not body.get('ok'):
            raise APIError(body.get('error_code',0),body.get('parameters',{}).get('retry_after',3),
                           body.get('description',''))
        return body['result']

    def call(self, method, payload=None):
        return self._request(method,json.dumps(payload or {},ensure_ascii=False).encode('utf-8'),
                             'application/json')

    def _pace(self, chat_id):
        delay=1.05-(time.monotonic()-self._last_sent.get(chat_id,0))
        if delay>0: time.sleep(delay)
        self._last_sent[chat_id]=time.monotonic()

    def _remember(self, response):
        if self.store and isinstance(response,dict) and response.get('message_id'):
            self.store.track_message(response['chat']['id'],response['message_id'],
                                     response.get('date',int(time.time())))
        return response

    def send(self, chat_id, text, markup=None):
        self._pace(chat_id)
        payload={'chat_id':chat_id,'text':text}
        if markup: payload['reply_markup']=markup
        return self._remember(self.call('sendMessage',payload))

    def edit(self, chat_id, message_id, text, markup):
        self._pace(chat_id)
        try:
            return self._remember(self.call('editMessageText',{
                'chat_id':chat_id,'message_id':message_id,'text':text,
                'reply_markup':markup or {'inline_keyboard':[]}}))
        except APIError as exc:
            if exc.code==400 and 'message is not modified' in exc.description.lower():
                return None
            raise

    def send_document(self, chat_id, document, text, markup):
        if len(document.content)>49*1024*1024:
            raise ValueError('File melebihi batas pengiriman bot. Ambil cadangan dari penyimpanan hosting atau pilih Excel per hari.')
        boundary='TelegramExpense'+uuid.uuid4().hex
        chunks=[]
        fields={'chat_id':str(chat_id),'caption':text[:1000],
                'reply_markup':json.dumps(markup,ensure_ascii=False)}
        for key,value in fields.items():
            chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                           f'{value}\r\n').encode('utf-8'))
        # Nama file berasal dari periode tervalidasi, bukan nama bebas dari pengguna.
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
                       f'filename="{document.filename}"\r\n'
                       f'Content-Type: {document.mime_type}'
                       '\r\n\r\n').encode('utf-8'))
        chunks.extend([document.content,f'\r\n--{boundary}--\r\n'.encode('ascii')])
        self._pace(chat_id)
        return self._remember(self._request('sendDocument',b''.join(chunks),
                                            f'multipart/form-data; boundary={boundary}'))


def clear_chat(api, store, chat_id, cutoff, now=None):
    ids=store.clear_candidates(chat_id,cutoff,int(time.time()) if now is None else now)
    for start in range(0,len(ids),100):
        batch=ids[start:start+100]
        try:
            api.call('deleteMessages',{'chat_id':chat_id,'message_ids':batch})
        except APIError as exc:
            if exc.code!=400: raise
            # Pesan khusus yang tidak boleh dihapus tidak menghalangi pesan lainnya.
            for mid in batch:
                try: api.call('deleteMessage',{'chat_id':chat_id,'message_id':mid})
                except APIError as individual:
                    if individual.code!=400: raise
        store.forget_messages(chat_id,batch)


def deliver(api, store, chat_id, reply, edit_id=None, backup_manager=None):
    if reply.backup_request:
        if not backup_manager or chat_id!=backup_manager.owner_id:
            api.send(chat_id,'Cadangan lengkap hanya dapat diakses pemilik bot.')
            return
        try:
            # Handler sudah menutup transaksi sebelum snapshot; hindari backup dalam BEGIN IMMEDIATE.
            file = backup_manager.manual(datetime.now(timezone.utc))
            if file.stat().st_size>49*1024*1024:
                api.send(chat_id,'Cadangan tersimpan, tetapi terlalu besar untuk dikirim. Ambil file dari folder backups pada hosting.')
                return
            document = Document(file.name,file.read_bytes(),'Cadangan lengkap bot pengeluaran.','application/vnd.sqlite3')
        except (OSError,sqlite3.Error,ValueError):
            api.send(chat_id,'Cadangan belum berhasil dibuat. Periksa ruang/izin penyimpanan, lalu coba kembali.')
            return
        api.send_document(chat_id,document,reply.text,reply.markup)
        return
    if reply.clear_cutoff is not None:
        clear_chat(api,store,chat_id,reply.clear_cutoff)
        edit_id=None
    if reply.document is not None:
        api.send_document(chat_id,reply.document,reply.text,reply.markup)
        return
    parts=split_text(reply.text)
    for index,part in enumerate(parts):
        markup=reply.markup if index==len(parts)-1 else None
        if index==0 and edit_id is not None:
            try:
                api.edit(chat_id,edit_id,part,markup)
                continue
            except APIError as exc:
                if exc.code!=400: raise
                # Pesan menu bisa telah dihapus manual; kirim menu pengganti.
        api.send(chat_id,part,markup)


def send_due_reminders(api, bot):
    """Pengingat opt-in per hari; keberhasilan disimpan agar restart tidak mengirim ulang."""
    for reminder in bot.store.due_reminders(int(bot.clock().timestamp())):
        uid=reminder['user_id']
        if uid not in bot.allowed_ids:
            continue
        now=bot.now(uid)
        today=now.date().isoformat()
        hour,minute=map(int,reminder['at_time'].split(':'))
        scheduled=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
        next_due=next_reminder_time(reminder['at_time'],now)
        if now<scheduled or reminder['last_sent_day']==today:
            bot.store.set_reminder(uid,reminder['at_time'],True,next_due)
            continue
        text=(f"🔔 PENGINGAT PENGELUARAN\n{now:%d-%m-%Y}, {reminder['at_time']} {now.tzname()}\n\n"
              'Sudah mencatat pengeluaran hari ini? Periksa catatanmu dan tambahkan yang belum dicatat.')
        try:
            api.send(uid,text,{'inline_keyboard':[
                [{'text':'➕ Catat','callback_data':'add'},{'text':'📅 Hari ini','callback_data':'today'}],
                [{'text':'Atur pengingat','callback_data':'reminder'}]]})
        except APIError as exc:
            if exc.code not in (400,403): raise
            bot.store.set_reminder(uid,reminder['at_time'],False,0)
            continue
        bot.store.finish_reminder(uid,today,next_due)


def run_polling(api, bot):
    offset=None
    while True:
        try:
            run_scheduled(api,bot)
            payload={'timeout':30,'allowed_updates':['message','callback_query']}
            if offset is not None: payload['offset']=offset
            for update in api.call('getUpdates',payload):
                message=update.get('message'); query=update.get('callback_query')
                reply=None; edit_id=None; chat_id=None
                if query:
                    uid=query.get('from',{}).get('id')
                    msg=query.get('message',{})
                    allowed=(uid in bot.allowed_ids and msg.get('chat',{}).get('type')=='private'
                             and msg.get('chat',{}).get('id')==uid)
                    try:
                        api.call('answerCallbackQuery',{'callback_query_id':query['id'],
                                 'text':'' if allowed else 'Akun ini belum diberi akses.'})
                    except APIError as exc:
                        if exc.code!=400: raise  # Query kedaluwarsa tetap aman untuk diproses ulang.
                    if allowed:
                        reply=bot.handle_callback(query)
                        chat_id=msg['chat']['id']; edit_id=msg['message_id']
                        bot.store.track_message(chat_id,edit_id,msg.get('date',int(time.time())))
                elif message:
                    uid=message.get('from',{}).get('id')
                    if message.get('chat',{}).get('type')=='private' and uid in bot.allowed_ids:
                        bot.store.track_message(message['chat']['id'],message['message_id'],message['date'])
                    reply=bot.handle(message)
                    chat_id=message.get('chat',{}).get('id')
                if reply:
                    try: deliver(api,bot.store,chat_id,reply,edit_id,bot.backups)
                    except APIError as exc:
                        if exc.code!=403: raise
                        print('Balasan tidak dikirim karena akses chat ditolak.')
                offset=update['update_id']+1
                run_scheduled(api,bot)
        except APIError as exc:
            if exc.code in (401,404):
                raise ValueError('Token ditolak Telegram. Periksa token dari BotFather.') from None
            if exc.code==409:
                raise ValueError('Bot berjalan di tempat lain atau masih memakai webhook. '
                                 'Hentikan proses lama sebelum menjalankan versi ini.') from None
            if exc.code==400:
                raise ValueError('Telegram menolak permintaan (400). Catatan yang sudah tersimpan tetap ada.') from None
            print('Koneksi sementara terganggu; bot akan mencoba kembali.')
            time.sleep(max(1,exc.retry_after))


def run_scheduled(api, bot):
    for uid in bot.allowed_ids:
        bot.store.budget(uid,bot.now(uid).strftime('%Y-%m'))
    if bot.backups:
        now = bot.now(bot.owner_id) if bot.owner_id else bot.clock().astimezone(bot.zone)
        bot.backups.ensure_daily(now)
    send_due_reminders(api,bot)
    send_scheduled_reports(api,bot)
    send_bill_reminders(api,bot)


def load_config(path: Path):
    try:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        data={}
    except (OSError,ValueError):
        raise ValueError('Format config.json tidak valid. Lihat README.html.') from None
    if not isinstance(data,dict):
        raise ValueError('config.json harus berisi objek JSON.')
    token=os.environ.get('TELEGRAM_BOT_TOKEN',data.get('bot_token',''))
    if not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',token.strip()):
        raise ValueError('Isi bot_token di config.json atau TELEGRAM_BOT_TOKEN pada hosting.')
    ids=data.get('allowed_user_ids',[])
    if 'ALLOWED_USER_IDS' in os.environ:
        raw=os.environ['ALLOWED_USER_IDS'].strip()
        if raw and not re.fullmatch(r'[0-9]+(?:\s*,\s*[0-9]+)*',raw):
            raise ValueError('ALLOWED_USER_IDS harus angka dipisahkan koma, contoh: 123456789,987654321.')
        ids=[int(part.strip()) for part in raw.split(',')] if raw else []
    if not isinstance(ids,list) or any(type(i) is not int or i<=0 for i in ids):
        raise ValueError('allowed_user_ids harus daftar angka, contoh: [123456789].')
    zone=os.environ.get('BOT_TIMEZONE',data.get('timezone','WIB'))
    if not isinstance(zone,str) or zone not in ZONES:
        raise ValueError('Zona waktu harus WIB, WITA, atau WIT.')
    name=os.environ.get('DB_PATH',data.get('database','data/pengeluaran.db'))
    if not isinstance(name,str) or not name.strip() or name==':memory:':
        raise ValueError('DB_PATH/database harus nama file database.')
    db_path=(path.resolve().parent/name).resolve()
    if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
        mount=os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
        if not mount or not db_path.is_relative_to(Path(mount).resolve()):
            raise ValueError('Pasang Volume Railway pada /data dan set DB_PATH=/data/pengeluaran.db.')
    db_path.parent.mkdir(parents=True,exist_ok=True)
    return token.strip(),set(ids),ZONES[zone],db_path


def load_owner(path, allowed):
    try: data=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError: data={}
    value=os.environ.get('OWNER_USER_ID',data.get('owner_user_id'))
    if value is None or value=='':
        return next(iter(allowed)) if len(allowed)==1 else None
    if isinstance(value,bool) or not re.fullmatch(r'[1-9][0-9]*',str(value)) or int(value) not in allowed:
        raise ValueError('OWNER_USER_ID/owner_user_id harus satu ID yang tercantum dalam daftar pengguna diizinkan.')
    return int(value)


def main():
    parser=argparse.ArgumentParser(description='Bot pengeluaran harian, bulanan, dan ekspor Excel.')
    parser.add_argument('--config',type=Path,default=ROOT/'config.json')
    args=parser.parse_args()
    store=None; lock=None
    def stop(_signal,_frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    try:
        token,allowed,zone,db_path=load_config(args.config)
        owner = load_owner(args.config,allowed)
        api=Telegram(token)
        account=api.call('getMe')
        if api.call('getWebhookInfo').get('url'):
            raise ValueError('Token masih memakai webhook. Lepaskan webhook pada layanan lama dahulu.')
        lock=RuntimeLock(db_path); lock.__enter__()
        backup_before_upgrade(db_path)
        store=Store(db_path); store.bind_bot(account['id']); api.store=store
        commands=[('start','Buka menu utama'),('menu','Ringkasan dan tombol fitur'),
                  ('catat','Tambah satu atau banyak pengeluaran'),('hariini','Lihat pengeluaran hari ini'),
                  ('bulanini','Lihat rekap bulan ini'),('excel','Unduh rekap Excel'),
                  ('hapus','Pilih pengeluaran untuk dihapus'),('pulihkan','Pulihkan pengeluaran'),
                  ('edit','Edit nominal keterangan kategori atau tanggal'),('anggaran','Atur anggaran bulanan'),
                  ('cari','Cari pengeluaran dan atur filter'),('pengingat','Atur pengingat harian'),
                  ('banding','Bandingkan pengeluaran antarbulan'),('batal','Batalkan input atau draf edit'),
                  ('clear','Bersihkan chat tanpa menghapus data'),('zona','Pilih WIB WITA atau WIT'),
                  ('harian','Laporan tanggal YYYY-MM-DD'),('bulanan','Laporan bulan YYYY-MM'),
                  ('id','ID akun Telegram'),('bantuan','Panduan singkat')]
        commands += [('riwayat','Catatan koreksi dan pilihan beberapa'),('laporan','Laporan dan ekspor Excel'),
                     ('pengaturan','Pengingat zona bantuan dan cadangan'),('riwayatedit','Riwayat perubahan dan urungkan edit'),
                     ('pilih','Pilih beberapa catatan sekaligus'),('cadangan','Cadangan lengkap khusus pemilik bot')]
        commands += [('kategoriotomatis','Atur kategori otomatis berdasarkan kata'),('favorit','Template pengeluaran favorit'),
                     ('rekapotomatis','Jadwal rekap mingguan dan bulanan'),('anggarankategori','Batas pengeluaran per kategori'),
                     ('tagihan','Pengingat dan pencatatan tagihan rutin')]
        commands += [('pemasukan','Catat pemasukan dan dompet penerima'),('saldo','Saldo dan arus kas bulanan'),
                     ('dompet','Dompet saldo awal dan sumber pembayaran'),('transfer','Pindahkan saldo antardompet')]
        api.call('setMyCommands',{'commands':[{'command':c,'description':d} for c,d in commands]})
        print(f"Bot @{account['username']} v2.4 aktif. Tekan Ctrl+C untuk berhenti.")
        if not allowed:
            print('Kirim /id ke bot, isi daftar ID pengguna di konfigurasi, lalu mulai ulang.')
        if len(allowed)>1 and owner is None:
            print('Isi OWNER_USER_ID/owner_user_id untuk mengaktifkan unduhan cadangan. Cadangan harian tetap berjalan.')
        run_polling(api,ExpenseBot(store,allowed,zone,owner_id=owner,backups=BackupManager(store,owner)))
    except KeyboardInterrupt:
        print('\nBot dihentikan. Catatan tetap tersimpan.')
    except APIError as exc:
        print(f'Gagal menghubungi Telegram (kode {exc.code}). Periksa internet dan token.')
        return 1
    except (ValueError,OSError,sqlite3.Error) as exc:
        print(f'Bot berhenti: {exc}')
        return 1
    finally:
        if store: store.close()
        if lock: lock.__exit__(None,None,None)
    return 0


if __name__=='__main__':
    sys.exit(main())
