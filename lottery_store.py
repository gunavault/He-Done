"""Item raffles: atomic tickets, durable random results, and refundable point debits."""
import secrets
from datetime import datetime, timedelta
from schedule import WIB


def lottery_now(now=None):
    return (now or datetime.now(WIB)).astimezone(WIB)


class LotteryStoreMixin:
    def init_lottery_tables(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL, message_id TEXT, request_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL, prize TEXT NOT NULL, cost INTEGER NOT NULL CHECK(cost>0),
                closes_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                winner_id TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
                handled_by TEXT, handled_at TEXT, dirty INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                lottery_id INTEGER NOT NULL REFERENCES lotteries(id), guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL, cost INTEGER NOT NULL CHECK(cost>0), created_at TEXT NOT NULL,
                voided INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(lottery_id,user_id)
            );
            CREATE INDEX IF NOT EXISTS lottery_ticket_wallet ON lottery_tickets(guild_id,user_id);
            CREATE TABLE IF NOT EXISTS lottery_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, lottery_id INTEGER NOT NULL REFERENCES lotteries(id),
                actor_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL
            );
        ''')

    def lottery_get(self, guild_id, lottery_id):
        row = self.db.execute('SELECT * FROM lotteries WHERE guild_id=? AND id=?',
                              (str(guild_id), lottery_id)).fetchone()
        if row is None:
            raise ValueError('Lotre tidak ditemukan di server ini.')
        return row

    def lottery_audit(self, lottery_id, actor, action, now):
        self.db.execute('INSERT INTO lottery_audit(lottery_id,actor_id,action,at) VALUES(?,?,?,?)',
                        (lottery_id, str(actor), action, now.isoformat()))

    def lottery_create(self, guild_id, channel_id, actor, title, prize, cost, closes_at, request_id, now=None):
        now = lottery_now(now)
        title, prize = title.strip(), prize.strip()
        if not 1 <= len(title) <= 100 or not 1 <= len(prize) <= 500:
            raise ValueError('Judul 1–100 karakter dan hadiah 1–500 karakter.')
        if type(cost) is not int or not 1 <= cost <= 1000000:
            raise ValueError('Biaya harus 1–1000000 poin.')
        if closes_at.tzinfo is None or not now < closes_at <= now + timedelta(days=30):
            raise ValueError('Penutupan harus di masa depan, maksimal 30 hari.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM lotteries WHERE request_id=?', (str(request_id),)).fetchone()
            if old:
                if (old['guild_id'], old['channel_id'], old['created_by'], old['title'], old['prize'], old['cost'], old['closes_at']) != (
                    str(guild_id), str(channel_id), str(actor), title, prize, cost, closes_at.astimezone(WIB).isoformat()):
                    raise ValueError('Permintaan lotre sudah digunakan untuk data berbeda.')
                return old
            cur = self.db.execute('''INSERT INTO lotteries
                (guild_id,channel_id,request_id,title,prize,cost,closes_at,created_by,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)''', (str(guild_id), str(channel_id), str(request_id), title, prize, cost,
                    closes_at.astimezone(WIB).isoformat(), str(actor), now.isoformat()))
            self.lottery_audit(cur.lastrowid, actor, 'created', now)
            return self.lottery_get(guild_id, cur.lastrowid)

    def lottery_join(self, guild_id, lottery_id, user_id, expected_cost, now=None):
        now = lottery_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.lottery_get(guild_id, lottery_id)
            old = self.db.execute('SELECT 1 FROM lottery_tickets WHERE lottery_id=? AND user_id=?',
                                  (lottery_id, str(user_id))).fetchone()
            if old:
                return False
            if row['status'] != 'open' or now >= datetime.fromisoformat(row['closes_at']):
                raise ValueError('Pendaftaran lotre sudah ditutup.')
            if row['cost'] != expected_cost:
                raise ValueError('Biaya berubah. Buka konfirmasi baru.')
            balance = self.point_summary(guild_id, user_id)['points']
            if balance < row['cost']:
                raise ValueError(f"Saldo tidak cukup: {balance} poin; biaya {row['cost']} poin.")
            self.db.execute('INSERT INTO lottery_tickets(lottery_id,guild_id,user_id,cost,created_at) VALUES(?,?,?,?,?)',
                            (lottery_id, str(guild_id), str(user_id), row['cost'], now.isoformat()))
            self.db.execute('UPDATE lotteries SET dirty=1 WHERE id=?', (lottery_id,))
            self.lottery_audit(lottery_id, user_id, 'joined', now)
            return True

    def lottery_members(self, guild_id, lottery_id, page=0):
        self.lottery_get(guild_id, lottery_id)
        return self.db.execute('SELECT user_id FROM lottery_tickets WHERE lottery_id=? ORDER BY created_at,user_id LIMIT 20 OFFSET ?',
                               (lottery_id, page * 20)).fetchall()

    def lottery_count(self, guild_id, lottery_id):
        self.lottery_get(guild_id, lottery_id)
        return self.db.execute('SELECT COUNT(*) FROM lottery_tickets WHERE lottery_id=?', (lottery_id,)).fetchone()[0]

    def lottery_draw(self, guild_id, lottery_id, now=None):
        now = lottery_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.lottery_get(guild_id, lottery_id)
            if row['status'] != 'open':
                return row
            if now < datetime.fromisoformat(row['closes_at']):
                raise ValueError('Belum waktunya pengundian.')
            users = [r[0] for r in self.db.execute('SELECT user_id FROM lottery_tickets WHERE lottery_id=? ORDER BY user_id', (lottery_id,))]
            winner = secrets.choice(users) if len(users) >= 2 else None
            status = 'drawn' if winner else 'cancelled'
            self.db.execute('UPDATE lotteries SET status=?,winner_id=?,handled_at=?,handled_by=?,dirty=1 WHERE id=?',
                            (status, winner, now.isoformat(), 'automatic', lottery_id))
            self.lottery_audit(lottery_id, 'automatic', 'drawn:' + winner if winner else 'cancelled:insufficient_participants', now)
            return self.lottery_get(guild_id, lottery_id)

    def lottery_status(self, guild_id, lottery_id, action, actor, now=None):
        now = lottery_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.lottery_get(guild_id, lottery_id)
            target = {'cancel': 'cancelled', 'deliver': 'delivered'}.get(action)
            if target is None:
                raise ValueError('Aksi lotre tidak dikenal.')
            if row['status'] == target:
                return row
            if action == 'cancel' and (row['status'] != 'open' or now >= datetime.fromisoformat(row['closes_at'])):
                raise ValueError('Lotre hanya bisa dibatalkan sebelum waktu tutup.')
            if action == 'deliver' and row['status'] != 'drawn':
                raise ValueError('Hadiah hanya bisa diserahkan setelah pemenang ditentukan.')
            self.db.execute('UPDATE lotteries SET status=?,handled_by=?,handled_at=?,dirty=1 WHERE id=?',
                            (target, str(actor), now.isoformat(), lottery_id))
            self.lottery_audit(lottery_id, actor, target, now)
            return self.lottery_get(guild_id, lottery_id)

    def lottery_spent(self, guild_id, user_id):
        return self.db.execute('''SELECT COALESCE(SUM(t.cost),0) FROM lottery_tickets t
            JOIN lotteries l ON l.id=t.lottery_id WHERE t.guild_id=? AND t.user_id=?
            AND t.voided=0 AND l.status!='cancelled' ''', (str(guild_id), str(user_id))).fetchone()[0]
