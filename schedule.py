"""Daily WIB reminders and durable delivery receipts; no Discord dependency."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import re
import math
import sqlite3

WIB = ZoneInfo('Asia/Jakarta')
SUPPORTED_INDICES = ('3.1', '3.2', '4.1', '4.3')
DEFAULT_SLOTS = (('3.1', time(11, 20)), ('3.2', time(12, 47)),
                 ('3.1', time(18, 0)), ('3.2', time(19, 27)))
DEFAULT_OFFSETS = (30, 15, 5, 0)
GRACE_SECONDS = 60


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

    @property
    def trigger(self):
        return self.start - timedelta(minutes=self.minutes_before)

    @property
    def key(self):
        return f'{self.index}|{self.start.isoformat()}|{self.minutes_before}'

    def is_due(self, now):
        # Missed countdowns must not arrive hours late after downtime.
        return self.trigger <= now < self.trigger + timedelta(seconds=GRACE_SECONDS)

    def message(self):
        label = f'H-{self.minutes_before} menit' if self.minutes_before else 'Waktunya spawn'
        window = (f'{self.start:%H:%M}–{self.end:%H:%M} WIB'
                  if self.end else f'{self.start:%H:%M} WIB')
        return (f'🦖 **T-Rex — Index {self.index} | {label}**\n'
                f'Perkiraan spawn T-Rex: **{window}**.\n'
                f'Tanggal spawn: {self.start:%d-%m-%Y}'
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


def calculate_timer(index, waktu, tanggal=None, now=None):
    if index not in SUPPORTED_INDICES:
        raise ValueError('Index harus salah satu dari: ' + ', '.join(SUPPORTED_INDICES) + '.')
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
    return Timer(index, observed, observed + timedelta(minutes=400), observed + timedelta(minutes=420))


def effective_reminders(day, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS, timers=()):
    """An updated index replaces all of that index's fallback slots, including future days."""
    overridden = {timer.index for timer in timers}
    events = daily_reminders(day, tuple(slot for slot in slots if slot[0] not in overridden), offsets)
    for timer in timers:
        start = datetime.combine(day, timer.start.timetz(), tzinfo=WIB)
        if start < timer.start:
            continue  # Don't invent an earlier occurrence before the first calculated window.
        end = start + (timer.end - timer.start)
        events.extend(Reminder(timer.index, start, offset, end) for offset in offsets)
    return sorted(events, key=lambda event: event.trigger)


def next_spawn(now, slots=DEFAULT_SLOTS, timers=()):
    """Closest scheduled spawn at or after now, including tomorrow's first spawn."""
    now = now.astimezone(WIB)
    candidates = [event for delta in (0, 1)
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
    day = 'Hari ini' if event.start.date() == now.date() else 'Besok'
    window = (f'{event.start:%H:%M}–{event.end:%H:%M} WIB'
              if event.end else f'{event.start:%H:%M} WIB')
    return (f'🦖 **Jadwal T-Rex terdekat**\n'
            f'Index: **{event.index}**\n'
            f'Spawn: **{window}**\n'
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
        # Previous 'jobs' table is left intact. Daily mode doesn't consume manual jobs.
        self.db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
            event_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS timer_overrides (
            guild_id TEXT NOT NULL, idx TEXT NOT NULL, observed TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY (guild_id, idx))''')
        self.db.commit()

    def set_timer(self, guild_id, timer):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO timer_overrides VALUES (?, ?, ?, ?, ?)',
                            (str(guild_id), timer.index, timer.observed.isoformat(),
                             timer.start.isoformat(), timer.end.isoformat()))

    def timers(self, guild_id):
        rows = self.db.execute('SELECT idx, observed, start, end FROM timer_overrides WHERE guild_id=?',
                               (str(guild_id),)).fetchall()
        return tuple(Timer(row[0], *(datetime.fromisoformat(value) for value in row[1:])) for row in rows)

    def was_sent(self, key):
        return self.db.execute('SELECT 1 FROM deliveries WHERE event_key=?', (key,)).fetchone() is not None

    def mark_sent(self, key, sent_at):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?)', (key, sent_at.isoformat()))

    def close(self):
        self.db.close()
