from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import sqlite3

WIB = ZoneInfo('Asia/Jakarta')


def calculate(waktu, tanggal=None, now=None, minimum=400, maximum=420):
    now = now or datetime.now(WIB)
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', waktu):
        raise ValueError('Waktu harus HH:MM, contoh 11:20.')
    if tanggal:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', tanggal):
            raise ValueError('Tanggal harus YYYY-MM-DD.')
        try:
            day = datetime.strptime(tanggal, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Tanggal tidak valid.') from None
    else:
        day = now.date()
    hour, minute = map(int, waktu.split(':'))
    base = datetime(day.year, day.month, day.day, hour, minute, tzinfo=WIB)
    if base > now:
        raise ValueError('Waktu catatan belum terjadi. Untuk catatan kemarin, isi tanggal.')
    start = base + timedelta(minutes=minimum)
    end = base + timedelta(minutes=maximum)
    if end <= now:
        raise ValueError('Jendela kemunculan sudah lewat. Periksa waktu dan tanggal.')
    return base, start, end


def describe(index, base, start, end):
    # Dates on both endpoints make windows spanning midnight unambiguous.
    return (f'🦖 **T-Rex — Index {index}**\n'
            f'Waktu index dicatat: {base:%d-%m-%Y %H:%M} WIB\n'
            f'T-Rex diperkirakan muncul antara **{start:%d-%m-%Y %H:%M}–'
            f'{end:%d-%m-%Y %H:%M} WIB**.')


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            idx TEXT PRIMARY KEY, base TEXT NOT NULL, start TEXT NOT NULL,
            end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending')''')
        self.db.commit()

    def put(self, index, base, start, end):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?)',
                            (index, base.isoformat(), start.isoformat(), end.isoformat(), 'pending'))

    def pending(self):
        return self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY start").fetchall()

    def mark(self, index, status):
        with self.db:
            self.db.execute('UPDATE jobs SET status=? WHERE idx=?', (status, index))

    def delete(self, index):
        with self.db:
            return self.db.execute('DELETE FROM jobs WHERE idx=?', (index,)).rowcount

    def close(self):
        self.db.close()


def times(row):
    return tuple(datetime.fromisoformat(row[key]) for key in ('base', 'start', 'end'))
