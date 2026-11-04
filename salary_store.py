"""Recurring Saturday payroll in the shared SQLite point ledger."""
from datetime import date, datetime, time, timedelta

from schedule import WIB


def parse_salary_hour(value):
    try:
        pieces = value.split(':')
        if len(pieces) != 2 or len(pieces[0]) != 2 or len(pieces[1]) != 2:
            raise ValueError()
        hour, minute = (int(piece) for piece in pieces)
        return time(hour, minute)
    except (TypeError, ValueError):
        raise ValueError('GAJIAN_JAM harus HH:MM, misalnya 09:00.') from None


def next_salary_day(now, hour):
    now = now.astimezone(WIB)
    distance = (5 - now.weekday()) % 7
    candidate = now.date() + timedelta(days=distance)
    if datetime.combine(candidate, hour, tzinfo=WIB) <= now:
        candidate += timedelta(days=7)
    return candidate


def last_salary_day(now):
    now = now.astimezone(WIB)
    return now.date() - timedelta(days=(now.weekday() - 5) % 7)


class SalaryStoreMixin:
    def init_salary_tables(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS weekly_salaries (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points BETWEEN 1 AND 1000000),
                detail TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                effective_payday TEXT NOT NULL, updated_by TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(guild_id,user_id)
            );
            CREATE INDEX IF NOT EXISTS weekly_salaries_active
                ON weekly_salaries(guild_id,active,effective_payday);
            CREATE TABLE IF NOT EXISTS weekly_salary_payments (
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
                payday TEXT NOT NULL, points INTEGER NOT NULL CHECK(points>0),
                detail TEXT NOT NULL, paid_at TEXT NOT NULL,
                voided INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id,user_id,payday)
            );
            CREATE INDEX IF NOT EXISTS weekly_salary_payments_user
                ON weekly_salary_payments(guild_id,user_id,voided);
        ''')

    def salary_set(self, guild_id, user_id, points, detail, actor_id, *, now=None, hour=None):
        if type(points) is not int or not 1 <= points <= 1000000:
            raise ValueError('Point gaji harus bilangan bulat 1–1000000.')
        if not isinstance(detail, str) or not 1 <= len(detail.strip()) <= 500:
            raise ValueError('Detail gaji harus 1–500 karakter.')
        if int(user_id) <= 0 or int(guild_id) <= 0:
            raise ValueError('ID anggota/server tidak valid.')
        now = (now or datetime.now(WIB)).astimezone(WIB)
        hour = hour or time(9, 0)
        detail = detail.strip()
        values = (str(guild_id), str(user_id))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.db.execute('SELECT * FROM weekly_salaries WHERE guild_id=? AND user_id=?', values).fetchone()
            if previous and previous['active'] and previous['points'] == points and previous['detail'] == detail:
                return previous
            effective = next_salary_day(now, hour).isoformat()
            self.db.execute('''INSERT INTO weekly_salaries
                (guild_id,user_id,points,detail,active,effective_payday,updated_by,created_at,updated_at)
                VALUES(?,?,?,?,1,?,?,?,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET
                    points=excluded.points,detail=excluded.detail,active=1,
                    effective_payday=excluded.effective_payday,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                (*values, points, detail, effective, str(actor_id), now.isoformat(), now.isoformat()))
            return self.db.execute('SELECT * FROM weekly_salaries WHERE guild_id=? AND user_id=?', values).fetchone()

    def salary_stop(self, guild_id, user_id, actor_id, *, now=None):
        now = (now or datetime.now(WIB)).astimezone(WIB)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT * FROM weekly_salaries WHERE guild_id=? AND user_id=?',
                                  (str(guild_id), str(user_id))).fetchone()
            if not row or not row['active']:
                return False
            self.db.execute('''UPDATE weekly_salaries
                SET active=0,updated_by=?,updated_at=? WHERE guild_id=? AND user_id=?''',
                (str(actor_id), now.isoformat(), str(guild_id), str(user_id)))
            return True

    def salary_list(self, guild_id, page=None):
        sql = '''SELECT * FROM weekly_salaries WHERE guild_id=? AND active=1
                 ORDER BY user_id'''
        params = [str(guild_id)]
        if page is not None:
            sql += ' LIMIT 10 OFFSET ?'
            params.append(page * 10)
        return self.db.execute(sql, params).fetchall()

    def salary_payweek(self, guild_id, payday, *, now=None):
        if isinstance(payday, str):
            payday = date.fromisoformat(payday)
        if payday.weekday() != 5:
            raise ValueError('Tanggal pembayaran wajib hari Sabtu.')
        now = (now or datetime.now(WIB)).astimezone(WIB)
        if payday > now.date():
            raise ValueError('Tanggal pembayaran belum tiba.')
        new_payments = []
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            rows = self.db.execute('''SELECT * FROM weekly_salaries
                WHERE guild_id=? AND active=1 AND effective_payday<=? ORDER BY user_id''',
                (str(guild_id), payday.isoformat())).fetchall()
            for row in rows:
                result = self.db.execute('''INSERT OR IGNORE INTO weekly_salary_payments
                    (guild_id,user_id,payday,points,detail,paid_at)
                    VALUES(?,?,?,?,?,?)''',
                    (str(guild_id), row['user_id'], payday.isoformat(), row['points'],
                     row['detail'], now.isoformat()))
                if result.rowcount == 1:
                    new_payments.append((row['user_id'], row['points']))
        return new_payments

    def salary_summary(self, guild_id, user_id):
        return self.db.execute('''SELECT COALESCE(SUM(points),0) AS points,COUNT(*) AS payments
            FROM weekly_salary_payments WHERE guild_id=? AND user_id=? AND voided=0''',
            (str(guild_id), str(user_id))).fetchone()

    def salary_history(self, guild_id, page=0):
        return self.db.execute('''SELECT * FROM weekly_salary_payments
            WHERE guild_id=? ORDER BY payday DESC,user_id LIMIT 10 OFFSET ?''',
            (str(guild_id), page * 10)).fetchall()
