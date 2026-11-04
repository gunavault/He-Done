"""Regression tests for recurring Saturday salary payouts."""
import tempfile
import unittest
from datetime import datetime, timedelta, time
from pathlib import Path

from raid_store import RaidStore
from schedule import WIB
from salary_store import last_salary_day, next_salary_day, parse_salary_hour


def clock(day, hour=9, minute=0):
    return datetime(day[0], day[1], day[2], hour, minute, tzinfo=WIB)


class SalaryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'points.sqlite3'
        self.store = RaidStore(self.path)
        self.wed = clock((2026, 11, 4), 12)
        self.sat = clock((2026, 11, 7), 9)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_schedule_and_clock(self):
        self.assertEqual(next_salary_day(self.wed, time(9)), self.sat.date())
        self.assertEqual(next_salary_day(self.sat, time(9)), (self.sat + timedelta(days=7)).date())
        self.assertEqual(last_salary_day(self.wed), clock((2026, 10, 31)).date())
        self.assertEqual(last_salary_day(self.sat), self.sat.date())
        self.assertEqual(parse_salary_hour('09:00'), time(9))
        with self.assertRaises(ValueError):
            parse_salary_hour('25:00')

    def test_payment_once_restart_and_point_totals(self):
        row = self.store.salary_set(123, 21, 50, 'Leader', 99, now=self.wed)
        self.assertEqual(row['effective_payday'], '2026-11-07')
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat), [('21', 50)])
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat), [])
        self.assertEqual(self.store.point_summary(123, 21)['points'], 50)
        self.assertEqual(self.store.salary_summary(123, 21)['points'], 50)
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 50)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat), [])
        self.assertEqual(self.store.point_summary(123, 21)['points'], 50)
        self.assertEqual(self.store.salary_payweek(123, (self.sat + timedelta(days=7)).date(),
                         now=self.sat + timedelta(days=7)), [('21', 50)])
        self.assertEqual(self.store.point_summary(123, 21)['points'], 100)

    def test_stop_change_idempotency_and_isolation(self):
        self.store.salary_set(123, 21, 50, 'Leader', 99, now=self.wed)
        self.store.salary_set(123, 21, 50, 'Leader', 99, now=self.sat)
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat), [('21', 50)])
        self.store.salary_set(123, 21, 75, 'Promoted', 99, now=self.sat + timedelta(hours=1))
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat + timedelta(hours=1)), [])
        self.assertEqual(self.store.salary_payweek(123, (self.sat + timedelta(days=7)).date(),
                         now=self.sat + timedelta(days=7)), [('21', 75)])
        self.assertTrue(self.store.salary_stop(123, 21, 99, now=self.sat + timedelta(days=7)))
        self.assertFalse(self.store.salary_stop(123, 21, 99))
        self.assertEqual(self.store.salary_payweek(123, (self.sat + timedelta(days=14)).date(),
                         now=self.sat + timedelta(days=14)), [])
        self.assertEqual(self.store.point_summary(123, 21)['points'], 125)
        self.store.salary_set(124, 21, 100, 'Another guild', 99, now=self.wed)
        self.assertEqual(self.store.salary_payweek(124, self.sat.date(), now=self.sat), [('21', 100)])
        self.assertEqual(self.store.point_summary(123, 21)['points'], 125)
        self.assertEqual(self.store.point_summary(124, 21)['points'], 100)

    def test_wipe_voids_history_not_future_payday(self):
        self.store.salary_set(123, 21, 50, 'Leader', 99, now=self.wed)
        self.store.salary_payweek(123, self.sat.date(), now=self.sat)
        self.store.wipe_points(123, 'console', 'wipe-salary')
        self.assertEqual(self.store.point_summary(123, 21)['points'], 0)
        self.assertEqual(self.store.salary_summary(123, 21)['points'], 0)
        self.assertTrue(self.store.salary_list(123))
        self.assertEqual(self.store.salary_payweek(123, self.sat.date(), now=self.sat), [])
        self.assertEqual(self.store.salary_payweek(123, (self.sat + timedelta(days=7)).date(),
                         now=self.sat + timedelta(days=7)), [('21', 50)])

    def test_validation(self):
        for points, detail in [(0, 'ok'), (-1, 'ok'), (True, 'ok'), (1000001, 'ok'), (1, ' '), (1, 'x' * 501)]:
            with self.assertRaises(ValueError):
                self.store.salary_set(123, 21, points, detail, 99, now=self.wed)
        with self.assertRaises(ValueError):
            self.store.salary_payweek(123, self.wed.date(), now=self.wed)


if __name__ == '__main__':
    unittest.main()
