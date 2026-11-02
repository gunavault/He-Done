"""Durable manual raid events; independent of T-Rex timer tables."""
import sqlite3
from datetime import datetime, date, timedelta

from schedule import WIB, parse_time, SUPPORTED_INDICES


KINDS = {'trex': 'T-Rex', 'rift': 'Rift', 'savage': 'Savage'}
STATUSES = {
    'pending': 'Menunggu diterima', 'accepted': 'Diterima',
    'absent': 'Tidak Hadir', 'rejected': 'Ditolak',
    'attended': 'Hadir disahkan', 'no_show': 'Tidak datang',
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


class RaidStore:
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
                points INTEGER NOT NULL CHECK (points=1), awarded_at TEXT NOT NULL,
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
        ''')

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
            self._open(guild_id, event_id)
            old = self.db.execute('SELECT status FROM raid_participants WHERE event_id=? AND user_id=?',
                                  (event_id, str(user_id))).fetchone()
            if old and old['status'] == 'attended':
                raise ValueError('Kehadiran sudah disahkan. Hubungi leader untuk koreksi.')
            if attending and old and old['status'] == 'accepted':
                return 'accepted'
            status = 'pending' if attending else 'absent'
            self.db.execute('''INSERT INTO raid_participants VALUES(?,?,?,?,?,NULL)
                ON CONFLICT(event_id,user_id) DO UPDATE SET name=excluded.name,
                status=excluded.status,updated_at=excluded.updated_at,verified_by=NULL''',
                (event_id, str(user_id), name[:100], status, datetime.now(WIB).isoformat()))
            self._audit(event_id, user_id, status, user_id)
        return status

    def moderate(self, guild_id, event_id, user_id, actor_id, action, now=None):
        allowed = {'accepted': {'pending', 'rejected'},
                   'rejected': {'pending', 'accepted', 'attended', 'no_show'},
                   'attended': {'accepted', 'no_show'},
                   'no_show': {'accepted', 'attended'}}
        with self.db:
            event = self._open(guild_id, event_id)
            row = self.db.execute('SELECT status FROM raid_participants WHERE event_id=? AND user_id=?',
                                  (event_id, str(user_id))).fetchone()
            if action not in allowed or row is None or row['status'] not in allowed[action]:
                raise ValueError('Status peserta sudah berubah atau tidak cocok. Muat ulang panel leader.')
            if action in ('attended', 'no_show') and (now or datetime.now(WIB)) < datetime.fromisoformat(event['starts_at']):
                raise ValueError('Verifikasi kehadiran baru tersedia saat jam event dimulai.')
            self.db.execute('''UPDATE raid_participants SET status=?,verified_by=?,updated_at=?
                WHERE event_id=? AND user_id=?''', (action, str(actor_id), datetime.now(WIB).isoformat(), event_id, str(user_id)))
            self._audit(event_id, actor_id, action, user_id)

    def finish(self, guild_id, event_id, actor_id, cancel=False, now=None):
        now = now or datetime.now(WIB)
        # One transaction serializes closure and awards, including across process connections.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            event = self._open(guild_id, event_id)
            if not cancel and now < datetime.fromisoformat(event['starts_at']):
                raise ValueError('Event baru bisa diselesaikan setelah jam mulainya.')
            count = 0
            if not cancel:
                rows = self.db.execute("SELECT user_id FROM raid_participants WHERE event_id=? AND status='attended'", (event_id,)).fetchall()
                for row in rows:
                    self.db.execute('INSERT INTO raid_points VALUES(?,?,?,1,?)',
                                    (event_id, str(guild_id), row['user_id'], now.isoformat()))
                count = len(rows)
                self.db.execute("UPDATE raid_participants SET status='no_show',updated_at=? WHERE event_id=? AND status='accepted'",
                                (now.isoformat(), event_id))
            status = 'cancelled' if cancel else 'completed'
            self.db.execute('UPDATE raid_events SET status=?,closed_at=?,closed_by=? WHERE id=?',
                            (status, now.isoformat(), str(actor_id), event_id))
            self._audit(event_id, actor_id, status)
        return count

    def leaderboard(self, guild_id, page=0):
        return self.db.execute('''SELECT user_id,SUM(points) AS points,COUNT(*) AS events
            FROM raid_points WHERE guild_id=? GROUP BY user_id
            ORDER BY points DESC,user_id LIMIT 10 OFFSET ?''', (str(guild_id), page * 10)).fetchall()

    def close(self):
        self.db.close()
