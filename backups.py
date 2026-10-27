"""Snapshot SQLite, cadangan harian, dan pemulihan saat bot dihentikan."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

from core import Store, ZONES, read_day, month_range
from storage_v22 import EDIT_FIELDS
from storage_v23 import V23_TABLES, V23_SEQUENCES, validate_v23
from storage_v24 import V24_TABLES, V24_SEQUENCES, validate_v24


class RuntimeLock:
    """Kunci OS dilepas otomatis jika proses mati; file kunci boleh tetap ada."""
    def __init__(self, database):
        self.path = Path(str(Path(database).resolve())+'.lock')
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file = self.path.open('a+b')
        if self.path.stat().st_size==0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            raise ValueError('Database sedang digunakan. Hentikan bot sebelum menjalankan bot lain atau pemulihan.') from None
        return self

    def __exit__(self, *args):
        if self.file:
            try:
                self.file.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            finally:
                self.file.close(); self.file = None


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA trusted_schema=OFF')
    return db


def check_integrity(db):
    rows = db.execute('PRAGMA integrity_check').fetchall()
    if len(rows)!=1 or rows[0][0]!='ok':
        raise ValueError('Database gagal pemeriksaan integritas. File tujuan belum diubah.')


def snapshot_database(db, target):
    if db.in_transaction:
        raise ValueError('Cadangan hanya boleh dibuat setelah transaksi database selesai.')
    target = Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,name = tempfile.mkstemp(prefix='.snapshot-',suffix='.db',dir=target.parent)
    os.close(fd)
    temp = Path(name)
    deadline = time.monotonic()+30
    def progress(status, remaining, total):
        if time.monotonic()>deadline:
            raise ValueError('Cadangan belum selesai dalam 30 detik. Coba kembali saat database tidak sibuk.')
    try:
        with closing(sqlite3.connect(temp)) as dest:
            db.backup(dest,pages=256,progress=progress,sleep=0.05)
            dest.execute('PRAGMA journal_mode=DELETE')
            check_integrity(dest)
        with temp.open('r+b') as stream: os.fsync(stream.fileno())
        os.replace(temp,target)
        return target
    finally:
        temp.unlink(missing_ok=True)


def backup_before_upgrade(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size==0: return None
    with closing(readonly(path)) as db:
        has_meta = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
        version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone() if has_meta else None
        if version and version[0]=='2.4': return None
        tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        return snapshot_database(db,path.parent/'backups'/path.stem/f'before-v2.4-{tag}.db')


class BackupManager:
    def __init__(self, store, owner_id=None):
        self.store,self.owner_id = store,owner_id
        path = Path(store.path).resolve()
        self.folder = path.parent/'backups'/path.stem
        self.last_slot = None
        self.last_error = None
        self.retry_at = 0

    def latest(self):
        files = list(self.folder.glob('auto-????-??-??.db')) if self.folder.exists() else []
        return max(files,key=lambda p:p.name) if files else None

    def ensure_daily(self, now):
        slot = (now.date() if now.hour>=3 else now.date()-timedelta(days=1)).isoformat()
        target = self.folder/f'auto-{slot}.db'
        if self.last_slot==slot and target.exists(): return None
        if int(now.timestamp())<self.retry_at: return None
        try:
            if target.exists():
                try:
                    with closing(readonly(target)) as db: check_integrity(db)
                except (sqlite3.Error,ValueError):
                    os.replace(target,target.with_suffix('.invalid-'+uuid.uuid4().hex[:8]))
                    snapshot_database(self.store.db,target)
            else: snapshot_database(self.store.db,target)
            files = sorted(self.folder.glob('auto-????-??-??.db'),key=lambda p:p.name,reverse=True)
            for old in files[14:]: old.unlink()
            self.last_slot,self.last_error = slot,None
            return target
        except (OSError,sqlite3.Error,ValueError) as exc:
            self.last_error = str(exc)
            self.retry_at = int(now.timestamp())+300
            print('Cadangan harian gagal; akan dicoba lagi dalam 5 menit. Periksa ruang dan izin folder cadangan.')
            return None

    def manual(self, now):
        name = f"manual-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.db"
        return snapshot_database(self.store.db,self.folder/name)


PERSISTENT_TABLES = ('metadata','preferences','expenses','budgets','budget_rules',
                     'reminders','search_filters','expense_changes')+V23_TABLES+V24_TABLES
TRANSIENT_TABLES = ('chat_messages','callback_actions','pending_inputs','event_receipts')


def _values_valid(values):
    if not isinstance(values,dict) or set(values) not in (set(EDIT_FIELDS),set(EDIT_FIELDS+('wallet_id',))):
        raise ValueError('Nilai riwayat edit tidak valid.')
    if type(values['amount']) is not int or not 1<=values['amount']<=1000000000000:
        raise ValueError('Nominal dalam cadangan tidak valid.')
    for key,limit in [('note',160),('category',32)]:
        if not isinstance(values[key],str) or not 1<=len(values[key])<=limit:
            raise ValueError('Keterangan/kategori dalam cadangan tidak valid.')
    read_day(values['spent_on'])


def _valid_stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None: raise ValueError('Zona waktu catatan dalam cadangan tidak valid.')


def validate_data(store):
    """Periksa data di tabel kanonis, bukan menjalankan skema dari file unggahan."""
    for table in PERSISTENT_TABLES[1:]:
        for r in store.db.execute(f'SELECT * FROM {table}'):
            if type(r['user_id']) is not int or r['user_id']<=0: raise ValueError('ID pengguna tidak valid.')
            if table=='expenses':
                _values_valid({k:r[k] for k in EDIT_FIELDS}); _valid_stamp(r['created_at'])
                if r['chat_id']!=r['user_id'] or r['id']<=0 or r['message_id']<0 or r['line_no']<0 or r['revision']<0:
                    raise ValueError('Identitas catatan dalam cadangan tidak valid.')
            elif table=='preferences' and r['zone'] not in ZONES: raise ValueError('Zona cadangan tidak dikenal.')
            elif table in ('budgets','budget_rules'):
                month_range(r['month'] if table=='budgets' else r['effective_from'])
                if r['amount'] is not None and (type(r['amount']) is not int or not 1<=r['amount']<=1000000000000):
                    raise ValueError('Anggaran dalam cadangan tidak valid.')
                if table=='budgets' and (r['source'] not in ('auto','manual') or r['alert_level'] not in (0,80,100)):
                    raise ValueError('Pengaturan anggaran tidak valid.')
            elif table=='reminders':
                if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',r['at_time']) or r['enabled'] not in (0,1) or r['next_due']<0:
                    raise ValueError('Pengingat dalam cadangan tidak valid.')
                if r['last_sent_day']: read_day(r['last_sent_day'])
            elif table=='search_filters':
                data = json.loads(r['data'])
                if not isinstance(data,dict) or set(data)!={'keyword','category','start','end'}:
                    raise ValueError('Filter pencarian tidak valid.')
                if not isinstance(data['keyword'],str) or len(data['keyword'])>160:
                    raise ValueError('Kata pencarian tidak valid.')
                if data['category'] is not None and (not isinstance(data['category'],str) or not 1<=len(data['category'])<=32):
                    raise ValueError('Kategori pencarian tidak valid.')
                for key in ('start','end'):
                    if data[key] is not None: read_day(data[key])
            elif table=='expense_changes':
                before,after = json.loads(r['before_json']),json.loads(r['after_json'])
                _values_valid(before); _values_valid(after); _valid_stamp(r['changed_at'])
                row = store.get(r['user_id'],r['record_id'])
                if not row or r['result_revision']<=0 or r['result_revision']>row['revision'] or r['kind'] not in ('edit','bulk_category','undo'):
                    raise ValueError('Hubungan riwayat edit tidak valid.')
                if r['undone_by'] is not None:
                    undo = store.change(r['user_id'],r['undone_by'])
                    if not undo or undo['kind']!='undo' or undo['record_id']!=r['record_id']:
                        raise ValueError('Hubungan urungkan edit tidak valid.')
    validate_v23(store)
    validate_v24(store)
    bot = store.db.execute("SELECT value FROM metadata WHERE key='bot_id'").fetchone()
    if bot and not re.fullmatch(r'[1-9][0-9]*',bot[0]): raise ValueError('Identitas bot di cadangan tidak valid.')
    return bot[0] if bot else None


def prepare_restore(source, staging):
    """Salin data ke skema baru; file sumber tidak pernah diubah."""
    source = Path(source).resolve()
    if not source.is_file(): raise ValueError('File cadangan tidak ditemukan.')
    with source.open('rb') as file:
        if file.read(16)!=b'SQLite format 3\x00': raise ValueError('Pilih cadangan database .db, bukan laporan Excel atau ZIP.')
    with closing(readonly(source)) as db:
        check_integrity(db)
        schema = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {r['name'] for r in schema if r['type']=='table'}
        allowed = set(PERSISTENT_TABLES+TRANSIENT_TABLES)
        if 'expenses' not in tables or tables-allowed or any(r['type'] in ('view','trigger') or
                (r['sql'] and 'VIRTUAL TABLE' in r['sql'].upper()) for r in schema):
            raise ValueError('Skema file tidak cocok dengan bot pengeluaran.')
        dest = Store(staging)
        try:
            with dest.transaction():
                for table in PERSISTENT_TABLES:
                    dest.db.execute(f'DELETE FROM {table}')
                    if table not in tables: continue
                    src_cols = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                    columns = [r[1] for r in dest.db.execute(f'PRAGMA table_info({table})')]
                    legacy = {'expenses':{'line_no','revision','wallet_id'},'budgets':{'source'},
                              'favorites':{'wallet_id'},'bills':{'wallet_id'}}.get(table,set())
                    if src_cols-set(columns) or set(columns)-src_cols-legacy:
                        raise ValueError('Versi/skema cadangan tidak didukung. Gunakan versi bot yang sesuai.')
                    cols = [c for c in columns if c in src_cols]
                    names = ','.join(cols)
                    sql = f"INSERT INTO {table}({names}) VALUES({','.join('?' for c in cols)})"
                    for row in db.execute(f'SELECT {names} FROM {table}'):
                        dest.db.execute(sql,tuple(row))
                if 'wallet_id' not in {r[1] for r in db.execute('PRAGMA table_info(expenses)')}:
                    dest.migrate_expense_wallets()
                bot_id = validate_data(dest)
                # Hindari menghidupkan tombol/draf lama setelah kembali ke snapshot sebelumnya.
                dest.db.execute("INSERT OR REPLACE INTO metadata VALUES('messages_seeded','1')")
                dest.db.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','2.4')")
                # Pertahankan penghitung ID, termasuk ID yang sudah tidak dipakai.
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                    for row in db.execute('SELECT name,seq FROM sqlite_sequence'):
                        if row[0] not in ('expenses','expense_changes')+V23_SEQUENCES+V24_SEQUENCES: continue
                        current = dest.db.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(row[0],)).fetchone()
                        if type(row[1]) is not int or row[1]<0: raise ValueError('Penghitung ID tidak valid.')
                        if not current: dest.db.execute('INSERT INTO sqlite_sequence VALUES(?,?)',tuple(row))
                        elif row[1]>current[0]: dest.db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?',(row[1],row[0]))
            check_integrity(dest.db)
            return {'active':dest.db.execute('SELECT COUNT(*) FROM expenses WHERE deleted=0').fetchone()[0],
                    'deleted':dest.db.execute('SELECT COUNT(*) FROM expenses WHERE deleted=1').fetchone()[0],
                    'changes':dest.db.execute('SELECT COUNT(*) FROM expense_changes').fetchone()[0],
                    'users':dest.db.execute('SELECT COUNT(*) FROM (SELECT user_id FROM expenses UNION SELECT user_id FROM wallets UNION SELECT user_id FROM money_entries)').fetchone()[0],
                    'incomes':dest.db.execute("SELECT COUNT(*) FROM money_entries WHERE kind='income' AND deleted=0").fetchone()[0],
                    'transfers':dest.db.execute("SELECT COUNT(*) FROM money_entries WHERE kind='transfer' AND deleted=0").fetchone()[0],
                    'wallets':dest.db.execute('SELECT COUNT(*) FROM wallets').fetchone()[0],
                    'bot_id':bot_id}
        finally: dest.close()


def restore_database(source, target, confirm):
    """Konfirmasi ringkasan wajib; cadangan pra-pemulihan selesai sebelum penggantian."""
    source,target = Path(source).resolve(),Path(target).resolve()
    if source==target: raise ValueError('File cadangan dan database tujuan harus berbeda.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with RuntimeLock(target):
        fd,name = tempfile.mkstemp(prefix='.restore-',suffix='.db',dir=target.parent)
        os.close(fd); staging = Path(name)
        moved = []
        try:
            summary = prepare_restore(source,staging)
            old_bot_id = None
            if target.exists():
                try:
                    with closing(readonly(target)) as old:
                        row = old.execute("SELECT value FROM metadata WHERE key='bot_id'").fetchone()
                        old_bot_id = row[0] if row else None
                except sqlite3.Error: pass  # Database rusak tetap bisa diganti setelah salinan mentah dibuat.
            if old_bot_id and summary['bot_id']!=old_bot_id:
                raise ValueError('Cadangan berasal dari bot berbeda. Database tujuan belum diubah.')
            if not confirm(summary): return None
            recovery = None
            if target.exists():
                folder = target.parent/'backups'/target.stem
                folder.mkdir(parents=True,exist_ok=True)
                tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
                recovery = folder/('before-restore-'+tag+'.db')
                try:
                    with closing(readonly(target)) as old: snapshot_database(old,recovery)
                except (sqlite3.Error,ValueError):
                    # Bila database rusak, simpan byte asli dan semua jurnal untuk pemeriksaan berikutnya.
                    shutil.copy2(target,recovery)
                    for suffix in ('-wal','-shm','-journal'):
                        sidecar = Path(str(target)+suffix)
                        if sidecar.exists(): shutil.copy2(sidecar,Path(str(recovery)+suffix))
            # Jurnal milik database lama tidak boleh diterapkan ke database hasil pemulihan.
            for suffix in ('-wal','-shm','-journal'):
                sidecar = Path(str(target)+suffix)
                if sidecar.exists():
                    saved = Path(str(staging)+suffix+'.old')
                    os.replace(sidecar,saved); moved.append((sidecar,saved))
            with staging.open('r+b') as stream: os.fsync(stream.fileno())
            try: os.replace(staging,target)
            except BaseException:
                for sidecar,saved in moved: os.replace(saved,sidecar)
                moved.clear()
                raise
            # Setelah commit, jurnal lama tidak boleh dikembalikan meskipun pembersihan gagal.
            obsolete = moved
            moved = []
            for _,saved in obsolete:
                try: saved.unlink(missing_ok=True)
                except OSError: pass  # Tetap bernama *.old; SQLite tidak akan membacanya.
            return {'summary':summary,'previous':recovery,'target':target}
        finally:
            for sidecar,saved in moved:
                if saved.exists(): os.replace(saved,sidecar)
            staging.unlink(missing_ok=True)
            for suffix in ('-wal','-shm','-journal'): Path(str(staging)+suffix).unlink(missing_ok=True)
