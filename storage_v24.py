"""Dompet dan buku kas: saldo selalu dihitung dari transaksi aktif, bukan cache."""
import json
import re
from datetime import date, datetime

from storage_v23 import RoutineStore
from storage_v22 import EDIT_FIELDS

V24_TABLES = ('wallets', 'wallet_settings', 'money_entries')
V24_SEQUENCES = ('wallets', 'money_entries')
MONEY_FIELDS = ('kind', 'wallet_id', 'to_wallet_id', 'amount', 'note', 'category', 'occurred_on')


def wallet_name(value):
    if not isinstance(value, str): raise ValueError('Nama dompet wajib diisi.')
    value = ' '.join(value.split())
    if not 1 <= len(value) <= 32 or '|' in value:
        raise ValueError('Nama dompet wajib 1–32 karakter dan tidak boleh mengandung |.')
    return value


class WalletStore(RoutineStore):
    def initialize_v24(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                name TEXT NOT NULL, name_key TEXT NOT NULL, opening_balance INTEGER,
                revision INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,name_key),
                CHECK(opening_balance IS NULL OR opening_balance>=0));
            CREATE TABLE IF NOT EXISTS wallet_settings (
                user_id INTEGER PRIMARY KEY, default_wallet_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS money_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                source_key TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('income','transfer')),
                wallet_id INTEGER NOT NULL, to_wallet_id INTEGER,
                amount INTEGER NOT NULL CHECK(amount>0), note TEXT NOT NULL, category TEXT NOT NULL,
                occurred_on TEXT NOT NULL, created_at TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)),
                revision INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,source_key));
            CREATE INDEX IF NOT EXISTS money_by_user_date ON money_entries(user_id,occurred_on,deleted);
        ''')
        if 'wallet_id' not in {r[1] for r in self.db.execute('PRAGMA table_info(expenses)')}:
            self.db.execute('ALTER TABLE expenses ADD COLUMN wallet_id INTEGER')
            self.db.commit()
        for table in ('favorites','bills'):
            if 'wallet_id' not in {r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}:
                self.db.execute('ALTER TABLE '+table+' ADD COLUMN wallet_id INTEGER')
                self.db.commit()
        self.migrate_expense_wallets()

    def migrate_expense_wallets(self):
        with self.transaction():
            users = [r[0] for r in self.db.execute('SELECT DISTINCT user_id FROM expenses WHERE wallet_id IS NULL')]
            for uid in users:
                wid = self.default_wallet(uid)['id']
                self.db.execute('UPDATE expenses SET wallet_id=? WHERE user_id=? AND wallet_id IS NULL', (wid,uid))

    def wallet(self, uid, wid):
        row = self.db.execute('SELECT * FROM wallets WHERE user_id=? AND id=?', (uid,wid)).fetchone()
        if row is None: raise ValueError('Dompet tidak ditemukan di akunmu.')
        return row

    def wallets(self, uid):
        self.default_wallet(uid)
        return self.db.execute('SELECT * FROM wallets WHERE user_id=? ORDER BY id', (uid,)).fetchall()

    def default_wallet(self, uid):
        row = self.db.execute('SELECT default_wallet_id FROM wallet_settings WHERE user_id=?', (uid,)).fetchone()
        if row: return self.wallet(uid,row[0])
        with self.transaction():
            first = self.db.execute('SELECT * FROM wallets WHERE user_id=? ORDER BY id LIMIT 1', (uid,)).fetchone()
            if first is None:
                wid = self.db.execute("INSERT INTO wallets(user_id,name,name_key) VALUES(?,'Umum','umum')", (uid,)).lastrowid
            else: wid = first['id']
            self.db.execute('INSERT INTO wallet_settings VALUES(?,?)', (uid,wid))
            return self.wallet(uid,wid)

    def resolve_wallet(self, uid, name=None):
        if name is None: return self.default_wallet(uid)['id']
        name = wallet_name(name)
        row = self.db.execute('SELECT id FROM wallets WHERE user_id=? AND name_key=?', (uid,name.casefold())).fetchone()
        if row is None: raise ValueError(f'Dompet “{name}” belum ada. Buat melalui /dompet, lalu kirim ulang.')
        return row[0]

    def create_wallet(self, uid, name):
        name = wallet_name(name)
        with self.transaction():
            self.default_wallet(uid)
            if self.db.execute('SELECT COUNT(*) FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]>=20:
                raise ValueError('Maksimal 20 dompet per akun. Gunakan atau ganti nama dompet yang sudah ada.')
            if self.db.execute('SELECT 1 FROM wallets WHERE user_id=? AND name_key=?',(uid,name.casefold())).fetchone():
                raise ValueError('Nama dompet sudah digunakan.')
            wid = self.db.execute('INSERT INTO wallets(user_id,name,name_key) VALUES(?,?,?)',(uid,name,name.casefold())).lastrowid
            return self.wallet(uid,wid)

    def update_wallet(self, uid, wid, revision, *, name=None, opening=None):
        with self.transaction():
            row = self.wallet(uid,wid)
            if row['revision']!=revision: raise ValueError('Dompet sudah berubah. Buka kembali dan konfirmasi ulang.')
            if name is not None:
                name = wallet_name(name)
                if self.db.execute('SELECT 1 FROM wallets WHERE user_id=? AND name_key=? AND id<>?',(uid,name.casefold(),wid)).fetchone():
                    raise ValueError('Nama dompet sudah digunakan.')
                self.db.execute('UPDATE wallets SET name=?,name_key=?,revision=revision+1 WHERE user_id=? AND id=?',(name,name.casefold(),uid,wid))
            if opening is not None:
                if type(opening) is not int or not 0<=opening<=1000000000000: raise ValueError('Saldo awal harus Rp0–Rp1.000.000.000.000.')
                self.db.execute('UPDATE wallets SET opening_balance=?,revision=revision+1 WHERE user_id=? AND id=?',(opening,uid,wid))
            return self.wallet(uid,wid)

    def set_default_wallet(self, uid, wid):
        self.wallet(uid,wid)
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO wallet_settings VALUES(?,?)',(uid,wid))

    def add_confirmed(self, uid, values, source_key, when):
        with self.transaction():
            previous = self.source_expense(uid,source_key)
            if previous: return previous,False
            wid = values.get('wallet_id') or self.default_wallet(uid)['id']
            self.wallet(uid,wid)
            row,added = super().add_confirmed(uid,values,source_key,when)
            if added: self.db.execute('UPDATE expenses SET wallet_id=? WHERE id=? AND user_id=?',(wid,row['id'],uid))
            return self.get(uid,row['id']),added

    def save_favorite(self, uid, values, rid=None, revision=None):
        with self.transaction():
            wid=values.get('wallet_id')
            if wid is not None: self.wallet(uid,wid)
            rid=super().save_favorite(uid,values,rid,revision)
            self.db.execute('UPDATE favorites SET wallet_id=? WHERE user_id=? AND id=?',(wid,uid,rid))
            return rid

    def save_bill(self, uid, values, rid=None, revision=None):
        with self.transaction():
            wid=values.get('wallet_id')
            if wid is not None: self.wallet(uid,wid)
            rid=super().save_bill(uid,values,rid,revision)
            self.db.execute('UPDATE bills SET wallet_id=? WHERE user_id=? AND id=?',(wid,uid,rid))
            return rid

    def _change(self, uid, row, values, when, kind):
        # Riwayat versi lama hanya memiliki empat kolom; undo lama mempertahankan dompet saat ini.
        before = {key:row[key] for key in EDIT_FIELDS+('wallet_id',)}
        after = {key:values[key] for key in EDIT_FIELDS}
        after['wallet_id'] = values.get('wallet_id',row['wallet_id'])
        self.wallet(uid,after['wallet_id'])
        if before==after: return None
        self.db.execute('''UPDATE expenses SET amount=?,note=?,category=?,spent_on=?,wallet_id=?,revision=revision+1
            WHERE user_id=? AND id=?''',(*[after[k] for k in EDIT_FIELDS+('wallet_id',)],uid,row['id']))
        return self.db.execute('''INSERT INTO expense_changes
            (user_id,record_id,changed_at,kind,before_json,after_json,result_revision) VALUES(?,?,?,?,?,?,?)''',
            (uid,row['id'],when,kind,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),row['revision']+1)).lastrowid

    def validate_money(self, uid, values):
        from core import read_day
        if set(values)!=set(MONEY_FIELDS): raise ValueError('Isian transaksi belum lengkap.')
        if values['kind'] not in ('income','transfer'): raise ValueError('Jenis transaksi tidak dikenal.')
        self.wallet(uid,values['wallet_id'])
        if values['kind']=='transfer':
            self.wallet(uid,values['to_wallet_id'])
            if values['wallet_id']==values['to_wallet_id']: raise ValueError('Dompet asal dan tujuan harus berbeda.')
        elif values['to_wallet_id'] is not None: raise ValueError('Pemasukan hanya memiliki satu dompet penerima.')
        if type(values['amount']) is not int or not 1<=values['amount']<=1000000000000: raise ValueError('Nominal tidak valid.')
        for key,limit in (('note',160),('category',32)):
            if not isinstance(values[key],str) or not 1<=len(values[key])<=limit: raise ValueError('Keterangan/kategori tidak valid.')
        read_day(values['occurred_on'])

    def money_entry(self, uid, rid):
        row = self.db.execute('SELECT * FROM money_entries WHERE user_id=? AND id=?',(uid,rid)).fetchone()
        if row is None: raise ValueError('Transaksi tidak ditemukan di akunmu.')
        return row

    def save_money(self, uid, values, source_key, when, rid=None, revision=None):
        with self.transaction():
            self.validate_money(uid,values)
            if rid is None:
                previous = self.db.execute('SELECT * FROM money_entries WHERE user_id=? AND source_key=?',(uid,source_key)).fetchone()
                if previous: return previous,False
                rid = self.db.execute('''INSERT INTO money_entries
                    (user_id,source_key,kind,wallet_id,to_wallet_id,amount,note,category,occurred_on,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',(uid,source_key,*[values[k] for k in MONEY_FIELDS],when)).lastrowid
            else:
                row = self.money_entry(uid,rid)
                if row['deleted'] or row['revision']!=revision or row['kind']!=values['kind']:
                    raise ValueError('Transaksi sudah berubah atau dihapus. Buka kembali dari riwayat.')
                self.db.execute('''UPDATE money_entries SET kind=?,wallet_id=?,to_wallet_id=?,amount=?,note=?,category=?,
                    occurred_on=?,revision=revision+1 WHERE user_id=? AND id=?''',(*[values[k] for k in MONEY_FIELDS],uid,rid))
            return self.money_entry(uid,rid),True

    def set_money_deleted(self, uid, rid, revision, deleted):
        with self.transaction():
            row = self.money_entry(uid,rid)
            if row['revision']!=revision or bool(row['deleted'])==deleted:
                raise ValueError('Transaksi sudah berubah. Muat ulang daftar.')
            self.db.execute('UPDATE money_entries SET deleted=?,revision=revision+1 WHERE user_id=? AND id=?',(int(deleted),uid,rid))
            return self.money_entry(uid,rid)

    def money_rows(self, uid, kind=None, start=None, end=None, deleted=False):
        sql,args = 'SELECT * FROM money_entries WHERE user_id=? AND deleted=?',[uid,int(deleted)]
        if kind is not None:
            if kind not in ('income','transfer'): raise ValueError('Jenis transaksi tidak dikenal.')
            sql+=' AND kind=?'; args.append(kind)
        if start is not None: sql+=' AND occurred_on>=?'; args.append(str(start))
        if end is not None: sql+=' AND occurred_on<?'; args.append(str(end))
        return self.db.execute(sql+' ORDER BY occurred_on DESC,id DESC',args).fetchall()

    def wallet_totals(self, uid, wid, end=None):
        row = self.wallet(uid,wid)
        args = [uid,wid]; until = ''
        if end is not None: until=' AND spent_on<?'; args.append(str(end))
        spent = self.db.execute('SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=? AND wallet_id=? AND deleted=0'+until,args).fetchone()[0]
        entries = self.money_rows(uid,end=end)
        income = sum(r['amount'] for r in entries if r['kind']=='income' and r['wallet_id']==wid)
        outgoing = sum(r['amount'] for r in entries if r['kind']=='transfer' and r['wallet_id']==wid)
        incoming = sum(r['amount'] for r in entries if r['kind']=='transfer' and r['to_wallet_id']==wid)
        opening = row['opening_balance'] or 0
        return dict(opening=opening,income=income,expense=spent,transfer_in=incoming,transfer_out=outgoing,
                    balance=opening+income-spent+incoming-outgoing,configured=row['opening_balance'] is not None)

    def cash_period(self, uid, start, end):
        wallets = self.wallets(uid)
        beginning = sum(self.wallet_totals(uid,w['id'],start)['balance'] for w in wallets)
        income = sum(r['amount'] for r in self.money_rows(uid,'income',start,end))
        expense = sum(r['amount'] for r in self.rows(uid,start,end))
        return dict(beginning=beginning,income=income,expense=expense,balance=beginning+income-expense,
                    configured=all(w['opening_balance'] is not None for w in wallets))


def validate_v24(store):
    from core import read_day
    for row in store.db.execute('SELECT * FROM wallets'):
        if row['id']<=0 or row['revision']<0 or wallet_name(row['name'])!=row['name'] or row['name_key']!=row['name'].casefold():
            raise ValueError('Dompet dalam cadangan tidak valid.')
        opening=row['opening_balance']
        if opening is not None and (type(opening) is not int or not 0<=opening<=1000000000000):
            raise ValueError('Saldo awal dalam cadangan tidak valid.')
    if store.db.execute('SELECT 1 FROM wallets GROUP BY user_id HAVING COUNT(*)>20').fetchone():
        raise ValueError('Jumlah dompet melebihi batas.')
    for row in store.db.execute('SELECT * FROM wallet_settings'): store.wallet(row['user_id'],row['default_wallet_id'])
    for row in store.db.execute('SELECT * FROM expenses'): store.wallet(row['user_id'],row['wallet_id'])
    for table in ('favorites','bills'):
        for row in store.db.execute('SELECT * FROM '+table):
            if row['wallet_id'] is not None: store.wallet(row['user_id'],row['wallet_id'])
    for row in store.db.execute('SELECT * FROM expense_changes'):
        for key in ('before_json','after_json'):
            values=json.loads(row[key])
            if 'wallet_id' in values: store.wallet(row['user_id'],values['wallet_id'])
    for row in store.db.execute('SELECT * FROM money_entries'):
        store.validate_money(row['user_id'],{k:row[k] for k in MONEY_FIELDS})
        if row['id']<=0 or row['revision']<0 or row['deleted'] not in (0,1) or not re.fullmatch(r'money:[0-9a-f]{12}',row['source_key']):
            raise ValueError('Identitas transaksi kas tidak valid.')
        if datetime.fromisoformat(row['created_at']).tzinfo is None: raise ValueError('Waktu transaksi kas tidak valid.')
