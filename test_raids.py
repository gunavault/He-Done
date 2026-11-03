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

    def test_signup_duplicate_absent_rejoin_needs_fresh_accept(self):
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

    def test_accepted_awarded_immediately_once_and_survive_restart(self):
        for uid in range(1, 7):
            self.signup(uid)
        for uid in (1, 2, 3):
            self.moderate(uid, 'accepted')
        self.assertEqual(len(self.store.leaderboard(123)), 3)
        self.moderate(1, 'accepted')
        self.moderate(3, 'absent')
        self.store.respond(123, self.event_id, 4, 'P4', False)
        self.moderate(5, 'absent')
        self.assertEqual(self.store.finish(123, self.event_id, 789, now=NOW), 2)
        self.assertEqual([(r['user_id'], r['points']) for r in self.store.leaderboard(123)], [('1', 2), ('2', 2)])
        self.store.close()
        self.store = RaidStore(self.path)
        with self.assertRaises(ValueError):
            self.store.finish(123, self.event_id, 789, now=NOW)
        with self.assertRaises(ValueError):
            self.signup()
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 2)
        self.assertEqual(self.store.open_events(123), [])

    def test_different_event_each_gives_one_point_and_guilds_are_isolated(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.store.finish(123, self.event_id, 789, now=NOW)
        other = self.store.create(123, 456, 789, 'rift', NOW, 'Pantai')
        self.store.publish(123, other, 1000)
        self.store.respond(123, other, 1, 'Player', True)
        self.store.moderate(123, other, 1, 789, 'accepted', NOW)
        self.store.finish(123, other, 789, now=NOW)
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 3)
        self.assertEqual(self.store.leaderboard(124), [])
        with self.assertRaises(ValueError):
            self.store.respond(124, other, 2, 'Other guild', True)

    def test_cancel_event_reverses_accepted_points(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.store.finish(123, self.event_id, 789, cancel=True, now=NOW)
        self.assertEqual(self.store.event(123, self.event_id)['status'], 'cancelled')
        self.assertEqual(self.store.leaderboard(123), [])

    def test_accept_before_start_absence_reverses_points_and_rejoin_needs_accept(self):
        self.signup()
        self.moderate(1, 'accepted', NOW - timedelta(minutes=1))
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 2)
        self.store.respond(123, self.event_id, 1, 'Player', False)
        self.assertEqual(self.store.leaderboard(123), [])
        with self.assertRaises(ValueError):
            self.moderate(1, 'accepted')
        self.signup()
        self.assertEqual(self.store.leaderboard(123), [])
        self.moderate(1, 'accepted')
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 2)
        self.moderate(1, 'absent')
        self.assertEqual(self.store.leaderboard(123), [])
        self.assertEqual(self.store.participants(self.event_id)[0]['verified_by'], '789')

    def test_upgrade_legacy_statuses_and_existing_accepted_points_is_idempotent(self):
        for uid in (1, 2, 3, 4):
            self.signup(uid)
        with self.store.db:
            for uid, status in ((1, 'attended'), (2, 'accepted'), (3, 'rejected'), (4, 'no_show')):
                self.store.db.execute('UPDATE raid_participants SET status=? WHERE event_id=? AND user_id=?',
                                      (status, self.event_id, str(uid)))
            self.store.db.execute('INSERT INTO raid_points VALUES(?,?,?,1,?)',
                                 (self.event_id, '123', '1', NOW.isoformat()))
        for _ in range(2):
            self.store.close()
            self.store = RaidStore(self.path)
            self.assertEqual([p['status'] for p in self.store.participants(self.event_id)],
                             ['accepted', 'accepted', 'absent', 'absent'])
            self.assertEqual([(r['user_id'], r['points']) for r in self.store.leaderboard(123)], [('1', 2), ('2', 2)])

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
        second = RaidStore(self.path)
        self.store.finish(123, self.event_id, 789, now=NOW)
        try:
            with self.assertRaises(ValueError):
                second.finish(123, self.event_id, 789, now=NOW)
            self.assertEqual(second.leaderboard(123)[0]['points'], 2)
        finally:
            second.close()

    def test_dates_do_not_roll_over_silently(self):
        self.assertEqual(raid_time('20:00', now=NOW), NOW)
        self.assertEqual(raid_time('00:10', '2026-11-03', NOW).day, 3)
        for jam, day in [('19:59', None), ('25:00', None), ('21:00', '2026-02-30'), ('21:00', '20261102')]:
            with self.assertRaises(ValueError):
                raid_time(jam, day, NOW)

    def test_contributions_total_count_replay_and_restart(self):
        self.signup()
        self.moderate(1, 'accepted')
        receipt = self.store.add_contribution(123, 1, 5, 'Membantu material', 99, 'interaction-1')
        self.assertEqual(receipt, self.store.add_contribution(123, 1, 5, 'Membantu material', 99, 'interaction-1'))
        row = self.store.leaderboard(123)[0]
        self.assertEqual((row['points'], row['events'], row['contributions']), (7, 1, 1))
        self.store.add_contribution(123, 1, 2, 'Membantu transport', 99, 'interaction-2')
        self.store.add_contribution(124, 1, 100, 'Other server', 99, 'interaction-3')
        self.store.close()
        self.store = RaidStore(self.path)
        row = self.store.leaderboard(123)[0]
        self.assertEqual((row['points'], row['events'], row['contributions']), (9, 1, 2))
        detail = self.store.db.execute('SELECT * FROM raid_contributions WHERE id=?', (receipt,)).fetchone()
        self.assertEqual((detail['detail'], detail['actor_id']), ('Membantu material', '99'))
        # Cancelling a raid must never delete an independent contribution.
        self.store.finish(123, self.event_id, 789, cancel=True, now=NOW)
        row = self.store.leaderboard(123)[0]
        self.assertEqual((row['points'], row['events'], row['contributions']), (7, 0, 2))

    def test_contribution_validation_and_interaction_collision(self):
        for points, detail in ((0, 'a'), (-1, 'a'), (1.5, 'a'), (True, 'a'), (1000001, 'a'), (1, '  '), (1, 'x' * 501)):
            with self.assertRaises(ValueError):
                self.store.add_contribution(123, 1, points, detail, 99, 'bad')
        self.store.add_contribution(123, 2, 4, 'Valid', 99, 'valid')
        with self.assertRaises(ValueError):
            self.store.add_contribution(123, 2, 10, 'Different', 99, 'valid')
        row = self.store.leaderboard(123)[0]
        self.assertEqual((row['user_id'], row['points'], row['events'], row['contributions']), ('2', 4, 0, 1))

    def test_personal_point_summary_includes_zero_and_isolates_user_and_server(self):
        empty = dict(self.store.point_summary(123, 1))
        self.assertEqual(empty, dict(points=0, events=0, contributions=0, event_points=0, contribution_points=0))
        self.signup()
        self.moderate(1, 'accepted')
        self.store.add_contribution(123, 1, 5, 'Material', 99, 'summary-1')
        self.store.add_contribution(123, 2, 20, 'Other user', 99, 'summary-2')
        self.store.add_contribution(124, 1, 100, 'Other server', 99, 'summary-3')
        self.assertEqual(dict(self.store.point_summary(123, 1)),
                         dict(points=7, events=1, contributions=1, event_points=2, contribution_points=5))
        self.store.respond(123, self.event_id, 1, 'Player', False)
        self.assertEqual(dict(self.store.point_summary(123, 1)),
                         dict(points=5, events=0, contributions=1, event_points=0, contribution_points=5))

    def test_three_event_weights_and_upgrade_old_one_point_constraint(self):
        ids = [self.event_id]
        for kind in ('savage', 'rift'):
            eid = self.store.create(123, 456, 789, kind, NOW, 'Place')
            self.store.publish(123, eid, 1000 + eid)
            ids.append(eid)
        for eid in ids:
            self.store.respond(123, eid, 1, 'Player', True)
            self.store.moderate(123, eid, 1, 789, 'accepted')
        self.assertEqual([self.store.event_credit(123, eid, 1) for eid in ids], [2, 3, 1])
        # Recreate the real pre-upgrade constraint and legacy 1-point records.
        with self.store.db:
            self.store.db.execute('DROP TABLE raid_points')
            self.store.db.execute('''CREATE TABLE raid_points (
                event_id INTEGER NOT NULL REFERENCES raid_events(id),guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,points INTEGER NOT NULL CHECK (points=1),
                awarded_at TEXT NOT NULL,PRIMARY KEY(event_id,user_id))''')
            for eid in ids:
                self.store.db.execute('INSERT INTO raid_points VALUES(?,?,?,1,?)', (eid, '123', '1', NOW.isoformat()))
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual([self.store.event_credit(123, eid, 1) for eid in ids], [2, 3, 1])
        summary = self.store.point_summary(123, 1)
        self.assertEqual((summary['points'], summary['events']), (6, 3))

    def test_wipe_keeps_history_but_zero_survives_restart_old_clicks_and_replay(self):
        self.signup()
        self.moderate(1, 'accepted')
        self.store.add_contribution(123, 1, 5, 'Material', 99, 'before-wipe')
        self.store.add_contribution(124, 1, 10, 'Other guild', 99, 'other-guild')
        reset = self.store.wipe_points(123, 'console', 'reset-1')
        self.assertEqual((reset['event_awards'], reset['contributions']), (1, 1))
        self.assertEqual(self.store.leaderboard(123), [])
        self.assertEqual(self.store.leaderboard(124)[0]['points'], 10)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(self.store.leaderboard(123), [])
        self.assertEqual(self.store.participants(self.event_id)[0]['status'], 'accepted')
        self.moderate(1, 'accepted')
        self.store.respond(123, self.event_id, 1, 'Player', False)
        self.signup()
        self.moderate(1, 'accepted')
        self.store.add_contribution(123, 1, 5, 'Material', 99, 'before-wipe')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        self.store.add_contribution(123, 1, 3, 'New material', 99, 'after-wipe')
        self.store.wipe_points(123, 'console', 'reset-1')  # Replay must not reset new points.
        self.assertEqual(self.store.point_summary(123, 1)['points'], 3)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM raid_contributions WHERE guild_id=?', ('123',)).fetchone()[0], 2)
        self.assertEqual(self.store.event(123, self.event_id)['status'], 'open')
        self.signup(2)  # A new attendance after the reset can earn points normally.
        self.moderate(2, 'accepted')
        self.assertEqual(self.store.point_summary(123, 2)['points'], 2)


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
        user.guild_permissions = SimpleNamespace(administrator=False, manage_guild=False)
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

    async def test_startup_refreshes_existing_card_once(self):
        await self.service.refresh_open_cards()
        await self.service.refresh_open_cards()
        self.service.refresh.assert_awaited_once_with(self.event_id)

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
        view = ConfirmView(self.service, self.event_id, 10, False)
        with patch('raid_store.datetime') as clock:
            clock.now.return_value = NOW
            clock.fromisoformat.side_effect = datetime.fromisoformat
            await view.children[0].callback(self.interaction(uid=10))
        self.assertEqual(self.service.store.leaderboard(123)[0]['points'], 1)
        self.assertTrue(all(b.disabled for b in view.children))
        with self.assertRaises(ValueError):
            await self.service.handle_public(self.interaction(), self.event_id, 'join')

    async def test_accept_immediately_gives_point_and_panel_has_two_actions(self):
        self.service.store.respond(123, self.event_id, 20, 'P20', True)
        i = self.interaction(uid=10)
        await self.service.moderate(i, self.event_id, 20, 'accepted')
        self.assertEqual(self.service.store.participants(self.event_id)[0]['status'], 'accepted')
        self.assertEqual(self.service.store.leaderboard(123)[0]['points'], 1)
        panel = LeaderView(self.service, self.event_id, 10)
        actions = [b.label for b in panel.children if isinstance(b, discord.ui.Button)]
        self.assertIn('Hadir', actions)
        self.assertIn('Tidak Hadir', actions)
        self.assertNotIn('Sahkan Hadir', actions)
        embed = event_embed(self.service.store.event(123, self.event_id), self.service.store.participants(self.event_id))
        self.assertEqual([f.name for f in embed.fields], ['Menunggu diterima (0)', 'Hadir (1)', 'Tidak Hadir (0)'])
        await self.service.moderate(i, self.event_id, 20, 'absent')
        self.assertEqual(self.service.store.leaderboard(123), [])

    async def test_addpoint_requires_discord_administrator_not_manage_server_or_role(self):
        command = self.bot.tree.get_command('addpoint')
        target = self.interaction(uid=30).user
        target.guild = SimpleNamespace(id=123)
        for i in (self.interaction(), self.interaction(role=True), self.interaction(uid=10)):
            i.user.guild_permissions = SimpleNamespace(administrator=False, manage_guild=True)
            with self.assertRaises(app_commands.CheckFailure):
                await command.callback(i, target, 5, 'Material')
        allowed = self.interaction()
        allowed.user.roles = []
        allowed.user.guild_permissions = SimpleNamespace(administrator=True, manage_guild=True)
        self.service.require_admin(allowed)
        self.assertTrue(command.default_permissions.administrator)
        with self.assertRaises(app_commands.CheckFailure):
            self.service.require_manager(allowed, self.service.store.event(123, self.event_id))
        self.assertEqual(self.service.store.leaderboard(123), [])

    async def test_addpoint_receipt_replay_and_example_leaderboard(self):
        admin = self.interaction()
        admin.id = 7654
        admin.user.guild_permissions = SimpleNamespace(administrator=True, manage_guild=True)
        target = self.interaction(uid=30).user
        target.guild = SimpleNamespace(id=123)
        for event_id in (self.event_id,
                         self.service.store.create(123, 555, 10, 'rift', NOW, 'P'),
                         self.service.store.create(123, 555, 10, 'savage', NOW, 'P')):
            self.service.store.publish(123, event_id, 999 + event_id)
            self.service.store.respond(123, event_id, 30, 'C. Ago', True)
            self.service.store.moderate(123, event_id, 30, 10, 'accepted')
        command = self.bot.tree.get_command('addpoint')
        for _ in range(2):
            await command.callback(admin, target, 5, 'Material @everyone')
        row = self.service.store.leaderboard(123)[0]
        self.assertEqual((row['points'], row['events'], row['contributions']), (10, 3, 1))
        admin.response.defer.assert_awaited_with(ephemeral=False)
        self.assertFalse(admin.followup.send.call_args.kwargs['ephemeral'])
        self.assertTrue(admin.followup.send.call_args.args[0].startswith('<@&789>\n'))
        mentions = admin.followup.send.call_args.kwargs['allowed_mentions']
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.users)
        self.assertEqual([role.id for role in mentions.roles], [789])
        reader = self.interaction()
        await self.bot.tree.get_command('leaderboard').callback(reader)
        self.assertIn('1. **<@30>** — **10 poin** · 3 event, 1 contribution', reader.response.send_message.call_args.args[0])

    async def test_addpoint_rejects_bot_wrong_guild_and_blank_detail(self):
        admin = self.interaction()
        admin.id = 9876
        admin.user.guild_permissions = SimpleNamespace(administrator=True, manage_guild=True)
        target = self.interaction(uid=30).user
        command = self.bot.tree.get_command('addpoint')
        target.guild = SimpleNamespace(id=124)
        with self.assertRaises(ValueError):
            await command.callback(admin, target, 1, 'Material')
        target.guild.id = 123
        target.bot = True
        with self.assertRaises(ValueError):
            await command.callback(admin, target, 1, 'Material')
        target.bot = False
        with self.assertRaises(ValueError):
            await command.callback(admin, target, 1, '   ')
        admin.guild_id = 124
        with self.assertRaises(app_commands.CheckFailure):
            await command.callback(admin, target, 1, 'Material')
        self.assertEqual(self.service.store.leaderboard(123), [])

    async def test_point_self_other_zero_and_no_admin_requirement(self):
        command = self.bot.tree.get_command('point')
        self.assertIsNone(command.default_permissions)
        reader = self.interaction(uid=20)
        reader.user.guild = SimpleNamespace(id=123)
        await command.callback(reader)
        self.assertIn('Total: **0 poin**', reader.response.send_message.call_args.args[0])
        self.assertIn('<@20>', reader.response.send_message.call_args.args[0])
        target = self.interaction(uid=30).user
        target.guild = SimpleNamespace(id=123)
        self.service.store.add_contribution(123, 30, 5, 'Material', 99, 'point-test')
        await command.callback(reader, target)
        text = reader.response.send_message.call_args.args[0]
        self.assertIn('<@30>', text)
        self.assertIn('Total: **5 poin**', text)
        self.assertIn('Contribution: **1 contribution** · 5 poin', text)
        self.assertTrue(reader.response.send_message.call_args.kwargs['ephemeral'])
        self.assertFalse(reader.response.send_message.call_args.kwargs['allowed_mentions'].users)
        target.guild.id = 124
        with self.assertRaises(ValueError):
            await command.callback(reader, target)
        reader.guild_id = 124
        with self.assertRaises(app_commands.CheckFailure):
            await command.callback(reader)
