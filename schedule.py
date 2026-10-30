"""Daily WIB reminders and durable delivery receipts; no Discord dependency."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import re
import math
import sqlite3

WIB = ZoneInfo('Asia/Jakarta')
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
        return (f'🦖 **T-Rex — Index {self.index} | {label}**\n'
                f'Jadwal spawn T-Rex: **{self.start:%H:%M} WIB**.\n'
                f'Tanggal spawn: {self.start:%d-%m-%Y}')


def daily_reminders(day: date, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS):
    reminders = []
    for index, start_time in slots:
        start = datetime.combine(day, start_time, tzinfo=WIB)
        for offset in offsets:
            reminders.append(Reminder(index, start, offset))
    return sorted(reminders, key=lambda r: r.trigger)


def next_spawn(now, slots=DEFAULT_SLOTS):
    """Closest scheduled spawn at or after now, including tomorrow's first spawn."""
    now = now.astimezone(WIB)
    candidates = [event for delta in (0, 1)
                  for event in daily_reminders(now.date() + timedelta(days=delta), slots, offsets=(0,))
                  if event.start >= now]
    if not candidates:
        raise ValueError('Belum ada jadwal spawn yang dikonfigurasi.')
    return min(candidates, key=lambda event: event.start)


def next_spawn_message(now, slots=DEFAULT_SLOTS):
    now = now.astimezone(WIB)
    event = next_spawn(now, slots)
    seconds = max(0, math.ceil((event.start - now).total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    parts = [f'{value} {unit}' for value, unit in
             ((hours, 'jam'), (minutes, 'menit'), (seconds, 'detik')) if value]
    remaining = ' '.join(parts) if parts else 'Sekarang'
    day = 'Hari ini' if event.start.date() == now.date() else 'Besok'
    return (f'🦖 **Jadwal T-Rex terdekat**\n'
            f'Index: **{event.index}**\n'
            f'Spawn: **{event.start:%H:%M} WIB**\n'
            f'Tanggal: {day}, {event.start:%d-%m-%Y}\n'
            f'Sisa waktu: **{remaining}**')


def due_reminders(now, slots=DEFAULT_SLOTS, offsets=DEFAULT_OFFSETS):
    now = now.astimezone(WIB)
    # Include tomorrow for H-30 before midnight; yesterday covers late polling at midnight.
    for delta in (-1, 0, 1):
        for reminder in daily_reminders(now.date() + timedelta(days=delta), slots, offsets):
            if reminder.is_due(now):
                yield reminder


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        # Previous 'jobs' table is left intact. Daily mode doesn't consume manual jobs.
        self.db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
            event_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL)''')
        self.db.commit()

    def was_sent(self, key):
        return self.db.execute('SELECT 1 FROM deliveries WHERE event_key=?', (key,)).fetchone() is not None

    def mark_sent(self, key, sent_at):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO deliveries VALUES (?, ?)', (key, sent_at.isoformat()))

    def close(self):
        self.db.close()
