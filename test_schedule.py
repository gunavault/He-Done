import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from schedule import WIB, Store, calculate, describe, times


class ScheduleTests(unittest.TestCase):
    def test_examples(self):
        now = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
        for base, start, end in [('11:20', '18:00', '18:20'), ('12:47', '19:27', '19:47')]:
            _, s, e = calculate(base, now=now)
            self.assertEqual((s.strftime('%H:%M'), e.strftime('%H:%M')), (start, end))

    def test_midnight(self):
        now = datetime(2026, 10, 31, 0, 5, tzinfo=WIB)
        b, s, e = calculate('17:10', '2026-10-30', now=now)
        self.assertEqual((s.day, s.hour, s.minute), (30, 23, 50))
        self.assertEqual((e.day, e.hour, e.minute), (31, 0, 10))
        self.assertIn('31-10-2026 00:10', describe('3.1', b, s, e))

    def test_future_rejected(self):
        with self.assertRaises(ValueError):
            calculate('11:20', now=datetime(2026, 10, 30, 10, 0, tzinfo=WIB))

    def test_expired_rejected(self):
        with self.assertRaises(ValueError):
            calculate('11:20', now=datetime(2026, 10, 30, 18, 20, tzinfo=WIB))

    def test_invalid_input(self):
        for value in ['24:00', '1:20', '11:70', '@everyone']:
            with self.assertRaises(ValueError):
                calculate(value)
        with self.assertRaises(ValueError):
            calculate('11:20', '2026-02-30')

    def test_persistence_replacement_and_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.sqlite3'
            now = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            first = calculate('11:20', now=now)
            second = calculate('12:47', now=now)
            store = Store(path)
            store.put('3.1', *first)
            store.close()
            store = Store(path)
            self.assertEqual(times(store.pending()[0]), first)
            store.put('3.1', *second)
            self.assertEqual(len(store.pending()), 1)
            self.assertEqual(times(store.pending()[0]), second)
            store.mark('3.1', 'sent')
            store.close()
            store = Store(path)
            self.assertEqual(len(store.pending()), 0)
            store.put('3.2', *first)
            self.assertEqual(store.delete('3.2'), 1)
            self.assertEqual(store.delete('3.2'), 0)
            store.close()


if __name__ == '__main__':
    unittest.main()
