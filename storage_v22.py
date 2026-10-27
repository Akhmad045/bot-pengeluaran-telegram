"""Penyimpanan riwayat edit, pilihan banyak catatan, dan aturan anggaran."""
import json
from datetime import datetime, timezone


EDIT_FIELDS = ('amount', 'note', 'category', 'spent_on')


def snapshot(row):
    return {key: row[key] for key in EDIT_FIELDS}


class AdvancedStore:
    def initialize_v22(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS expense_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, record_id INTEGER NOT NULL,
                changed_at TEXT NOT NULL, kind TEXT NOT NULL,
                before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                result_revision INTEGER NOT NULL, undone_by INTEGER);
            CREATE INDEX IF NOT EXISTS changes_by_user ON expense_changes(user_id,id);
            CREATE TABLE IF NOT EXISTS budget_rules (
                user_id INTEGER NOT NULL, effective_from TEXT NOT NULL,
                amount INTEGER CHECK(amount>0), created_at TEXT NOT NULL,
                PRIMARY KEY(user_id,effective_from));
        ''')
        if 'source' not in {r[1] for r in self.db.execute('PRAGMA table_info(budgets)')}:
            self.db.execute("ALTER TABLE budgets ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")

    def _change(self, uid, row, values, when, kind):
        before = snapshot(row)
        if before == values:
            return None
        self.db.execute('''UPDATE expenses SET amount=?,note=?,category=?,spent_on=?,revision=revision+1
            WHERE user_id=? AND id=?''', (*[values[k] for k in EDIT_FIELDS], uid, row['id']))
        cursor = self.db.execute('''INSERT INTO expense_changes
            (user_id,record_id,changed_at,kind,before_json,after_json,result_revision)
            VALUES(?,?,?,?,?,?,?)''', (uid,row['id'],when,kind,json.dumps(before,ensure_ascii=False),
                json.dumps(values,ensure_ascii=False),row['revision']+1))
        return cursor.lastrowid

    def edit_expense(self, user_id, record_id, revision, values, when=None):
        when = when or datetime.now(timezone.utc).isoformat()
        with self.transaction():
            row = self.get(user_id,record_id)
            if row is None or row['deleted'] or row['revision']!=revision:
                return False
            self._change(user_id,row,values,when,'edit')
            return True

    def changes(self, uid, record_id=None):
        sql,args = 'SELECT * FROM expense_changes WHERE user_id=?',[uid]
        if record_id is not None:
            sql += ' AND record_id=?'
            args.append(record_id)
        return self.db.execute(sql+' ORDER BY id DESC',args).fetchall()

    def change(self, uid, change_id):
        return self.db.execute('SELECT * FROM expense_changes WHERE user_id=? AND id=?',
                               (uid,change_id)).fetchone()

    def can_undo(self, uid, change):
        if change is None or change['kind']=='undo' or change['undone_by'] is not None:
            return False
        row = self.get(uid,change['record_id'])
        return bool(row and not row['deleted'] and row['revision']==change['result_revision'])

    def undo_change(self, uid, change_id, when):
        with self.transaction():
            change = self.change(uid,change_id)
            if not self.can_undo(uid,change):
                return False
            row = self.get(uid,change['record_id'])
            new_id = self._change(uid,row,json.loads(change['before_json']),when,'undo')
            self.db.execute('UPDATE expense_changes SET undone_by=? WHERE id=?',(new_id,change_id))
            return True

    def apply_bulk(self, uid, selected, action, category, when):
        """Cek seluruh versi sebelum menyentuh satu catatan pun."""
        if not 1<=len(selected)<=50 or action not in ('delete','category'):
            raise ValueError('Pilih 1–50 catatan dan tindakan yang tersedia.')
        if action=='category' and (not isinstance(category,str) or not 1<=len(category)<=32):
            raise ValueError('Kategori wajib diisi, maksimal 32 karakter.')
        with self.transaction():
            rows = [self.get(uid,int(rid)) for rid in selected]
            if any(row is None or row['deleted'] or row['revision']!=selected[str(row['id'])] for row in rows):
                raise ValueError('Ada catatan yang sudah berubah atau dihapus. Belum ada perubahan disimpan. Pilih ulang catatan.')
            changed = 0
            for row in rows:
                if action=='delete':
                    self.set_deleted(uid,row['id'],True)
                    changed += 1
                else:
                    values = snapshot(row)
                    values['category'] = category
                    changed += self._change(uid,row,values,when,'bulk_category') is not None
            return changed

    def budget_rule(self, uid, month):
        return self.db.execute('''SELECT * FROM budget_rules WHERE user_id=? AND effective_from<=?
            ORDER BY effective_from DESC LIMIT 1''',(uid,month)).fetchone()

    def set_budget_rule(self, uid, effective_from, amount, when):
        from core import month_range
        month_range(effective_from)
        if amount is not None and not 1<=amount<=1000000000000:
            raise ValueError('Nominal anggaran tidak valid.')
        with self.transaction():
            self.db.execute('INSERT OR REPLACE INTO budget_rules VALUES(?,?,?,?)',
                            (uid,effective_from,amount,when))
            # Bulan manual tetap menjadi pengecualian; aturan versi lama tetap tersimpan.
            months = [r[0] for r in self.db.execute(
                "SELECT month FROM budgets WHERE user_id=? AND month>=? AND source='auto'",(uid,effective_from))]
            for month in months:
                self.budget(uid,month)

    def budget(self, user_id, month):
        from core import month_range
        month_range(month)
        row = self.db.execute('SELECT * FROM budgets WHERE user_id=? AND month=?',(user_id,month)).fetchone()
        if row is not None and row['source']=='manual':
            return row
        rule = self.budget_rule(user_id,month)
        amount = rule['amount'] if rule else None
        if amount is None:
            if row is not None:
                with self.transaction():
                    self.db.execute("DELETE FROM budgets WHERE user_id=? AND month=? AND source='auto'",(user_id,month))
            return None
        if row is None or row['amount']!=amount:
            with self.transaction():
                self.db.execute('''INSERT INTO budgets(user_id,month,amount,source) VALUES(?,?,?,'auto')
                    ON CONFLICT(user_id,month) DO UPDATE SET amount=excluded.amount,alert_level=0''',
                    (user_id,month,amount))
        return self.db.execute('SELECT * FROM budgets WHERE user_id=? AND month=?',(user_id,month)).fetchone()

    def set_budget(self, user_id, month, amount):
        with self.transaction():
            self.db.execute('''INSERT INTO budgets(user_id,month,amount,source) VALUES(?,?,?,'manual')
                ON CONFLICT(user_id,month) DO UPDATE SET amount=excluded.amount,source='manual',
                alert_level=CASE WHEN budgets.amount=excluded.amount THEN budgets.alert_level ELSE 0 END''',
                (user_id,month,amount))

    def reset_budget_override(self, uid, month):
        with self.transaction():
            current,rule = self.budget(uid,month),self.budget_rule(uid,month)
            if current and rule and current['amount']==rule['amount']:
                self.db.execute("UPDATE budgets SET source='auto' WHERE user_id=? AND month=?",(uid,month))
                return self.budget(uid,month)
            self.db.execute('DELETE FROM budgets WHERE user_id=? AND month=?',(uid,month))
            return self.budget(uid,month)
