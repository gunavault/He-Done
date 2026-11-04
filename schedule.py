"""One-off registered WIB windows and durable receipts; no Discord dependency."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import re
import math
import sqlite3
from urllib.parse import quote

WIB = ZoneInfo('Asia/Jakarta')
SUPPORTED_INDICES = tuple(f'{main}.{sub}' for main in range(1, 9) for sub in range(1, 6))
VOICE_INDICES = ('3.1', '3.2', '4.1', '4.3')
WORLD_BOSS_PLACES = ('Volcano', 'Snowfield', 'Tundra', 'Swamp', 'Desert', 'Tropical')
DEFAULT_SLOTS = (('3.1', time(11, 20)), ('3.2', time(12, 47)),
                 ('3.1', time(18, 0)), ('3.2', time(19, 27)))
DEFAULT_OFFSETS = (30, 15, 5, 0)
GRACE_SECONDS = 60


def display_place(value):
    value = value.replace('\\', '\\\\').replace('@', '@\u200b')
    return re.sub(r'([`*_~|<>])', r'\\\1', value)


def normalize_place(value):
    value = ' '.join(value.split())
    for place in WORLD_BOSS_PLACES:
        if value.casefold() == place.casefold():
            return place
    raise ValueError('Tempat harus salah satu dari: ' + ', '.join(WORLD_BOSS_PLACES) + '.')


def parse_time(value):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Jam harus HH:MM WIB, contoh 18:00.')
    return time.fromisoformat(value)


def parse_times(value):
    result = tuple(parse_time(item.strip()) for item in value.split(','))
    if len(set(result)) != len(result):
        raise ValueError('Jam spawn untuk satu index tidak boleh duplikat.')
    return result


def parse_offsets(value):
    try:
        offsets = tuple(int(item.strip()) for item in value.split(','))
    except ValueError:
        raise ValueError('REMINDER_MINUTES harus angka dipisah koma, contoh 30,15,5,0.') from None
    if not offsets or len(set(offsets)) != len(offsets) or any(n < 0 or n > 1440 for n in offsets):
        raise ValueError('REMINDER_MINUTES harus unik dan berada antara 0–1440 menit.')
    return tuple(sorted(offsets, reverse=True))


@dataclass(frozen=True)
class Reminder:
    index: str
    start: datetime
    minutes_before: int
    end: datetime | None = None
    place: str = ''

    @property
    def trigger(self):
        return self.start - timedelta(minutes=self.minutes_before)

    @property
    def key(self):
        key = f'{self.index}|{self.start.isoformat()}|{self.minutes_before}'
        return f'{quote(self.place.casefold(), safe="")}|{key}' if self.place else key

    def is_due(self, now):
        # Missed countdowns must not arrive hours late after downtime.
        return self.trigger <= now < self.trigger + timedelta(seconds=GRACE_SECONDS)

    def message(self):
        label = f'H-{self.minutes_before} menit' if self.minutes_before else 'Waktunya spawn'
        window = (f'{self.start:%H:%M}–{self.end:%H:%M} WIB'
                  if self.end else f'{self.start:%H:%M} WIB')
        return (f'🦖 **T-Rex — Index {self.index} | {label}**\n'
                f'Perkiraan spawn T-Rex: **{window}**.\n'
                + (f'Tempat: {display_place(self.place)}\n' if self.place else '')
                + f'Tanggal spawn: {self.start:%d-%m-%Y}'
                + (f'–{self.end:%d-%m-%Y}' if self.end and self.end.date() != self.start.date() else ''))


def daily_reminders(day: date, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS):
    reminders = []
    for index, start_time in slots:
        start = datetime.combine(day, start_time, tzinfo=WIB)
        for offset in offsets:
            reminders.append(Reminder(index, start, offset))
    return sorted(reminders, key=lambda r: r.trigger)


@dataclass(frozen=True)
class Timer:
    index: str
    observed: datetime
    start: datetime
    end: datetime
    place: str = ''


def calculate_timer(index, waktu, tanggal=None, now=None, place=''):
    if index not in SUPPORTED_INDICES:
        raise ValueError('Index harus 1.1–8.5: angka utama 1–8 dan sub-index .1–.5.')
    place = normalize_place(place) if place.strip() else ''
    now = (now or datetime.now(WIB)).astimezone(WIB)
    at = parse_time(waktu)
    day = now.date()
    if tanggal:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', tanggal):
            raise ValueError('Tanggal harus YYYY-MM-DD.')
        try:
            day = date.fromisoformat(tanggal)
        except ValueError:
            raise ValueError('Tanggal tidak valid.') from None
    observed = datetime.combine(day, at, tzinfo=WIB)
    if observed > now:
        raise ValueError('Waktu muncul belum terjadi. Untuk kemarin, isi tanggal:YYYY-MM-DD.')
    return Timer(index, observed, observed + timedelta(minutes=400), observed + timedelta(minutes=420), place)


def effective_reminders(day, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS, timers=()):
    """Each registered timer produces exactly its original window, never a daily copy."""
    overridden = {timer.index for timer in timers}
    events = daily_reminders(day, tuple(slot for slot in slots if slot[0] not in overridden), offsets)
    for timer in timers:
        if day != timer.start.date():
            continue
        events.extend(Reminder(timer.index, timer.start, offset, timer.end, timer.place) for offset in offsets)
    return sorted(events, key=lambda event: event.trigger)


def next_spawn(now, slots=DEFAULT_SLOTS, timers=()):
    """Closest scheduled spawn at or after now, including tomorrow's first spawn."""
    now = now.astimezone(WIB)
    candidates = [event for delta in (-1, 0, 1)
                  for event in effective_reminders(now.date() + timedelta(days=delta), slots, offsets=(0,), timers=timers)
                  if event.start >= now or (event.end and event.end > now)]
    if not candidates:
        raise ValueError('Belum ada jadwal spawn yang dikonfigurasi.')
    return min(candidates, key=lambda event: event.start)


def next_spawn_message(now, slots=DEFAULT_SLOTS, timers=()):
    now = now.astimezone(WIB)
    event = next_spawn(now, slots, timers)
    seconds = max(0, math.ceil((event.start - now).total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    parts = [f'{value} {unit}' for value, unit in
             ((hours, 'jam'), (minutes, 'menit'), (seconds, 'detik')) if value]
    remaining = ' '.join(parts) if parts else ('Sedang dalam jendela spawn'
                if event.end and event.start < now else 'Sekarang')
    day = ('Hari ini' if event.start.date() == now.date() else
           'Kemarin' if event.start.date() < now.date() else 'Besok')
    window = (f'{event.start:%H:%M}–{event.end:%H:%M} WIB'
              if event.end else f'{event.start:%H:%M} WIB')
    return (f'🦖 **Jadwal T-Rex terdekat**\n'
            f'Index: **{event.index}**\n'
            + (f'Tempat: {display_place(event.place)}\n' if event.place else '')
            + f'Spawn: **{window}**\n'
            f'Tanggal: {day}, {event.start:%d-%m-%Y}\n'
            f'Sisa waktu: **{remaining}**')


def due_reminders(now, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS, timers=()):
    now = now.astimezone(WIB)
    # Include tomorrow for H-30 before midnight; yesterday covers late polling at midnight.
    for delta in (-1, 0, 1):
        for reminder in effective_reminders(now.date() + timedelta(days=delta), slots, offsets, timers):
            if reminder.is_due(now):
                yield reminder


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        # Legacy job/receipt tables are retained; island-aware timers use their own table.
        self.db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
            event_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS timer_overrides (
            guild_id TEXT NOT NULL, idx TEXT NOT NULL, observed TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY (guild_id, idx))''')
        self.db.commit()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS worldboss_timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,
                place TEXT NOT NULL,idx TEXT NOT NULL,observed TEXT NOT NULL,
                start TEXT NOT NULL,end TEXT NOT NULL,UNIQUE(guild_id,place,idx)
            );
            CREATE TABLE IF NOT EXISTS worldboss_migrations (name TEXT PRIMARY KEY);
        ''')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not self.db.execute("SELECT 1 FROM worldboss_migrations WHERE name='island-index-v1'").fetchone():
                # User requested a fresh start for old index-only world boss timers.
                # Clear only the obsolete timer table, never point/raid/redeem data.
                self.db.execute('DELETE FROM timer_overrides')
                self.db.execute("INSERT INTO worldboss_migrations VALUES('island-index-v1')")

    def set_timer(self, guild_id, timer):
        place = normalize_place(timer.place) if timer.place else ''
        with self.db:
            self.db.execute('''INSERT INTO worldboss_timers(guild_id,place,idx,observed,start,end)
                VALUES(?,?,?,?,?,?) ON CONFLICT(guild_id,place,idx) DO UPDATE SET
                observed=excluded.observed,start=excluded.start,end=excluded.end''',
                (str(guild_id), place, timer.index, timer.observed.isoformat(), timer.start.isoformat(), timer.end.isoformat()))

    def timers(self, guild_id):
        rows = self.db.execute('SELECT idx, observed, start, end, place FROM worldboss_timers WHERE guild_id=? ORDER BY place,idx',
                               (str(guild_id),)).fetchall()
        return tuple(Timer(row[0], *(datetime.fromisoformat(value) for value in row[1:4]), row[4]) for row in rows)

    def was_sent(self, key):
        return self.db.execute('SELECT 1 FROM deliveries WHERE event_key=?', (key,)).fetchone() is not None

    def mark_sent(self, key, sent_at):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?)', (key, sent_at.isoformat()))

    def close(self):
        self.db.close()
