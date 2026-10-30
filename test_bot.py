import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bot import TrexBot
from schedule import daily_reminders


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789',
            'INDEX_31_TIMES': '11:20,18:00', 'INDEX_32_TIMES': '12:47,19:27',
            'REMINDER_MINUTES': '30,15,5,0',
            'DB_PATH': str(Path(self.tmp.name) / 'test.sqlite3'),
        })
        self.env.start()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    async def test_daily_delivery_and_no_duplicates_after_restart(self):
        events = daily_reminders(date(2026, 10, 30))
        for event in events:
            await self.bot.deliver_due(event.trigger)
            await self.bot.deliver_due(event.trigger + timedelta(seconds=5))
        self.assertEqual(self.bot.send_notice.await_count, 16)
        await self.bot.close()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()
        await self.bot.deliver_due(events[-1].trigger)
        self.bot.send_notice.assert_not_awaited()
        for event in daily_reminders(date(2026, 10, 31)):
            await self.bot.deliver_due(event.trigger)
        self.assertEqual(self.bot.send_notice.await_count, 16)

    async def test_failed_delivery_retries_but_stale_reminder_is_skipped(self):
        event = daily_reminders(date(2026, 10, 30))[0]
        self.bot.send_notice.side_effect = ValueError('simulated permission failure')
        await self.bot.deliver_due(event.trigger)
        self.bot.send_notice.side_effect = None
        await self.bot.deliver_due(event.trigger + timedelta(seconds=5))
        self.assertEqual(self.bot.send_notice.await_count, 2)
        await self.bot.deliver_due(event.trigger + timedelta(seconds=10))
        self.assertEqual(self.bot.send_notice.await_count, 2)
        second = daily_reminders(date(2026, 10, 30))[1]
        await self.bot.deliver_due(second.trigger + timedelta(minutes=2))
        self.assertEqual(self.bot.send_notice.await_count, 2)

    async def test_commands_and_role_mention_scope(self):
        self.assertEqual({c.name for c in self.bot.tree.get_commands()}, {'jadwal', 'tes'})
        # Exercise the real send_notice method with a fake Discord destination.
        channel = AsyncMock()
        role = type('FakeRole', (), {'id': 789, 'mention': '<@&789>'})()
        self.bot.destination = AsyncMock(return_value=(channel, role))
        await TrexBot.send_notice(self.bot, 'H-30 menit')
        args, kwargs = channel.send.call_args
        self.assertEqual(args[0], '<@&789>\nH-30 menit')
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'roles': [789], 'parse': []})


if __name__ == '__main__':
    unittest.main()
