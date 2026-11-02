import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from discord import app_commands

from bot import TrexBot
from raids import RaidView, LeaderView, ConfirmView, event_embed
from raid_store import RaidStore, raid_time
from schedule import Store, calculate_timer, WIB


NOW = datetime(2026, 11, 2, 20, 0, tzinfo=WIB)


class RaidStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'bot.sqlite3'
        self.store = RaidStore(self.path)
        self.event_id = self.store.create(123, 456, 789, 'trex', NOW, 'Gurun', '3.1')
        self.store.publish(123, self.event_id, 999)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def signup(self, uid=1):
        self.store.respond(123, self.event_id, uid, f'Player {uid}', True)

    def moderate(self, uid, status, now=NOW):
        self.store.moderate(123, self.event_id, uid, 789, status, now)

    def test_signup_duplicate_absent_rejoin_and_accept_are_not_points(self):
        self.signup()
        self.signup()
        self.assertEqual(len(self.store.participants(self.event_id)), 1)
        self.moderate(1, 'accepted')
        self.assertEqual(self.store.respond(123, self.event_id, 1, 'Player', True), 'accepted')
        self.store.respond(123, self.event_id, 1, 'Player', False)
        self.assertEqual(self.store.participants(self.event_id)[0]['status'], 'absent')
        self.signup()
        self.assertEqual(self.store.participants(self.event_id)[0]['status'], 'pending')
        self.assertEqual(self.store.leaderboard(123), [])

    def test_only_verified_participants_awarded_once_and_survive_restart(self):
        for uid in range(1, 7):
            self.signup(uid)
        for uid in (1, 2, 3):
            self.moderate(uid, 'accepted')
        self.moderate(1, 'attended')
        self.moderate(3, 'no_show')
        self.store.respond(123, self.event_id, 4, 'P4', False)
        self.moderate(5, 'rejected')
        self.assertEqual(self.store.finish(123, self.event_id, 789, now=NOW), 1)
        self.assertEqual([(r['user_id'], r['points']) for r in self.store.leaderboard(123)], [('1', 1)])
        self.assertEqual(self.store.participants(self.event_id)[1]['status'], 'no_show')
        self.store.close()
        self.store = RaidStore(self.path)
        with self.assertRaises(ValueError):
            self.store.finish(123, self.event_id, 789, now=NOW)
        with self.assertRaises(ValueError):
            self.signup()
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 1)
        self.assertEqual(self.store.open_events(123), [])

    def test_different_event_each_gives_one_point_and_guilds_are_isolated(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.moderate(1, 'attended')
        self.store.finish(123, self.event_id, 789, now=NOW)
        other = self.store.create(123, 456, 789, 'rift', NOW, 'Pantai')
        self.store.publish(123, other, 1000)
        self.store.respond(123, other, 1, 'Player', True)
        self.store.moderate(123, other, 1, 789, 'accepted', NOW)
        self.store.moderate(123, other, 1, 789, 'attended', NOW)
        self.store.finish(123, other, 789, now=NOW)
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 2)
        self.assertEqual(self.store.leaderboard(124), [])
        with self.assertRaises(ValueError):
            self.store.respond(124, other, 2, 'Other guild', True)

    def test_cancel_event_never_awards_even_verified(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.moderate(1, 'attended')
        self.store.finish(123, self.event_id, 789, cancel=True, now=NOW)
        self.assertEqual(self.store.event(123, self.event_id)['status'], 'cancelled')
        self.assertEqual(self.store.leaderboard(123), [])

    def test_verification_requires_accept_and_start_and_can_be_corrected(self):
        self.signup()
        with self.assertRaises(ValueError):
            self.moderate(1, 'attended')
        self.moderate(1, 'accepted')
        with self.assertRaisesRegex(ValueError, 'jam event'):
            self.moderate(1, 'attended', NOW - timedelta(minutes=1))
        with self.assertRaises(ValueError):
            self.store.finish(123, self.event_id, 789, now=NOW - timedelta(minutes=1))
        self.moderate(1, 'attended')
        with self.assertRaisesRegex(ValueError, 'disahkan'):
            self.store.respond(123, self.event_id, 1, 'Player', False)
        self.moderate(1, 'no_show')
        self.moderate(1, 'attended')
        self.assertEqual(self.store.participants(self.event_id)[0]['verified_by'], '789')
        self.assertTrue(self.store.db.execute('SELECT 1 FROM raid_audit WHERE action=?', ('attended',)).fetchone())

    def test_existing_timers_and_receipts_preserved_in_same_database(self):
        timers = Store(self.path)
        timer = calculate_timer('3.1', '11:20', None, NOW)
        timers.set_timer(123, timer)
        timers.mark_sent('legacy-receipt', NOW)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(timers.timers(123), (timer,))
        self.assertTrue(timers.was_sent('legacy-receipt'))
        timers.close()

    def test_second_connection_cannot_award_again(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.moderate(1, 'attended')
        second = RaidStore(self.path)
        self.store.finish(123, self.event_id, 789, now=NOW)
        try:
            with self.assertRaises(ValueError):
                second.finish(123, self.event_id, 789, now=NOW)
            self.assertEqual(second.leaderboard(123)[0]['points'], 1)
        finally:
            second.close()

    def test_dates_do_not_roll_over_silently(self):
        self.assertEqual(raid_time('20:00', now=NOW), NOW)
        self.assertEqual(raid_time('00:10', '2026-11-03', NOW).day, 3)
        for jam, day in [('19:59', None), ('25:00', None), ('21:00', '2026-02-30'), ('21:00', '20261102')]:
            with self.assertRaises(ValueError):
                raid_time(jam, day, NOW)


class RaidUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789', 'VOICE_CHANNEL_ID': '',
            'RAID_CHANNEL_ID': '555', 'RAID_COMMAND_CHANNEL_ID': '556', 'RAID_LEADER_ROLE_ID': '777',
            'DB_PATH': str(Path(self.tmp.name) / 'bot.sqlite3')})
        self.env.start()
        self.bot = TrexBot()
        self.service = self.bot.raids
        self.event_id = self.service.store.create(123, 555, 10, 'rift', NOW, '@everyone Gurun')
        self.service.store.publish(123, self.event_id, 999)
        self.service.refresh = AsyncMock()

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    def interaction(self, uid=20, role=False, guild=123):
        user = MagicMock(spec=discord.Member)
        user.id, user.bot, user.display_name = uid, False, f'Player {uid}'
        user.roles = [SimpleNamespace(id=777)] if role else []
        i = SimpleNamespace(user=user, guild_id=guild, channel_id=556,
                            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(),
                                                     edit_message=AsyncMock(), is_done=Mock(return_value=False)),
                            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())
        return i

    async def test_public_buttons_and_persistent_restoration_after_restart(self):
        view = RaidView(self.service, self.event_id)
        self.assertEqual([b.label for b in view.children], ['Daftar', 'Tidak Hadir', 'Kelola — Leader'])
        self.assertTrue(view.is_persistent())
        await view.children[0].callback(self.interaction())
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'pending')
        await view.children[1].callback(self.interaction())
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'absent')
        ids = [b.custom_id for b in view.children]
        await self.bot.close()
        self.bot = TrexBot()
        self.service = self.bot.raids
        self.bot.add_view = Mock()
        self.service.restore_views()
        restored = self.bot.add_view.call_args.args[0]
        self.assertEqual(ids, [b.custom_id for b in restored.children])
        self.assertEqual(self.bot.add_view.call_args.kwargs['message_id'], 999)

    async def test_manager_permissions_checked_on_buttons_and_mutations(self):
        for guild in (123, 124):
            with self.assertRaises(app_commands.CheckFailure):
                await self.service.handle_public(self.interaction(guild=guild), self.event_id, 'manage')
        with self.assertRaises(app_commands.CheckFailure):
            await self.service.moderate(self.interaction(), self.event_id, 30, 'attended')
        with self.assertRaises(app_commands.CheckFailure):
            await self.service.finish(self.interaction(), self.event_id, False)
        self.service.require_manager(self.interaction(uid=10), self.service.store.event(123, self.event_id))
        self.service.require_manager(self.interaction(role=True), self.service.store.event(123, self.event_id))
        panel = LeaderView(self.service, self.event_id, 10)
        self.assertFalse(await panel.interaction_check(self.interaction(uid=20, role=True)))

    async def test_manual_commands_publish_and_do_not_change_timers_or_voice(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = SimpleNamespace(id=123)
        channel.send = AsyncMock(return_value=SimpleNamespace(id=1000, jump_url='https://discord.com/channels/123/555/1000'))
        self.service.channel = AsyncMock(return_value=channel)
        old = self.bot.store.timers(123)
        for name in ('rift', 'savage', 'trexraid'):
            command = self.bot.tree.get_command(name)
            values = {'jam': '20:00', 'tempat': 'Gurun'}
            if name == 'trexraid':
                values['index'] = '3.1'
            with patch('raids.raid_time', return_value=NOW):
                await command.callback(self.interaction(role=True), **values)
        self.assertEqual(channel.send.await_count, 3)
        self.assertEqual(self.bot.store.timers(123), old)
        self.assertEqual(self.bot._voice_tasks, {})
        kwargs = channel.send.call_args.kwargs
        self.assertEqual(kwargs['content'], '<@&789>')
        self.assertFalse(kwargs['allowed_mentions'].everyone)
        self.assertFalse(kwargs['allowed_mentions'].users)

    async def test_creation_requires_role_and_command_channel(self):
        with self.assertRaises(app_commands.CheckFailure):
            await self.service.create_event(self.interaction(), 'rift', '20:00', 'Gurun')
        i = self.interaction(role=True)
        i.channel_id = 999
        with self.assertRaisesRegex(ValueError, '556'):
            await self.service.create_event(i, 'rift', '20:00', 'Gurun')

    async def test_failed_publication_is_not_an_open_event(self):
        channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError('send failed')))
        self.service.channel = AsyncMock(return_value=channel)
        with patch('raids.raid_time', return_value=NOW):
            with self.assertRaises(RuntimeError):
                await self.service.create_event(self.interaction(role=True), 'savage', '20:00', 'Gurun')
        self.assertEqual(len(self.service.store.open_events(123)), 1)

    async def test_card_refresh_failure_does_not_lose_signup(self):
        self.service.refresh.side_effect = ValueError('no access')
        i = self.interaction()
        await self.service.handle_public(i, self.event_id, 'join')
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'pending')
        self.assertIn('Data tersimpan', i.followup.send.call_args.args[0])

    async def test_pagination_handles_more_than_25_participants(self):
        for uid in range(100, 156):
            self.service.store.respond(123, self.event_id, uid, 'Player', True)
        panel = LeaderView(self.service, self.event_id, 10)
        self.assertEqual(len(panel.children[0].options), 25)
        last = LeaderView(self.service, self.event_id, 10, page=2)
        self.assertEqual(len(last.children[0].options), 6)
        embed = event_embed(self.service.store.event(123, self.event_id), self.service.store.participants(self.event_id))
        self.assertLess(len(embed), 6000)
        self.assertIn('+44 lainnya', embed.fields[0].value)
        self.assertNotIn('@everyone', embed.description)

    async def test_finalize_via_confirmation_and_closed_buttons(self):
        self.service.store.respond(123, self.event_id, 20, 'P20', True)
        self.service.store.moderate(123, self.event_id, 20, 10, 'accepted', NOW)
        self.service.store.moderate(123, self.event_id, 20, 10, 'attended', NOW)
        view = ConfirmView(self.service, self.event_id, 10, False)
        with patch('raid_store.datetime') as clock:
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            await view.children[0].callback(self.interaction(uid=10))
        self.assertEqual(self.service.store.leaderboard(123)[0]['points'], 1)
        self.assertTrue(all(b.disabled for b in view.children))
        with self.assertRaises(ValueError):
            await self.service.handle_public(self.interaction(), self.event_id, 'join')

    async def test_accept_and_verify_through_leader_panel_actions(self):
        self.service.store.respond(123, self.event_id, 20, 'P20', True)
        i = self.interaction(uid=10)
        await self.service.moderate(i, self.event_id, 20, 'accepted')
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'accepted')
        # Existing fixture event time may be in the future relative to the host clock.
        with patch('raid_store.datetime') as clock:
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            await self.service.moderate(i, self.event_id, 20, 'attended')
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'attended')
        self.assertEqual(self.service.store.leaderboard(123), [])
