"""Durable manual raid events; independent of T-Rex timer tables."""
import sqlite3
import re
from datetime import datetime, date, timedelta

from schedule import WIB, parse_time, SUPPORTED_INDICES
from redeem_store import RedeemStoreMixin
from salary_store import SalaryStoreMixin
from quest_store import QuestStoreMixin


KINDS = {'trex': 'T-Rex', 'rift': 'Rift', 'savage': 'Savage'}
EVENT_POINTS = {'trex': 40, 'savage': 50, 'rift': 35}
STATUSES = {
    'pending': 'Menunggu diterima', 'accepted': 'Hadir',
    'absent': 'Tidak Hadir',
}


def raid_time(jam, tanggal=None, now=None):
    now = (now or datetime.now(WIB)).astimezone(WIB)
    try:
        day = date.fromisoformat(tanggal) if tanggal else now.date()
        if tanggal and day.isoformat() != tanggal:
            raise ValueError()
    except ValueError:
        raise ValueError('Tanggal harus YYYY-MM-DD yang valid.') from None
    start = datetime.combine(day, parse_time(jam), tzinfo=WIB)
    if start < now.replace(second=0, microsecond=0):
        raise ValueError('Jam event sudah lewat. Untuk besok, isi tanggal:YYYY-MM-DD.')
    if start > now + timedelta(days=365):
        raise ValueError('Jadwal maksimal satu tahun ke depan.')
    return start


class RaidStore(SalaryStoreMixin, RedeemStoreMixin, QuestStoreMixin):
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS raid_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
                message_id TEXT, leader_id TEXT NOT NULL,
                kind TEXT NOT NULL, idx TEXT, starts_at TEXT NOT NULL,
                place TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'publishing',
                created_at TEXT NOT NULL, closed_at TEXT, closed_by TEXT
            );
            CREATE TABLE IF NOT EXISTS raid_participants (
                event_id INTEGER NOT NULL REFERENCES raid_events(id),
                user_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
                updated_at TEXT NOT NULL, verified_by TEXT,
                PRIMARY KEY (event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS raid_points (
                event_id INTEGER NOT NULL REFERENCES raid_events(id),
                guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
                points INTEGER NOT NULL CHECK (points>0), awarded_at TEXT NOT NULL,
                PRIMARY KEY (event_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS raid_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES raid_events(id),
                actor_id TEXT NOT NULL, target_id TEXT,
                action TEXT NOT NULL, at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS raid_events_guild ON raid_events(guild_id, status);
            CREATE INDEX IF NOT EXISTS raid_points_guild ON raid_points(guild_id, user_id);
            CREATE TABLE IF NOT EXISTS raid_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interaction_id TEXT NOT NULL UNIQUE, guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL, points INTEGER NOT NULL CHECK (points>0),
                detail TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS raid_contributions_guild ON raid_contributions(guild_id,user_id);
            CREATE TABLE IF NOT EXISTS raid_deductions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interaction_id TEXT NOT NULL UNIQUE,guild_id TEXT NOT NULL,user_id TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points>0),detail TEXT NOT NULL,
                actor_id TEXT NOT NULL,created_at TEXT NOT NULL,voided INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS raid_deductions_guild ON raid_deductions(guild_id,user_id);
            CREATE TABLE IF NOT EXISTS raid_wiped_awards (
                event_id INTEGER NOT NULL REFERENCES raid_events(id),
                user_id TEXT NOT NULL, PRIMARY KEY(event_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS raid_point_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, interaction_id TEXT NOT NULL UNIQUE,
                guild_id TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
                event_awards INTEGER NOT NULL, contributions INTEGER NOT NULL
            );
        ''')
        self.init_redeem_tables()
        self.init_salary_tables()
        self.init_quest_tables()
        with self.db:
            # Replace the old CHECK(points=1) without losing existing awards.
            schema = self.db.execute("SELECT sql FROM sqlite_master WHERE name='raid_points'").fetchone()[0]
            if re.search(r'CHECK\s*\(\s*points\s*=\s*1\s*\)', schema, re.I):
                self.db.execute('ALTER TABLE raid_points RENAME TO raid_points_legacy')
                self.db.execute('''CREATE TABLE raid_points (
                    event_id INTEGER NOT NULL REFERENCES raid_events(id), guild_id TEXT NOT NULL,
                    user_id TEXT NOT NULL, points INTEGER NOT NULL CHECK(points>0),
                    awarded_at TEXT NOT NULL, PRIMARY KEY(event_id,user_id))''')
                self.db.execute('INSERT INTO raid_points SELECT * FROM raid_points_legacy')
                self.db.execute('DROP TABLE raid_points_legacy')
                self.db.execute('CREATE INDEX raid_points_guild ON raid_points(guild_id,user_id)')
            if 'voided' not in {row['name'] for row in self.db.execute('PRAGMA table_info(raid_contributions)')}:
                self.db.execute('ALTER TABLE raid_contributions ADD COLUMN voided INTEGER NOT NULL DEFAULT 0')
            if 'deductions' not in {row['name'] for row in self.db.execute('PRAGMA table_info(raid_point_resets)')}:
                self.db.execute('ALTER TABLE raid_point_resets ADD COLUMN deductions INTEGER NOT NULL DEFAULT 0')
            if 'redemptions' not in {row['name'] for row in self.db.execute('PRAGMA table_info(raid_point_resets)')}:
                self.db.execute('ALTER TABLE raid_point_resets ADD COLUMN redemptions INTEGER NOT NULL DEFAULT 0')
            if 'quest_rewards' not in {row['name'] for row in self.db.execute('PRAGMA table_info(raid_point_resets)')}:
                self.db.execute('ALTER TABLE raid_point_resets ADD COLUMN quest_rewards INTEGER NOT NULL DEFAULT 0')
        # Upgrade older six-status raids and reconcile one point per accepted member.
        # Idempotent: restarting never adds a second point for an event/user pair.
        with self.db:
            self.db.execute("UPDATE raid_participants SET status='accepted' WHERE status='attended'")
            self.db.execute("UPDATE raid_participants SET status='absent' WHERE status IN ('no_show','rejected')")
            self.db.execute('''DELETE FROM raid_points WHERE NOT EXISTS (
                SELECT 1 FROM raid_participants p JOIN raid_events e ON e.id=p.event_id
                WHERE p.event_id=raid_points.event_id AND p.user_id=raid_points.user_id
                AND p.status='accepted' AND e.status IN ('open','completed'))''')
            self.db.execute('''INSERT OR IGNORE INTO raid_points
                SELECT e.id,e.guild_id,p.user_id,
                    CASE e.kind WHEN 'trex' THEN 40 WHEN 'savage' THEN 50 ELSE 35 END,p.updated_at
                FROM raid_participants p JOIN raid_events e ON e.id=p.event_id
                WHERE p.status='accepted' AND e.status IN ('open','completed')
                AND NOT EXISTS (SELECT 1 FROM raid_wiped_awards w
                    WHERE w.event_id=p.event_id AND w.user_id=p.user_id)''')
            self.db.execute('''UPDATE raid_points SET points=(SELECT
                CASE kind WHEN 'trex' THEN 40 WHEN 'savage' THEN 50 ELSE 35 END
                FROM raid_events WHERE id=raid_points.event_id)''')

    def event(self, guild_id, event_id):
        row = self.db.execute('SELECT * FROM raid_events WHERE id=? AND guild_id=?',
                              (event_id, str(guild_id))).fetchone()
        if row is None:
            raise ValueError('Event tidak ditemukan di server ini.')
        return row

    def _open(self, guild_id, event_id):
        event = self.event(guild_id, event_id)
        if event['status'] != 'open':
            raise ValueError('Event sudah ditutup atau belum selesai dipublikasikan.')
        return event

    def _audit(self, event_id, actor, action, target=None):
        self.db.execute('INSERT INTO raid_audit(event_id,actor_id,target_id,action,at) VALUES(?,?,?,?,?)',
                        (event_id, str(actor), str(target) if target else None,
                         action, datetime.now(WIB).isoformat()))

    def create(self, guild_id, channel_id, leader_id, kind, start, place, index=None):
        if kind not in KINDS or (kind == 'trex' and index not in SUPPORTED_INDICES):
            raise ValueError('Jenis event atau index tidak valid.')
        place = place.strip()
        if not 1 <= len(place) <= 200:
            raise ValueError('Tempat harus 1–200 karakter.')
        with self.db:
            cur = self.db.execute('''INSERT INTO raid_events
                (guild_id,channel_id,leader_id,kind,idx,starts_at,place,created_at)
                VALUES(?,?,?,?,?,?,?,?)''', (str(guild_id), str(channel_id), str(leader_id),
                kind, index if kind == 'trex' else None, start.isoformat(), place,
                datetime.now(WIB).isoformat()))
            event_id = cur.lastrowid
            self._audit(event_id, leader_id, 'create')
        return event_id

    def publish(self, guild_id, event_id, message_id):
        with self.db:
            self.event(guild_id, event_id)
            self.db.execute("UPDATE raid_events SET message_id=?,status='open' WHERE id=? AND status='publishing'",
                            (str(message_id), event_id))

    def publication_failed(self, guild_id, event_id):
        with self.db:
            self.event(guild_id, event_id)
            self.db.execute("UPDATE raid_events SET status='failed' WHERE id=? AND status='publishing'", (event_id,))

    def open_events(self, guild_id):
        return self.db.execute("SELECT * FROM raid_events WHERE guild_id=? AND status='open' AND message_id IS NOT NULL",
                               (str(guild_id),)).fetchall()

    def recent_events(self, guild_id):
        return self.db.execute("SELECT * FROM raid_events WHERE guild_id=? AND status IN ('open','completed','cancelled') ORDER BY id DESC LIMIT 10",
                               (str(guild_id),)).fetchall()

    def participants(self, event_id):
        return self.db.execute('SELECT * FROM raid_participants WHERE event_id=? ORDER BY user_id', (event_id,)).fetchall()

    def respond(self, guild_id, event_id, user_id, name, attending):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            event = self._open(guild_id, event_id)
            old = self.db.execute('SELECT status FROM raid_participants WHERE event_id=? AND user_id=?',
                                  (event_id, str(user_id))).fetchone()
            if attending and old and old['status'] == 'accepted':
                return 'accepted'
            status = 'pending' if attending else 'absent'
            self.db.execute('''INSERT INTO raid_participants VALUES(?,?,?,?,?,NULL)
                ON CONFLICT(event_id,user_id) DO UPDATE SET name=excluded.name,
                status=excluded.status,updated_at=excluded.updated_at,verified_by=NULL''',
                (event_id, str(user_id), name[:100], status, datetime.now(WIB).isoformat()))
            self.db.execute('DELETE FROM raid_points WHERE event_id=? AND user_id=?',
                            (event_id, str(user_id)))
            self._audit(event_id, user_id, status, user_id)
        return status

    def moderate(self, guild_id, event_id, user_id, actor_id, action, now=None):
        allowed = {'accepted': {'pending', 'accepted'},
                   'absent': {'pending', 'accepted', 'absent'}}
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            event = self._open(guild_id, event_id)
            row = self.db.execute('SELECT status FROM raid_participants WHERE event_id=? AND user_id=?',
                                  (event_id, str(user_id))).fetchone()
            if action not in allowed or row is None or row['status'] not in allowed[action]:
                raise ValueError('Status peserta sudah berubah atau tidak cocok. Muat ulang panel leader.')
            self.db.execute('''UPDATE raid_participants SET status=?,verified_by=?,updated_at=?
                WHERE event_id=? AND user_id=?''', (action, str(actor_id), datetime.now(WIB).isoformat(), event_id, str(user_id)))
            if action == 'accepted':
                self.db.execute('''INSERT OR IGNORE INTO raid_points
                    SELECT ?,?,?,?,? WHERE NOT EXISTS (
                        SELECT 1 FROM raid_wiped_awards WHERE event_id=? AND user_id=?)''',
                    (event_id, str(guild_id), str(user_id), EVENT_POINTS[event['kind']],
                     datetime.now(WIB).isoformat(), event_id, str(user_id)))
            else:
                self.db.execute('DELETE FROM raid_points WHERE event_id=? AND user_id=?',
                                (event_id, str(user_id)))
            self._audit(event_id, actor_id, action, user_id)

    def finish(self, guild_id, event_id, actor_id, cancel=False, now=None):
        now = now or datetime.now(WIB)
        # Closing keeps existing points. Cancelling reverses all awards atomically.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            event = self._open(guild_id, event_id)
            if not cancel and now < datetime.fromisoformat(event['starts_at']):
                raise ValueError('Event baru bisa diselesaikan setelah jam mulainya.')
            count = self.db.execute('SELECT COUNT(*) FROM raid_points WHERE event_id=?', (event_id,)).fetchone()[0]
            if cancel:
                self.db.execute('DELETE FROM raid_points WHERE event_id=?', (event_id,))
                count = 0
            status = 'cancelled' if cancel else 'completed'
            self.db.execute('UPDATE raid_events SET status=?,closed_at=?,closed_by=? WHERE id=?',
                            (status, now.isoformat(), str(actor_id), event_id))
            self._audit(event_id, actor_id, status)
        return count

    def add_contribution(self, guild_id, user_id, points, detail, actor_id, interaction_id):
        if type(points) is not int or not 1 <= points <= 1000000:
            raise ValueError('Point harus bilangan bulat 1–1000000.')
        detail = detail.strip()
        if not 1 <= len(detail) <= 500:
            raise ValueError('Detail kontribusi harus 1–500 karakter.')
        values = (str(interaction_id), str(guild_id), str(user_id), points, detail, str(actor_id))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM raid_contributions WHERE interaction_id=?',
                                  (str(interaction_id),)).fetchone()
            if old:
                if tuple(old[k] for k in ('interaction_id', 'guild_id', 'user_id', 'points', 'detail', 'actor_id')) != values:
                    raise ValueError('Permintaan kontribusi sudah dipakai untuk data berbeda.')
                return old['id']
            cur = self.db.execute('''INSERT INTO raid_contributions
                (interaction_id,guild_id,user_id,points,detail,actor_id,created_at)
                VALUES(?,?,?,?,?,?,?)''', (*values, datetime.now(WIB).isoformat()))
            return cur.lastrowid

    def remove_points(self, guild_id, user_id, points, detail, actor_id, interaction_id):
        if type(points) is not int or not 1 <= points <= 1000000:
            raise ValueError('Point harus bilangan bulat 1–1000000.')
        detail = detail.strip()
        if not 1 <= len(detail) <= 500:
            raise ValueError('Alasan pengurangan harus 1–500 karakter.')
        values = (str(interaction_id), str(guild_id), str(user_id), points, detail, str(actor_id))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM raid_deductions WHERE interaction_id=?',
                                  (str(interaction_id),)).fetchone()
            if old:
                if tuple(old[k] for k in ('interaction_id', 'guild_id', 'user_id', 'points', 'detail', 'actor_id')) != values:
                    raise ValueError('Permintaan pengurangan sudah dipakai untuk data berbeda.')
                return old['id']
            cur = self.db.execute('''INSERT INTO raid_deductions
                (interaction_id,guild_id,user_id,points,detail,actor_id,created_at)
                VALUES(?,?,?,?,?,?,?)''', (*values, datetime.now(WIB).isoformat()))
            return cur.lastrowid

    def _point_entries(self, guild_id, user_id=None):
        extra = ' AND user_id=?' if user_id is not None else ''
        sql = f'''SELECT user_id,points,1 AS events,0 AS contributions,points AS event_points,
                0 AS contribution_points,0 AS deduction_points,0 AS redeem_points,0 AS quests,0 AS quest_points
            FROM raid_points WHERE guild_id=?{extra}
            UNION ALL
            SELECT user_id,points,0,1,0,points,0,0,0,0 FROM raid_contributions WHERE guild_id=? AND voided=0{extra}
            UNION ALL
            SELECT user_id,-points,0,0,0,0,points,0,0,0 FROM raid_deductions WHERE guild_id=? AND voided=0{extra}
            UNION ALL
            SELECT user_id,-price,0,0,0,0,0,price,0,0 FROM redeem_orders
                WHERE guild_id=? AND voided=0 AND status IN ('pending','fulfilled'){extra}
            UNION ALL
            SELECT user_id,points,0,0,0,0,0,0,0,0 FROM weekly_salary_payments WHERE guild_id=? AND voided=0{extra}
            UNION ALL
            SELECT user_id,points,0,0,0,0,0,0,1,points FROM guild_quest_rewards WHERE guild_id=? AND voided=0{extra}'''
        values = [str(guild_id)] if user_id is None else [str(guild_id), str(user_id)]
        return sql, values * 6

    def leaderboard(self, guild_id, page=0):
        entries, params = self._point_entries(guild_id)
        return self.db.execute(f'''SELECT user_id,SUM(points) AS points,SUM(events) AS events,
            SUM(contributions) AS contributions,SUM(quests) AS quests FROM ({entries})
            GROUP BY user_id ORDER BY points DESC,user_id LIMIT 10 OFFSET ?''', (*params, page * 10)).fetchall()

    def point_summary(self, guild_id, user_id):
        entries, params = self._point_entries(guild_id, user_id)
        return self.db.execute(f'''SELECT COALESCE(SUM(points),0) AS points,
            COALESCE(SUM(events),0) AS events,COALESCE(SUM(contributions),0) AS contributions,
            COALESCE(SUM(event_points),0) AS event_points,COALESCE(SUM(contribution_points),0) AS contribution_points,
            COALESCE(SUM(deduction_points),0) AS deduction_points,COALESCE(SUM(redeem_points),0) AS redeem_points,
            COALESCE(SUM(quests),0) AS quests,COALESCE(SUM(quest_points),0) AS quest_points FROM ({entries})''', params).fetchone()

    def wipe_points(self, guild_id, actor_id, interaction_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM raid_point_resets WHERE interaction_id=?',
                                  (str(interaction_id),)).fetchone()
            if old:
                if old['guild_id'] != str(guild_id) or old['actor_id'] != str(actor_id):
                    raise ValueError('Permintaan reset sudah dipakai untuk data berbeda.')
                return old
            event_count = self.db.execute('SELECT COUNT(*) FROM raid_points WHERE guild_id=?', (str(guild_id),)).fetchone()[0]
            contributions = self.db.execute('SELECT COUNT(*) FROM raid_contributions WHERE guild_id=? AND voided=0', (str(guild_id),)).fetchone()[0]
            deductions = self.db.execute('SELECT COUNT(*) FROM raid_deductions WHERE guild_id=? AND voided=0', (str(guild_id),)).fetchone()[0]
            redemptions = self.db.execute("SELECT COUNT(*) FROM redeem_orders WHERE guild_id=? AND voided=0 AND status IN ('pending','fulfilled')", (str(guild_id),)).fetchone()[0]
            quest_rewards = self.db.execute('SELECT COUNT(*) FROM guild_quest_rewards WHERE guild_id=? AND voided=0', (str(guild_id),)).fetchone()[0]
            self.db.execute('''INSERT OR IGNORE INTO raid_wiped_awards
                SELECT event_id,user_id FROM raid_points WHERE guild_id=?''', (str(guild_id),))
            self.db.execute('DELETE FROM raid_points WHERE guild_id=?', (str(guild_id),))
            self.db.execute('UPDATE raid_contributions SET voided=1 WHERE guild_id=?', (str(guild_id),))
            self.db.execute('UPDATE raid_deductions SET voided=1 WHERE guild_id=?', (str(guild_id),))
            self.db.execute('UPDATE redeem_orders SET voided=1 WHERE guild_id=?', (str(guild_id),))
            self.db.execute('UPDATE weekly_salary_payments SET voided=1 WHERE guild_id=?', (str(guild_id),))
            self.db.execute('UPDATE guild_quest_rewards SET voided=1 WHERE guild_id=?', (str(guild_id),))
            cur = self.db.execute('''INSERT INTO raid_point_resets
                (interaction_id,guild_id,actor_id,created_at,event_awards,contributions,deductions,redemptions,quest_rewards)
                VALUES(?,?,?,?,?,?,?,?,?)''', (str(interaction_id), str(guild_id), str(actor_id),
                                       datetime.now(WIB).isoformat(), event_count, contributions, deductions, redemptions, quest_rewards))
            return self.db.execute('SELECT * FROM raid_point_resets WHERE id=?', (cur.lastrowid,)).fetchone()

    def event_credit(self, guild_id, event_id, user_id):
        self.event(guild_id, event_id)
        row = self.db.execute('SELECT points FROM raid_points WHERE event_id=? AND user_id=?',
                              (event_id, str(user_id))).fetchone()
        return row['points'] if row else 0

    def close(self):
        self.db.close()
