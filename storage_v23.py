"""Aturan pribadi, favorit, anggaran kategori, dan status pengiriman versi 2.3."""
import json
import re
from storage_v22 import AdvancedStore

DEFAULT_RULES = [('bensin','Transportasi'),('ojek','Transportasi'),('parkir','Transportasi'),
                 ('makan','Makanan'),('minum','Makanan')]
V23_TABLES = ('category_settings','category_rules','favorites','expense_sources','category_budgets',
              'report_settings','report_jobs','bills','bill_cycles')
V23_SEQUENCES = ('category_rules','favorites','category_budgets','bills')


class RoutineStore(AdvancedStore):
    def initialize_v23(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS category_settings (
                user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)));
            CREATE TABLE IF NOT EXISTS category_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL, category TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id,keyword));
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount>0), note TEXT NOT NULL, category TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS expense_sources (
                user_id INTEGER NOT NULL, source_key TEXT NOT NULL, record_id INTEGER NOT NULL UNIQUE,
                PRIMARY KEY(user_id,source_key));
            CREATE TABLE IF NOT EXISTS category_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, month TEXT NOT NULL,
                category TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0),
                alert_level INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,month,category));
            CREATE TABLE IF NOT EXISTS report_settings (
                user_id INTEGER NOT NULL, kind TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
                at_time TEXT NOT NULL DEFAULT '07:00', with_excel INTEGER NOT NULL DEFAULT 0 CHECK(with_excel IN (0,1)),
                activated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS report_jobs (
                user_id INTEGER NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL,
                start_on TEXT NOT NULL, end_on TEXT NOT NULL, reply TEXT NOT NULL,
                excel BLOB, text_sent INTEGER NOT NULL DEFAULT 0 CHECK(text_sent IN (0,1)),
                doc_sent INTEGER NOT NULL DEFAULT 0 CHECK(doc_sent IN (0,1)),
                completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
                created_at INTEGER NOT NULL, PRIMARY KEY(user_id,kind,period));
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
                amount INTEGER NOT NULL CHECK(amount>0), note TEXT NOT NULL, category TEXT NOT NULL,
                day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 31),
                at_time TEXT NOT NULL, start_month TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS bill_cycles (
                user_id INTEGER NOT NULL, bill_id INTEGER NOT NULL, period TEXT NOT NULL,
                due_on TEXT NOT NULL, reminded_at INTEGER, expense_id INTEGER,
                PRIMARY KEY(user_id,bill_id,period));
        ''')

    def rule_settings(self, uid):
        row = self.db.execute('SELECT * FROM category_settings WHERE user_id=?',(uid,)).fetchone()
        if row is None:
            with self.transaction():
                self.db.execute('INSERT OR IGNORE INTO category_settings VALUES(?,1)',(uid,))
                self.db.executemany('INSERT OR IGNORE INTO category_rules(user_id,keyword,category) VALUES(?,?,?)',
                                    [(uid,k,c) for k,c in DEFAULT_RULES])
            row = self.db.execute('SELECT * FROM category_settings WHERE user_id=?',(uid,)).fetchone()
        return row

    def toggle_rules(self, uid, enabled):
        self.rule_settings(uid)
        with self.transaction():
            self.db.execute('UPDATE category_settings SET enabled=? WHERE user_id=?',(int(enabled),uid))

    def rules(self, uid):
        self.rule_settings(uid)
        return self.db.execute('SELECT * FROM category_rules WHERE user_id=? ORDER BY id',(uid,)).fetchall()

    def owned(self, table, uid, rid):
        if table not in ('category_rules','favorites','category_budgets','bills'):
            raise ValueError('Jenis data tidak dikenal.')
        return self.db.execute(f'SELECT * FROM {table} WHERE user_id=? AND id=?',(uid,rid)).fetchone()

    def save_rule(self, uid, keyword, category, rid=None, revision=None):
        keyword = ' '.join(keyword.casefold().split())
        if not 1<=len(keyword)<=40 or not 1<=len(category)<=32: raise ValueError('Kata maksimal 40 dan kategori 32 karakter.')
        with self.transaction():
            self.rule_settings(uid)
            duplicate = self.db.execute('SELECT id FROM category_rules WHERE user_id=? AND keyword=?',(uid,keyword)).fetchone()
            if duplicate and duplicate['id']!=rid: raise ValueError('Kata itu sudah memiliki aturan. Edit aturan yang tersedia.')
            if rid is None:
                if len(self.rules(uid))>=50: raise ValueError('Maksimal 50 aturan. Hapus aturan yang tidak dipakai.')
                return self.db.execute('INSERT INTO category_rules(user_id,keyword,category) VALUES(?,?,?)',
                                       (uid,keyword,category)).lastrowid
            changed = self.db.execute('UPDATE category_rules SET keyword=?,category=?,revision=revision+1 WHERE user_id=? AND id=? AND revision=?',
                                     (keyword,category,uid,rid,revision))
            if changed.rowcount!=1: raise ValueError('Aturan sudah berubah. Buka kembali daftar aturan.')
            return rid

    def automatic_category(self, uid, note):
        if not self.rule_settings(uid)['enabled']: return 'Lainnya'
        normalized = ' '.join(note.casefold().split())
        for rule in sorted(self.rules(uid),key=lambda r:(-len(r['keyword']),r['id'])):
            if re.search(r'(?<!\w)'+re.escape(rule['keyword'])+r'(?!\w)',normalized): return rule['category']
        return 'Lainnya'

    def favorite_rows(self, uid):
        return self.db.execute('SELECT * FROM favorites WHERE user_id=? ORDER BY id',(uid,)).fetchall()

    def save_favorite(self, uid, values, rid=None, revision=None):
        with self.transaction():
            args = (values['title'],values['amount'],values['note'],values['category'])
            if rid is None:
                if len(self.favorite_rows(uid))>=30: raise ValueError('Maksimal 30 favorit. Hapus yang tidak dipakai.')
                return self.db.execute('INSERT INTO favorites(title,amount,note,category,user_id) VALUES(?,?,?,?,?)',(*args,uid)).lastrowid
            changed = self.db.execute('UPDATE favorites SET title=?,amount=?,note=?,category=?,revision=revision+1 WHERE user_id=? AND id=? AND revision=?',
                                     (*args,uid,rid,revision))
            if changed.rowcount!=1: raise ValueError('Favorit sudah berubah atau dihapus. Buka kembali daftar.')
            return rid

    def remove_owned(self, table, uid, rid, revision):
        if table not in ('category_rules','favorites'): raise ValueError('Jenis data tidak dikenal.')
        with self.transaction():
            return self.db.execute(f'DELETE FROM {table} WHERE user_id=? AND id=? AND revision=?',(uid,rid,revision)).rowcount==1

    def source_expense(self, uid, source_key):
        return self.db.execute('''SELECT e.* FROM expenses e JOIN expense_sources s ON e.id=s.record_id
            WHERE s.user_id=? AND e.user_id=? AND s.source_key=?''',(uid,uid,source_key)).fetchone()

    def add_confirmed(self, uid, values, source_key, when):
        """ID sumber mencegah konfirmasi pembayaran/favorit lama mencatat dua kali."""
        with self.transaction():
            previous = self.source_expense(uid,source_key)
            if previous: return previous,False
            line = self.db.execute('SELECT COALESCE(MAX(line_no),-1)+1 FROM expenses WHERE chat_id=? AND message_id=0',(uid,)).fetchone()[0]
            rid = self.db.execute('''INSERT INTO expenses
                (user_id,chat_id,message_id,line_no,spent_on,amount,note,category,created_at) VALUES(?,?,0,?,?,?,?,?,?)''',
                (uid,uid,line,values['spent_on'],values['amount'],values['note'],values['category'],when)).lastrowid
            self.db.execute('INSERT INTO expense_sources VALUES(?,?,?)',(uid,source_key,rid))
            return self.get(uid,rid),True

    def category_limits(self, uid, month):
        return self.db.execute('SELECT * FROM category_budgets WHERE user_id=? AND month=? ORDER BY category,id',(uid,month)).fetchall()

    def set_category_limit(self, uid, month, category, amount):
        with self.transaction():
            existing = self.db.execute('SELECT * FROM category_budgets WHERE user_id=? AND month=? AND category=?',(uid,month,category)).fetchone()
            if not existing and len(self.category_limits(uid,month))>=50: raise ValueError('Maksimal 50 anggaran kategori per bulan.')
            self.db.execute('''INSERT INTO category_budgets(user_id,month,category,amount) VALUES(?,?,?,?)
                ON CONFLICT(user_id,month,category) DO UPDATE SET amount=excluded.amount,
                alert_level=CASE WHEN category_budgets.amount=excluded.amount THEN category_budgets.alert_level ELSE 0 END''',
                (uid,month,category,amount))

    def category_notices(self, uid, month):
        from core import month_range
        notices=[]
        with self.transaction():
            start,end = month_range(month)
            totals={}
            for row in self.rows(uid,start,end): totals[row['category']] = totals.get(row['category'],0)+row['amount']
            for limit in self.category_limits(uid,month):
                used=totals.get(limit['category'],0)
                level=100 if used>=limit['amount'] else 80 if used*100>=limit['amount']*80 else 0
                if level>limit['alert_level']:
                    self.db.execute('UPDATE category_budgets SET alert_level=? WHERE id=?',(level,limit['id']))
                    notices.append((limit['category'],level,used,limit['amount']))
        return notices

    def report_setting(self, uid, kind):
        if kind not in ('weekly','monthly'): raise ValueError('Pilih rekap mingguan atau bulanan.')
        row=self.db.execute('SELECT * FROM report_settings WHERE user_id=? AND kind=?',(uid,kind)).fetchone()
        return dict(row) if row else dict(user_id=uid,kind=kind,enabled=0,at_time='07:00',with_excel=0,activated_at=0)

    def set_report_setting(self, uid, kind, now, **values):
        with self.transaction():
            current=self.report_setting(uid,kind)
            if values.get('enabled') and not current['enabled']: current['activated_at']=now
            current.update(values)
            self.db.execute('INSERT OR REPLACE INTO report_settings VALUES(?,?,?,?,?,?)',
                            (uid,kind,int(current['enabled']),current['at_time'],int(current['with_excel']),current['activated_at']))
            if values.get('with_excel') is False:
                self.db.execute('UPDATE report_jobs SET excel=NULL WHERE user_id=? AND kind=? AND completed=0',(uid,kind))

    def report_job(self, uid, kind, period):
        return self.db.execute('SELECT * FROM report_jobs WHERE user_id=? AND kind=? AND period=?',(uid,kind,period)).fetchone()

    def save_report_job(self, uid, kind, period, start, end, reply, excel, now):
        with self.transaction():
            self.db.execute('''INSERT OR IGNORE INTO report_jobs
                (user_id,kind,period,start_on,end_on,reply,excel,created_at) VALUES(?,?,?,?,?,?,?,?)''',
                (uid,kind,period,str(start),str(end),reply,excel,now))
        return self.report_job(uid,kind,period)

    def mark_report(self, uid, kind, period, part):
        if part not in ('text_sent','doc_sent','completed'): raise ValueError('Status kiriman tidak valid.')
        with self.transaction():
            self.db.execute(f'UPDATE report_jobs SET {part}=1 WHERE user_id=? AND kind=? AND period=?',(uid,kind,period))
            if part=='completed':
                self.db.execute("UPDATE report_jobs SET excel=NULL,reply='' WHERE user_id=? AND kind=? AND period=?",(uid,kind,period))

    def bill_rows(self, uid):
        return self.db.execute('SELECT * FROM bills WHERE user_id=? ORDER BY id',(uid,)).fetchall()

    def save_bill(self, uid, values, rid=None, revision=None):
        with self.transaction():
            fields=('title','amount','note','category','day_of_month','at_time','start_month')
            args=tuple(values[k] for k in fields)
            if rid is None:
                if len(self.bill_rows(uid))>=30: raise ValueError('Maksimal 30 tagihan rutin. Gunakan tagihan yang sudah tersedia.')
                return self.db.execute('''INSERT INTO bills
                    (title,amount,note,category,day_of_month,at_time,start_month,user_id) VALUES(?,?,?,?,?,?,?,?)''',(*args,uid)).lastrowid
            changed=self.db.execute('''UPDATE bills SET title=?,amount=?,note=?,category=?,day_of_month=?,at_time=?,
                start_month=?,revision=revision+1 WHERE user_id=? AND id=? AND revision=?''',(*args,uid,rid,revision))
            if changed.rowcount!=1: raise ValueError('Tagihan sudah berubah. Buka kembali daftar tagihan.')
            return rid

    def set_bill_enabled(self, uid, rid, enabled, revision=None):
        with self.transaction():
            sql='UPDATE bills SET enabled=?,revision=revision+1 WHERE user_id=? AND id=?'
            args=[int(enabled),uid,rid]
            if revision is not None: sql+=' AND revision=?'; args.append(revision)
            return self.db.execute(sql,args).rowcount==1

    def bill_cycle(self, uid, rid, period):
        return self.db.execute('SELECT * FROM bill_cycles WHERE user_id=? AND bill_id=? AND period=?',(uid,rid,period)).fetchone()

    def ensure_cycle(self, uid, bill, period, due_on):
        if bill['user_id']!=uid: raise ValueError('Tagihan tidak tersedia di akunmu.')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO bill_cycles(user_id,bill_id,period,due_on) VALUES(?,?,?,?)',
                            (uid,bill['id'],period,str(due_on)))
            self.db.execute('''UPDATE bill_cycles SET due_on=? WHERE user_id=? AND bill_id=? AND period=?
                AND reminded_at IS NULL AND expense_id IS NULL''',(str(due_on),uid,bill['id'],period))
        return self.bill_cycle(uid,bill['id'],period)

    def finish_bill_reminder(self, uid, rid, period, now):
        with self.transaction():
            self.db.execute('UPDATE bill_cycles SET reminded_at=? WHERE user_id=? AND bill_id=? AND period=?',(now,uid,rid,period))

    def pay_bill(self, uid, bill, period, values, when):
        with self.transaction():
            cycle=self.bill_cycle(uid,bill['id'],period)
            if cycle is None: raise ValueError('Periode tagihan belum dipilih.')
            row,added=self.add_confirmed(uid,values,f"bill:{bill['id']}:{period}",when)
            self.db.execute('UPDATE bill_cycles SET expense_id=? WHERE user_id=? AND bill_id=? AND period=?',
                            (row['id'],uid,bill['id'],period))
            return row,added


def validate_v23(store):
    """Validasi isi cadangan sebelum database tujuan diganti."""
    from core import month_range, read_day
    from ui import Reply
    def text(value, limit):
        if not isinstance(value,str) or not 1<=len(value)<=limit: raise ValueError('Teks fitur 2.3 di cadangan tidak valid.')
    def number(value, low=0, high=1000000000000):
        if type(value) is not int or not low<=value<=high: raise ValueError('Angka fitur 2.3 di cadangan tidak valid.')
    def at_time(value):
        if not isinstance(value,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):
            raise ValueError('Jam fitur 2.3 di cadangan tidak valid.')
    for table in V23_TABLES:
        for row in store.db.execute(f'SELECT * FROM {table}'):
            uid=row['user_id']; number(uid,1,2**63-1)
            if table in ('category_rules','favorites','bills'):
                number(row['id'],1,2**63-1); number(row['revision'])
            if table=='category_rules':
                text(row['keyword'],40); text(row['category'],32)
                if row['keyword']!=' '.join(row['keyword'].casefold().split()): raise ValueError('Kata aturan tidak valid.')
            if table in ('favorites','bills'):
                text(row['title'],40); text(row['note'],160); text(row['category'],32); number(row['amount'],1)
            if table=='bills':
                number(row['day_of_month'],1,31); at_time(row['at_time']); month_range(row['start_month'])
            if table=='category_budgets':
                month_range(row['month']); text(row['category'],32); number(row['amount'],1)
                if row['alert_level'] not in (0,80,100): raise ValueError('Batas pemberitahuan kategori tidak valid.')
            if table=='report_settings':
                if row['kind'] not in ('weekly','monthly'): raise ValueError('Jenis rekap tidak valid.')
                at_time(row['at_time']); number(row['activated_at'])
            if table=='report_jobs':
                if row['kind'] not in ('weekly','monthly'): raise ValueError('Jenis kiriman rekap tidak valid.')
                start,end=read_day(row['start_on']),read_day(row['end_on'])
                if not start<end or row['period']!=str(start): raise ValueError('Periode rekap tidak valid.')
                if row['kind']=='weekly' and ((end-start).days!=7 or start.weekday()!=0): raise ValueError('Periode mingguan tidak valid.')
                if row['kind']=='monthly' and (start.day!=1 or month_range(start.strftime('%Y-%m'))[1]!=end): raise ValueError('Periode bulanan tidak valid.')
                number(row['created_at'])
                if row['excel'] is not None and (not isinstance(row['excel'],bytes) or len(row['excel'])>49*1024*1024):
                    raise ValueError('Lampiran rekap tidak valid.')
                if not row['completed']:
                    reply=Reply.from_json(row['reply'])
                    if not isinstance(reply.text,str) or not 1<=len(reply.text)<=1800 or reply.backup_request or reply.clear_cutoff is not None:
                        raise ValueError('Pesan rekap tidak valid.')
                    if not isinstance(reply.buttons,list): raise ValueError('Tombol rekap tidak valid.')
                    for line in reply.buttons:
                        if not isinstance(line,list): raise ValueError('Baris tombol rekap tidak valid.')
                        for b in line:
                            if not isinstance(b,dict) or set(b)!={'text','callback_data'}:
                                raise ValueError('Tombol rekap tidak valid.')
                            text(b['text'],100); text(b['callback_data'],64)
            if table=='expense_sources':
                expense=store.get(uid,row['record_id']); key=row['source_key']
                if not expense or expense['message_id']!=0 or not isinstance(key,str) or not re.fullmatch(r'(?:fav:[0-9a-f]{12}|bill:[1-9][0-9]*:[0-9]{4}-[0-9]{2})',key):
                    raise ValueError('Sumber pencatatan tombol tidak valid.')
                if key.startswith('bill:'):
                    _,rid,period=key.split(':'); cycle=store.bill_cycle(uid,int(rid),period)
                    if not cycle or cycle['expense_id']!=expense['id']: raise ValueError('Hubungan pembayaran tagihan tidak valid.')
            if table=='bill_cycles':
                bill=store.owned('bills',uid,row['bill_id']); month_range(row['period']); read_day(row['due_on'])
                if not bill or row['period']<bill['start_month'] or row['due_on'][:7]!=row['period']:
                    raise ValueError('Periode tagihan tidak valid.')
                if row['reminded_at'] is not None: number(row['reminded_at'])
                if row['expense_id'] is not None:
                    expense=store.source_expense(uid,f"bill:{row['bill_id']}:{row['period']}")
                    if not expense or expense['id']!=row['expense_id']: raise ValueError('Pembayaran tagihan tidak valid.')
    missing=store.db.execute('''SELECT 1 FROM expenses e LEFT JOIN expense_sources s
        ON e.id=s.record_id AND e.user_id=s.user_id WHERE e.message_id=0 AND s.record_id IS NULL LIMIT 1''').fetchone()
    if missing: raise ValueError('Catatan tombol kehilangan identitas sumber.')
