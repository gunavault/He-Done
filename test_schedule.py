import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from schedule import (WIB, Store, daily_reminders, due_reminders, parse_time,
                      parse_offsets, parse_times, next_spawn, next_spawn_message, calculate_timer, effective_reminders)


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

    def test_next_spawn_between_schedules_and_exact_time(self):
        for hour, minute, index, expected in (
                (10, 0, '3.1', time(11, 20)), (11, 21, '3.2', time(12, 47)),
                (13, 0, '3.1', time(18, 0)), (18, 1, '3.2', time(19, 27)),
                (18, 0, '3.1', time(18, 0))):
            event = next_spawn(datetime(2026, 10, 30, hour, minute, tzinfo=WIB))
            self.assertEqual((event.index, event.start.time()), (index, expected))

    def test_next_spawn_tomorrow_and_utc(self):
        now = datetime(2026, 10, 30, 20, 0, tzinfo=WIB)
        event = next_spawn(now)
        self.assertEqual(event.start, datetime(2026, 10, 31, 11, 20, tzinfo=WIB))
        self.assertIn('Besok, 31-10-2026', next_spawn_message(now))
        self.assertEqual(next_spawn(now.astimezone(timezone.utc)), event)

    def test_next_spawn_custom_schedule_and_countdown(self):
        now = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
        self.assertIn('5 jam', next_spawn_message(now))
        custom = (('3.2', time(14, 15)),)
        self.assertEqual(next_spawn(now, custom).index, '3.2')
        self.assertIn('1 jam 15 menit', next_spawn_message(now, custom))
        self.assertIn('Sekarang', next_spawn_message(datetime(2026, 10, 30, 18, 0, tzinfo=WIB)))
        with self.assertRaises(ValueError):
            next_spawn(now, slots=())

    def test_calculated_timer_windows_and_offsets(self):
        now = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
        for index, at, start, end in [('3.1', '11:20', '18:00', '18:20'),
                                      ('3.2', '12:47', '19:27', '19:47')]:
            timer = calculate_timer(index, at, now=now)
            self.assertEqual((timer.start.strftime('%H:%M'), timer.end.strftime('%H:%M')), (start, end))
        timer = calculate_timer('3.1', '11:30', now=now)
        events = [e for e in effective_reminders(now.date(), timers=(timer,)) if e.index == '3.1']
        self.assertEqual([e.trigger.strftime('%H:%M') for e in events], ['17:40', '17:55', '18:05', '18:10'])
        self.assertIn('18:10–18:30 WIB', events[0].message())
        # The old morning and evening slots of this index are replaced.
        self.assertEqual(len(events), 4)
        original_other = [e for e in daily_reminders(now.date()) if e.index == '3.2']
        self.assertEqual([e for e in effective_reminders(now.date(), timers=(timer,)) if e.index == '3.2'], original_other)

    def test_timer_crosses_midnight_and_repeats_daily(self):
        now = datetime(2026, 10, 30, 23, 30, tzinfo=WIB)
        timer = calculate_timer('3.1', '23:20', now=now)
        self.assertEqual(timer.start, datetime(2026, 10, 31, 6, 0, tzinfo=WIB))
        self.assertFalse([e for e in effective_reminders(now.date(), timers=(timer,)) if e.index == '3.1'])
        events = effective_reminders(date(2026, 11, 1), timers=(timer,))
        self.assertIn(datetime(2026, 11, 1, 5, 30, tzinfo=WIB), [e.trigger for e in events if e.index == '3.1'])

    def test_timer_validation_and_previous_day(self):
        now = datetime(2026, 10, 31, 0, 5, tzinfo=WIB)
        for args in [('3.3', '00:00', None), ('3.1', '24:00', None),
                     ('3.1', '11:20', None), ('3.1', '00:00', '2026-02-30'),
                     ('3.1', '00:00', '30-10-2026')]:
            with self.assertRaises(ValueError):
                calculate_timer(*args, now=now)
        timer = calculate_timer('3.1', '23:20', '2026-10-30', now=now)
        self.assertEqual(timer.start.hour, 6)
        self.assertEqual(timer.observed.date(), date(2026, 10, 30))

    def test_updated_window_remains_visible_until_end(self):
        timer = calculate_timer('3.1', '11:20', now=datetime(2026, 10, 30, 13, 0, tzinfo=WIB))
        now = datetime(2026, 10, 30, 18, 5, tzinfo=WIB)
        event = next_spawn(now, timers=(timer,))
        self.assertEqual(event.start.hour, 18)
        self.assertIn('Sedang dalam jendela spawn', next_spawn_message(now, timers=(timer,)))
        # At the end, the expired window is no longer the nearest.
        self.assertEqual(next_spawn(datetime(2026, 10, 30, 18, 20, tzinfo=WIB), timers=(timer,)).index, '3.2')

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
