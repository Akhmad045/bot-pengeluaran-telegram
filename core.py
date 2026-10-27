"""Bot pengeluaran pribadi. Python 3.10+, tanpa paket tambahan."""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
import re
import secrets
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from storage_v24 import WalletStore

ROOT = Path(__file__).resolve().parent
MONTHS = ("", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember")
ZONES = {name: timezone(timedelta(hours=hours), name)
         for name, hours in (("WIB", 7), ("WITA", 8), ("WIT", 9))}


def rupiah(value: int) -> str:
    return "Rp" + f"{value:,}".replace(",", ".")


def day_label(value: date) -> str:
    return f"{value.day} {MONTHS[value.month]} {value.year}"


def read_day(value: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Tanggal harus YYYY-MM-DD, misalnya 2026-09-19.")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Tanggal tidak valid. Periksa hari, bulan, dan tahunnya.") from None
    if result.year < 1900 or result.year > 9998:
        raise ValueError("Tahun harus antara 1900 dan 9998.")
    return result


def month_range(value: str) -> tuple[date, date]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise ValueError("Bulan harus YYYY-MM, misalnya 2026-09.")
    first = read_day(value + "-01")
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, last


def parse_amount(value: str) -> int:
    """Rupiah bulat; titik ribuan, koma desimal hanya dengan rb/k/jt."""
    value = re.sub(r"^rp", "", value.strip().lower())
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]{3})*(?:,[0-9]{1,6})?)(rb|k|jt)?", value)
    if not match or len(value) > 30:
        raise ValueError("Nominal tidak valid. Gunakan 15000, 15.000, 15rb, atau 1,5jt.")
    number, suffix = match.groups()
    if "," in number and not suffix:
        raise ValueError("Gunakan rupiah bulat: 15000 atau 15.000. Untuk ribuan: 15,5rb.")
    amount = Decimal(number.replace(".", "").replace(",", "."))
    amount *= {None: 1, "rb": 1000, "k": 1000, "jt": 1000000}[suffix]
    if amount != amount.to_integral_value() or not 1 <= amount <= 1000000000000:
        raise ValueError("Nominal harus rupiah bulat, minimal Rp1, maksimal Rp1.000.000.000.000.")
    return int(amount)


@dataclass(frozen=True)
class Expense:
    spent_on: date
    amount: int
    note: str
    category: str
    wallet: str | None = None


def parse_expense(text: str, sent_on: date) -> Expense:
    text = " ".join(text.split())
    spent_on = sent_on
    if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:\s|$)", text):
        pieces = text.split(" ", 1)
        spent_on = read_day(pieces[0])
        text = pieces[1] if len(pieces) > 1 else ""
    if spent_on > sent_on:
        raise ValueError("Tanggal pengeluaran tidak boleh melewati tanggal pesan ini.")
    text = re.sub(r"^rp\s+", "Rp", text, flags=re.IGNORECASE)
    parts = text.split(" ", 1)
    if len(parts) != 2:
        raise ValueError("Tulis nominal dan keterangan. Contoh: 15000 makan siang")
    amount = parse_amount(parts[0])
    fields = parts[1].split("|")
    if len(fields) > 3:
        raise ValueError("Gunakan nominal keterangan | kategori | dompet; maksimal dua tanda |.")
    note = fields[0].strip()
    category = fields[1].strip().capitalize() if len(fields) >= 2 else "Lainnya"
    if len(fields)==3 and not category: category='Lainnya'
    wallet = fields[2].strip() if len(fields)==3 else None
    if wallet is not None and not 1<=len(wallet)<=32: raise ValueError('Nama dompet wajib diisi setelah pemisah kedua, maksimal 32 karakter.')
    if not 1 <= len(note) <= 160:
        raise ValueError("Keterangan wajib diisi, maksimal 160 karakter.")
    if not 1 <= len(category) <= 32:
        raise ValueError("Kategori wajib diisi setelah |, maksimal 32 karakter.")
    return Expense(spent_on, amount, note, category, wallet)


def parse_batch(text: str, sent_on: date) -> list[Expense]:
    lines = [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1) if line.strip()]
    if not lines:
        raise ValueError("Tulis nominal dan keterangan, misalnya 15000 makan siang.")
    if len(lines) > 100:
        raise ValueError("Maksimal 100 pengeluaran dalam satu pesan. Pisahkan menjadi beberapa pesan.")
    expenses = []
    for line_number, line in lines:
        try:
            expenses.append(parse_expense(line, sent_on))
        except ValueError as exc:
            raise ValueError(f"Baris {line_number}: {exc}\n\nBelum ada pengeluaran dari pesan ini yang disimpan. "
                             "Perbaiki baris tersebut, lalu kirim ulang seluruh pesan.") from None
    return expenses


SCHEMA = """CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL DEFAULT 0,
    spent_on TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
    note TEXT NOT NULL, category TEXT NOT NULL, created_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0, 1)),
    UNIQUE(chat_id, message_id, line_no)
)"""


class Store(WalletStore):
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self.db.create_function('casefold', 1, lambda value: str(value).casefold(), deterministic=True)
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self):
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(expenses)")}
        if columns and "line_no" not in columns:
            if self.path != ":memory:":
                backup = Path(self.path + ".v1.bak")
                if not backup.exists():
                    dest = sqlite3.connect(str(backup))
                    try:
                        self.db.backup(dest)
                    finally:
                        dest.close()
            # Seluruh perubahan skema dan salinan catatan berlangsung satu transaksi.
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(SCHEMA.replace("expenses (", "expenses_v2 ("))
                self.db.execute("""INSERT INTO expenses_v2
                    (id,user_id,chat_id,message_id,line_no,spent_on,amount,note,category,created_at,deleted)
                    SELECT id,user_id,chat_id,message_id,0,spent_on,amount,note,category,created_at,deleted
                    FROM expenses""")
                self.db.execute("DROP TABLE expenses")
                self.db.execute("ALTER TABLE expenses_v2 RENAME TO expenses")
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        self.db.execute(SCHEMA)
        self.db.executescript("""
            CREATE INDEX IF NOT EXISTS expenses_by_user_date ON expenses(user_id, spent_on, deleted);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences (user_id INTEGER PRIMARY KEY, zone TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_messages (
                chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, sent_at INTEGER NOT NULL,
                PRIMARY KEY(chat_id,message_id));
            CREATE TABLE IF NOT EXISTS callback_actions (callback_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS pending_inputs (
                user_id INTEGER PRIMARY KEY, token TEXT NOT NULL, kind TEXT NOT NULL,
                data TEXT NOT NULL, expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS event_receipts (
                event_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL, reply TEXT NOT NULL,
                created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS budgets (
                user_id INTEGER NOT NULL, month TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0),
                alert_level INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,month));
            CREATE TABLE IF NOT EXISTS search_filters (
                user_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY, at_time TEXT NOT NULL DEFAULT '21:00',
                enabled INTEGER NOT NULL DEFAULT 0, next_due INTEGER NOT NULL DEFAULT 0,
                last_sent_day TEXT);
        """)
        if 'revision' not in {row[1] for row in self.db.execute('PRAGMA table_info(expenses)')}:
            self.db.execute('ALTER TABLE expenses ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
        self.initialize_v22()
        self.initialize_v23()
        self.initialize_v24()
        # Pesan transaksi dari versi lama dapat dikenali; balasan bot versi lama tidak tersedia.
        seeded = self.db.execute("SELECT value FROM metadata WHERE key='messages_seeded'").fetchone()
        if not seeded:
            with self.transaction():
                for row in self.db.execute("SELECT chat_id,message_id,created_at FROM expenses"):
                    try:
                        stamp = int(datetime.fromisoformat(row["created_at"]).timestamp())
                    except ValueError:
                        continue
                    self.db.execute("INSERT OR IGNORE INTO chat_messages VALUES(?,?,?)",
                                    (row["chat_id"],row["message_id"],stamp))
                self.db.execute("INSERT INTO metadata VALUES('messages_seeded','1')")
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','2.4')")

    def bind_bot(self, bot_id: int):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('bot_id', ?)", (str(bot_id),))
            saved = self.db.execute("SELECT value FROM metadata WHERE key='bot_id'").fetchone()[0]
            if saved != str(bot_id):
                raise ValueError("Database ini milik bot lain. Gunakan folder berbeda untuk bot lain.")

    @contextmanager
    def transaction(self):
        """Satu perubahan pengguna dan tanda terimanya disimpan secara atomik."""
        if self._transaction_depth:
            yield
            return
        self.db.execute('BEGIN IMMEDIATE')
        self._transaction_depth = 1
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._transaction_depth = 0

    def add_many(self, user_id: int, message: dict, expenses: list[Expense], stamp: datetime):
        with self.transaction():
            # Mengunci sebelum cek duplikasi agar pemrosesan ulang tidak menggandakan catatan.
            previous = self.db.execute("SELECT * FROM expenses WHERE chat_id=? AND message_id=? ORDER BY line_no",
                                       (message["chat"]["id"], message["message_id"])).fetchall()
            if previous:
                if any(row["user_id"] != user_id for row in previous):
                    raise RuntimeError("Identitas pesan tidak cocok.")
                return previous, False
            wallets = [self.resolve_wallet(user_id,expense.wallet) for expense in expenses]
            for index, expense in enumerate(expenses):
                self.db.execute("""INSERT INTO expenses
                    (user_id,chat_id,message_id,line_no,spent_on,amount,note,category,created_at,wallet_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (user_id,message["chat"]["id"],message["message_id"],index,expense.spent_on.isoformat(),
                     expense.amount,expense.note,expense.category,stamp.isoformat(),wallets[index]))
            rows = self.db.execute("SELECT * FROM expenses WHERE chat_id=? AND message_id=? ORDER BY line_no",
                                   (message["chat"]["id"], message["message_id"])).fetchall()
        return rows, True

    def add(self, user_id, message, expense, stamp):
        rows, added = self.add_many(user_id,message,[expense],stamp)
        return rows[0], added

    def rows(self, user_id: int, start: date, end: date):
        return self.db.execute("""SELECT e.*,w.name AS wallet_name FROM expenses e
            LEFT JOIN wallets w ON w.id=e.wallet_id AND w.user_id=e.user_id WHERE e.user_id=? AND e.deleted=0
            AND e.spent_on>=? AND e.spent_on<? ORDER BY e.spent_on,e.id""",
            (user_id,start.isoformat(),end.isoformat())).fetchall()

    def history(self, user_id: int, deleted: bool = False):
        return self.db.execute("SELECT * FROM expenses WHERE user_id=? AND deleted=? ORDER BY spent_on DESC,id DESC",
                               (user_id,int(deleted))).fetchall()

    def get(self, user_id: int, record_id: int):
        return self.db.execute("SELECT * FROM expenses WHERE user_id=? AND id=?", (user_id,record_id)).fetchone()

    def set_deleted(self, user_id: int, record_id: int, deleted: bool, callback_id: str | None = None):
        with self.transaction():
            if callback_id is not None:
                cursor = self.db.execute("INSERT OR IGNORE INTO callback_actions VALUES(?)", (callback_id,))
                if cursor.rowcount == 0:
                    return False
            self.db.execute("UPDATE expenses SET deleted=?,revision=revision+1 WHERE user_id=? AND id=? AND deleted<>?",
                            (int(deleted),user_id,record_id,int(deleted)))
        return True

    def get_zone(self, user_id: int, default: timezone):
        row = self.db.execute("SELECT zone FROM preferences WHERE user_id=?", (user_id,)).fetchone()
        return ZONES.get(row[0], default) if row else default

    def set_zone(self, user_id: int, zone: str):
        if zone not in ZONES:
            raise ValueError("Pilih WIB, WITA, atau WIT.")
        with self.transaction():
            self.db.execute("INSERT INTO preferences VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET zone=excluded.zone",
                            (user_id,zone))

    def track_message(self, chat_id: int, message_id: int, sent_at: int):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO chat_messages VALUES(?,?,?)",(chat_id,message_id,sent_at))
            self.db.execute("DELETE FROM chat_messages WHERE sent_at<?",(int(time.time())-172800,))

    def clear_candidates(self, chat_id: int, cutoff: int, now: int):
        return [r[0] for r in self.db.execute("""SELECT message_id FROM chat_messages
            WHERE chat_id=? AND message_id<=? AND sent_at>? ORDER BY message_id""",
            (chat_id,cutoff,now-172790))]

    def latest_message_id(self, chat_id: int):
        return self.db.execute("SELECT COALESCE(MAX(message_id),0) FROM chat_messages WHERE chat_id=?",
                               (chat_id,)).fetchone()[0]

    def forget_messages(self, chat_id: int, message_ids: list[int]):
        with self.transaction():
            self.db.executemany("DELETE FROM chat_messages WHERE chat_id=? AND message_id=?",
                                [(chat_id,i) for i in message_ids])

    def close(self):
        self.db.close()

    def get_receipt(self, key, user_id):
        row = self.db.execute('SELECT reply FROM event_receipts WHERE event_key=? AND user_id=?',
                              (key,user_id)).fetchone()
        return row[0] if row else None

    def save_receipt(self, key, user_id, reply, now):
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO event_receipts VALUES(?,?,?,?)',(key,user_id,reply,now))
            self.db.execute('DELETE FROM event_receipts WHERE created_at<?',(now-7*86400,))

    def pending(self, user_id):
        row = self.db.execute('SELECT * FROM pending_inputs WHERE user_id=?',(user_id,)).fetchone()
        if row:
            item = dict(row)
            item['data'] = json.loads(item['data'])
            return item

    def start_pending(self, user_id, kind, data, now):
        token = secrets.token_hex(6)
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO pending_inputs VALUES(?,?,?,?,?)',
                            (user_id,token,kind,json.dumps(data,ensure_ascii=False),now+1800))
        return self.pending(user_id)

    def update_pending(self, user_id, token, data, now):
        with self.transaction():
            self.db.execute('UPDATE pending_inputs SET data=?,expires_at=? WHERE user_id=? AND token=?',
                            (json.dumps(data,ensure_ascii=False),now+1800,user_id,token))
        return self.pending(user_id)

    def cancel_pending(self, user_id):
        with self.transaction():
            self.db.execute('DELETE FROM pending_inputs WHERE user_id=?',(user_id,))

    def budget_notice(self, user_id, month):
        with self.transaction():
            budget = self.budget(user_id,month)
            if budget is None:
                return None
            start,end = month_range(month)
            used = sum(r['amount'] for r in self.rows(user_id,start,end))
            level = 100 if used>=budget['amount'] else 80 if used*100>=budget['amount']*80 else 0
            if level<=budget['alert_level']:
                return None
            self.db.execute('UPDATE budgets SET alert_level=? WHERE user_id=? AND month=?',(level,user_id,month))
            return level,used,budget['amount']

    def filters(self, user_id):
        row = self.db.execute('SELECT data FROM search_filters WHERE user_id=?',(user_id,)).fetchone()
        return json.loads(row[0]) if row else {'keyword':'','category':None,'start':None,'end':None}

    def set_filters(self, user_id, values):
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO search_filters VALUES(?,?)',
                            (user_id,json.dumps(values,ensure_ascii=False)))

    def search_expenses(self, user_id, filters):
        sql = 'SELECT * FROM expenses WHERE user_id=? AND deleted=0'
        args = [user_id]
        if filters['keyword']:
            sql += ' AND instr(casefold(note),casefold(?))>0'
            args.append(filters['keyword'])
        if filters['category'] is not None:
            sql += ' AND category=?'
            args.append(filters['category'])
        for field,op in [('start','>='),('end','<=')]:
            if filters[field]:
                sql += ' AND spent_on'+op+'?'
                args.append(filters[field])
        return self.db.execute(sql+' ORDER BY spent_on DESC,id DESC',args).fetchall()

    def categories(self, user_id):
        return [r[0] for r in self.db.execute('SELECT DISTINCT category FROM expenses WHERE user_id=? AND deleted=0 ORDER BY category',
                                             (user_id,))]

    def reminder(self, user_id):
        row = self.db.execute('SELECT * FROM reminders WHERE user_id=?',(user_id,)).fetchone()
        return dict(row) if row else {'user_id':user_id,'at_time':'21:00','enabled':0,'next_due':0,'last_sent_day':None}

    def set_reminder(self, user_id, at_time, enabled, next_due):
        with self.transaction():
            self.db.execute('''INSERT INTO reminders(user_id,at_time,enabled,next_due) VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET at_time=excluded.at_time,enabled=excluded.enabled,next_due=excluded.next_due''',
                (user_id,at_time,int(enabled),next_due))

    def due_reminders(self, now):
        return self.db.execute('SELECT * FROM reminders WHERE enabled=1 AND next_due<=? ORDER BY user_id',(now,)).fetchall()

    def finish_reminder(self, user_id, day, next_due):
        with self.transaction():
            self.db.execute('UPDATE reminders SET last_sent_day=?,next_due=? WHERE user_id=?',(day,next_due,user_id))
