import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from types import SimpleNamespace
import discord
from discord import app_commands

from bot import TrexBot
from schedule import WIB, daily_reminders


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

    async def test_trex_response_displays_nearest_without_ping(self):
        interaction = AsyncMock()
        command = self.bot.tree.get_command('trex')
        with patch('bot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await command.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn('Index: **3.1**', args[0])
        self.assertIn('18:00 WIB', args[0])
        self.assertIn('5 jam', args[0])
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.bot.send_notice.assert_not_awaited()

    async def update_timer(self, index='3.1', waktu='11:20', now=None):
        interaction = AsyncMock()
        interaction.permissions = SimpleNamespace(manage_guild=True)
        with patch('bot.datetime') as clock:
            clock.now.return_value = now or datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await self.bot.tree.get_command('trex').callback(interaction, i=index, w=waktu)
        return interaction

    async def test_update_replaces_reminders_and_survives_restart(self):
        await self.update_timer()
        interaction = await self.update_timer(waktu='11:30')
        confirmation = interaction.followup.send.call_args.args[0]
        self.assertIn('18:10–18:30 WIB', confirmation)
        self.assertIn('17:40 WIB', confirmation)
        await self.bot.deliver_due(datetime(2026, 10, 30, 17, 30, tzinfo=WIB))
        self.bot.send_notice.assert_not_awaited()
        await self.bot.deliver_due(datetime(2026, 10, 30, 17, 40, tzinfo=WIB))
        self.bot.send_notice.assert_awaited_once()
        self.assertIn('18:10–18:30 WIB', self.bot.send_notice.call_args.args[0])
        await self.bot.close()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()
        self.assertEqual(len(self.bot.store.timers(self.bot.guild_id)), 1)
        await self.bot.deliver_due(datetime(2026, 10, 30, 17, 40, tzinfo=WIB))
        self.bot.send_notice.assert_not_awaited()
        await self.bot.deliver_due(datetime(2026, 10, 31, 17, 40, tzinfo=WIB))
        self.bot.send_notice.assert_awaited_once()

    async def test_update_index_isolation_and_nearest_response(self):
        await self.update_timer()
        await self.update_timer(index='3.2', waktu='12:47')
        await self.update_timer(waktu='11:30')
        timers = {t.index: t for t in self.bot.store.timers(self.bot.guild_id)}
        self.assertEqual(timers['3.2'].start.strftime('%H:%M'), '19:27')
        self.assertEqual(self.bot.store.timers('another-guild'), ())
        interaction = AsyncMock()
        with patch('bot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await self.bot.tree.get_command('trex').callback(interaction)
        self.assertIn('18:10–18:30 WIB', interaction.response.send_message.call_args.args[0])

    async def test_partial_and_unauthorized_updates_do_not_mutate(self):
        interaction = AsyncMock()
        interaction.permissions = SimpleNamespace(manage_guild=False)
        callback = self.bot.tree.get_command('trex').callback
        with self.assertRaises(ValueError):
            await callback(interaction, i='3.1')
        with self.assertRaises(app_commands.MissingPermissions):
            await callback(interaction, i='3.1', w='11:20')
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), ())

    async def test_invalid_time_preserves_existing_timer(self):
        await self.update_timer()
        previous = self.bot.store.timers(self.bot.guild_id)
        with self.assertRaises(ValueError):
            await self.update_timer(waktu='bad')
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), previous)

    def fake_destination(self, *, channel_cached=True, member_cached=True):
        role = SimpleNamespace(id=789, mentionable=True, is_default=lambda: False)
        member = SimpleNamespace(id=999)
        guild = SimpleNamespace(id=123, name='Test guild', unavailable=False,
            get_role=Mock(return_value=role), me=member if member_cached else None,
            fetch_member=AsyncMock(return_value=member))
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 456
        channel.guild = guild
        channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, send_messages=True, mention_everyone=False)
        guild.get_channel = Mock(return_value=channel if channel_cached else None)
        guild.fetch_channel = AsyncMock(return_value=channel)
        self.bot._connection.user = SimpleNamespace(id=999)
        return guild, channel, role

    async def test_missing_guild_cache_fetches_guild_channel_and_self(self):
        guild, channel, role = self.fake_destination(channel_cached=False, member_cached=False)
        self.bot.get_guild = Mock(return_value=None)
        self.bot.fetch_guild = AsyncMock(return_value=guild)
        self.assertEqual(await self.bot.destination(), (channel, role))
        self.bot.fetch_guild.assert_awaited_once_with(123)
        guild.fetch_channel.assert_awaited_once_with(456)
        guild.fetch_member.assert_awaited_once_with(999)

    async def test_cached_destination_avoids_api_fetch(self):
        guild, channel, role = self.fake_destination()
        self.bot.get_guild = Mock(return_value=guild)
        self.bot.fetch_guild = AsyncMock()
        self.assertEqual(await self.bot.destination(), (channel, role))
        self.bot.fetch_guild.assert_not_awaited()
        guild.fetch_channel.assert_not_awaited()
        guild.fetch_member.assert_not_awaited()

    async def test_unavailable_guild_refreshes_and_permissions_still_checked(self):
        guild, channel, _ = self.fake_destination()
        self.bot.get_guild = Mock(return_value=SimpleNamespace(unavailable=True))
        self.bot.fetch_guild = AsyncMock(return_value=guild)
        channel.permissions_for.return_value.send_messages = False
        with self.assertRaisesRegex(ValueError, 'Send Messages'):
            await self.bot.destination()
        self.bot.fetch_guild.assert_awaited_once()

    async def test_wrong_guild_channel_is_rejected(self):
        guild, channel, _ = self.fake_destination()
        self.bot.get_guild = Mock(return_value=guild)
        channel.guild = SimpleNamespace(id=99999)
        with self.assertRaisesRegex(ValueError, 'GUILD_ID'):
            await self.bot.destination()

    async def test_api_denial_reports_active_bot_and_guild(self):
        self.bot._connection.user = SimpleNamespace(id=999)
        self.bot.get_guild = Mock(return_value=None)
        response = SimpleNamespace(status=403, reason='Forbidden')
        self.bot.fetch_guild = AsyncMock(side_effect=discord.Forbidden(response, 'Missing Access'))
        with self.assertRaisesRegex(ValueError, 'server 123.*HTTP 403.*bot_id aktif=999'):
            await self.bot.destination()

    async def test_commands_and_role_mention_scope(self):
        self.assertEqual({c.name for c in self.bot.tree.get_commands()}, {'trex', 'jadwal', 'tes'})
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
