import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from schedule import (WIB, Store, daily_reminders, due_reminders, parse_time,
                      parse_offsets, parse_times)


class ScheduleTests(unittest.TestCase):
    def test_all_sixteen_trigger_times(self):
        events = daily_reminders(date(2026, 10, 30))
        actual = [(e.index, e.minutes_before, e.trigger.strftime('%H:%M')) for e in events]
        self.assertEqual(actual, [
            ('3.1', 30, '10:50'), ('3.1', 15, '11:05'), ('3.1', 5, '11:15'), ('3.1', 0, '11:20'),
            ('3.2', 30, '12:17'), ('3.2', 15, '12:32'), ('3.2', 5, '12:42'), ('3.2', 0, '12:47'),
            ('3.1', 30, '17:30'), ('3.1', 15, '17:45'), ('3.1', 5, '17:55'), ('3.1', 0, '18:00'),
            ('3.2', 30, '18:57'), ('3.2', 15, '19:12'), ('3.2', 5, '19:22'), ('3.2', 0, '19:27')])
        self.assertIn('11:20 WIB', events[0].message())
        self.assertIn('19:27 WIB', events[-1].message())

    def test_trigger_boundaries_and_skip_stale(self):
        r = daily_reminders(date(2026, 10, 30))[0]
        self.assertFalse(r.is_due(r.trigger - timedelta(microseconds=1)))
        self.assertTrue(r.is_due(r.trigger))
        self.assertTrue(r.is_due(r.trigger + timedelta(seconds=59)))
        self.assertFalse(r.is_due(r.trigger + timedelta(seconds=60)))
        self.assertEqual(list(due_reminders(r.trigger + timedelta(minutes=5))), [])

    def test_daily_recurrence_has_new_receipt_key(self):
        today = daily_reminders(date(2026, 10, 30))
        tomorrow = daily_reminders(date(2026, 10, 31))
        self.assertTrue(all(a.key != b.key for a, b in zip(today, tomorrow)))
        self.assertEqual([r.trigger.time() for r in today], [r.trigger.time() for r in tomorrow])

    def test_cross_midnight_early_reminder(self):
        now = datetime(2026, 10, 30, 23, 40, tzinfo=WIB)
        due = list(due_reminders(now, slots=(('3.1', time(0, 10)),), offsets=(30,)))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].start.date(), date(2026, 10, 31))
        self.assertEqual(due[0].minutes_before, 30)

    def test_utc_clock_uses_wib(self):
        due = list(due_reminders(datetime(2026, 10, 30, 10, 30, tzinfo=timezone.utc)))
        self.assertEqual(len(due), 1)
        self.assertEqual((due[0].index, due[0].minutes_before), ('3.1', 30))

    def test_midnight_early_reminder_message_shows_spawn_date(self):
        reminder = daily_reminders(date(2026, 10, 31), slots=(('3.1', time(0, 10)),))[0]
        self.assertIn('31-10-2026', reminder.message())
        self.assertIn('00:10 WIB', reminder.message())

    def test_configuration(self):
        self.assertEqual(parse_time('19:27'), time(19, 27))
        self.assertEqual(parse_times('11:20,18:00'), (time(11, 20), time(18, 0)))
        with self.assertRaises(ValueError):
            parse_times('11:20,11:20')
        self.assertEqual(parse_offsets('5, 30, 15'), (30, 15, 5))
        for value in ('24:00', '1:20', '11:70'):
            with self.assertRaises(ValueError):
                parse_time(value)
        for value in ('', '5,5', '-1', 'abc', '1441'):
            with self.assertRaises(ValueError):
                parse_offsets(value)

    def test_receipt_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'receipt.sqlite3'
            event = daily_reminders(date(2026, 10, 30))[0]
            store = Store(path)
            self.assertFalse(store.was_sent(event.key))
            store.mark_sent(event.key, event.trigger)
            store.mark_sent(event.key, event.trigger)
            store.close()
            store = Store(path)
            self.assertTrue(store.was_sent(event.key))
            self.assertFalse(store.was_sent(daily_reminders(date(2026, 10, 31))[0].key))
            store.close()


if __name__ == '__main__':
    unittest.main()
