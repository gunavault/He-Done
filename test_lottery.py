import asyncio
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from discord import app_commands
from bot import TrexBot
from lottery import LotteryCard, LotteryConfirm
from raid_store import RaidStore
from schedule import WIB

NOW = datetime(2026, 11, 9, 12, tzinfo=WIB)


class LotteryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'bot.sqlite3'
        self.store = RaidStore(self.path)
        for user in (1, 2, 3):
            self.store.add_contribution(123, user, 100, 'seed', 99, f'seed:{user}')
        self.row = self.create()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create(self, req='one', cost=50):
        return self.store.lottery_create(123, 456, 99, 'Lotre senjata', 'Senjata T-Rex', cost,
                                          NOW + timedelta(hours=1), req, NOW)

    def join(self, user=1, row=None, now=NOW):
        row = row or self.row
        return self.store.lottery_join(123, row['id'], user, row['cost'], now)

    def balance(self, user=1):
        return self.store.point_summary(123, user)['points']

    def test_ticket_debits_once_and_preserves_contribution_counts(self):
        self.assertTrue(self.join())
        self.assertFalse(self.join())
        self.assertEqual(self.balance(), 50)
        self.assertEqual(self.store.lottery_spent(123, 1), 50)
        self.assertEqual(self.store.point_summary(123, 1)['contributions'], 1)
        self.assertEqual(self.store.leaderboard(123)[-1]['points'], 50)
        self.assertEqual(self.store.lottery_count(123, self.row['id']), 1)
        self.assertEqual(self.create()['id'], self.row['id'])

    def test_no_debit_for_insufficient_balance_changed_price_closed_or_other_guild(self):
        with self.assertRaises(ValueError):
            self.join(9)
        with self.assertRaises(ValueError):
            self.store.lottery_join(123, self.row['id'], 1, 51, NOW)
        with self.assertRaises(ValueError):
            self.join(now=NOW + timedelta(hours=1))
        with self.assertRaises(ValueError):
            self.store.lottery_join(999, self.row['id'], 1, 50, NOW)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.store.lottery_count(123, self.row['id']), 0)

    def test_random_draw_is_saved_and_never_pays_points_or_rerolls(self):
        self.join(1)
        self.join(2)
        with self.assertRaises(ValueError):
            self.store.lottery_draw(123, self.row['id'], NOW)
        with patch('lottery_store.secrets.choice', return_value='2') as choose:
            drawn = self.store.lottery_draw(123, self.row['id'], NOW + timedelta(hours=1))
            self.assertEqual((drawn['status'], drawn['winner_id']), ('drawn', '2'))
            choose.assert_called_once_with(['1', '2'])
        self.store.close()
        self.store = RaidStore(self.path)
        with patch('lottery_store.secrets.choice') as choose:
            again = self.store.lottery_draw(123, self.row['id'], NOW + timedelta(days=1))
            choose.assert_not_called()
        self.assertEqual(again['winner_id'], '2')
        self.assertEqual(self.balance(2), 50)
        self.assertEqual(self.balance(1), 50)
        with self.assertRaises(ValueError):
            self.store.lottery_status(123, self.row['id'], 'cancel', 99, NOW + timedelta(hours=1))
        delivered = self.store.lottery_status(123, self.row['id'], 'deliver', 99)
        self.assertEqual(delivered['status'], 'delivered')
        self.store.lottery_status(123, self.row['id'], 'deliver', 99)
        self.assertEqual(self.balance(2), 50)

    def test_admin_cancel_refunds_once(self):
        self.join(1)
        self.join(2)
        self.store.lottery_status(123, self.row['id'], 'cancel', 99, NOW)
        self.store.lottery_status(123, self.row['id'], 'cancel', 99, NOW)
        self.assertEqual((self.balance(1), self.balance(2)), (100, 100))
        self.assertEqual(self.store.lottery_spent(123, 1), 0)
        self.assertEqual(self.store.lottery_draw(123, self.row['id'], NOW + timedelta(hours=2))['status'], 'cancelled')
        with self.assertRaises(ValueError):
            self.store.lottery_status(123, self.row['id'], 'deliver', 99, NOW)

    def test_zero_and_one_participant_auto_cancel_and_refund(self):
        for row in (self.row, self.create('two')):
            if row['id'] != self.row['id']:
                self.join(row=row)
                self.assertEqual(self.balance(), 50)
            result = self.store.lottery_draw(123, row['id'], NOW + timedelta(hours=1))
            self.assertEqual(result['status'], 'cancelled')
            self.assertIsNone(result['winner_id'])
            self.assertEqual(self.balance(), 100)

    def test_wipe_does_not_create_free_refund_or_duplicate_charge(self):
        self.join()
        self.store.wipe_points(123, 'console', 'wipe')
        self.assertEqual(self.balance(), 0)
        self.store.lottery_status(123, self.row['id'], 'cancel', 99, NOW)
        self.assertEqual(self.balance(), 0)
        self.assertFalse(self.join())
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.store.lottery_count(123, self.row['id']), 1)

    def test_parallel_ticket_purchases_cannot_overspend(self):
        other = self.create('two', 80)
        row = self.create('three', 80)
        def buy(lottery_id):
            store = RaidStore(self.path)
            try:
                return store.lottery_join(123, lottery_id, 1, 80, NOW)
            except ValueError:
                return False
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, [other['id'], row['id']]))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(self.balance(), 20)

    def test_ticket_cost_prevents_redeem_overspending(self):
        self.store.seed_catalog(123)
        item_id = self.store.catalog_add(123, 'Test murah', 60, 99)
        self.join()
        with self.assertRaises(ValueError):
            self.store.redeem_item(123, 1, item_id, 'Test murah', 60, 'redeem')
        self.assertEqual(self.balance(), 50)

    def test_invalid_creation_and_request_reuse(self):
        for cost in (0, -1, True, 1000001):
            with self.assertRaises(ValueError):
                self.create('bad', cost)
        with self.assertRaises(ValueError):
            self.create('one', 70)
        with self.assertRaises(ValueError):
            self.store.lottery_create(123, 456, 99, 'a', 'b', 50, NOW, 'bad', NOW)
        with self.assertRaises(ValueError):
            self.store.lottery_create(123, 456, 99, 'a', 'b', 50, NOW + timedelta(days=31), 'bad', NOW)
        with self.assertRaises(ValueError):
            self.store.lottery_status(123, self.row['id'], 'cancel', 99, NOW + timedelta(hours=1))
        self.assertEqual(self.store.lottery_get(123, self.row['id'])['status'], 'open')


class LotteryUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789',
            'VOICE_CHANNEL_ID': '', 'GUILD_QUEST_CHANNEL_ID': '', 'DB_PATH': str(Path(self.tmp.name) / 'bot.sqlite3')})
        self.env.start()
        self.bot = TrexBot()
        self.service = self.bot.lottery
        self.store = self.bot.raids.store
        self.now = datetime.now(WIB)
        self.row = self.store.lottery_create(123, 456, 99, 'Lotre', 'Senjata T-Rex', 50,
                                              self.now + timedelta(hours=1), 'one', self.now)
        self.store.add_contribution(123, 1, 100, 'seed', 99, 'seed')

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    def interaction(self, uid=1, admin=False, guild=123):
        user = MagicMock(spec=discord.Member)
        user.id, user.bot = uid, False
        user.guild_permissions = SimpleNamespace(administrator=admin)
        user.roles = [SimpleNamespace(id=789)]
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.guild = 456, SimpleNamespace(id=guild, me=SimpleNamespace(id=999))
        channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
        return SimpleNamespace(user=user, guild_id=guild, channel=channel, id=123456,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_quote_only_charges_after_owner_confirmation_and_duplicate_safe(self):
        member = self.interaction()
        self.service.refresh_safely = AsyncMock(return_value=True)
        await self.service.quote(member, self.row['id'])
        self.assertTrue(member.response.send_message.call_args.kwargs['ephemeral'])
        view = member.response.send_message.call_args.kwargs['view']
        self.assertEqual(self.store.point_summary(123, 1)['points'], 100)
        with self.assertRaises(app_commands.CheckFailure):
            await view.children[0].callback(self.interaction(2))
        for _ in range(2):
            await view.children[0].callback(member)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 50)
        self.assertEqual(self.store.lottery_count(123, self.row['id']), 1)

    async def test_admin_permissions_checked_at_command_and_confirmation(self):
        command = self.bot.tree.get_command('lotrestatus')
        with self.assertRaises(app_commands.CheckFailure):
            await command.callback(self.interaction(), self.row['id'], 'cancel')
        admin = self.interaction(99, True)
        await command.callback(admin, self.row['id'], 'cancel')
        view = admin.response.send_message.call_args.kwargs['view']
        with self.assertRaises(app_commands.CheckFailure):
            await view.children[0].callback(self.interaction(99, False))
        self.service.refresh_safely = AsyncMock(return_value=True)
        await view.children[0].callback(admin)
        self.assertEqual(self.store.lottery_get(123, self.row['id'])['status'], 'cancelled')
        with self.assertRaises(app_commands.CheckFailure):
            await self.service.quote(self.interaction(guild=999), self.row['id'])

    async def test_persistent_card_refresh_and_restart_restores_message_binding(self):
        channel = self.interaction().channel
        channel.send = AsyncMock(return_value=SimpleNamespace(id=1000))
        message = SimpleNamespace(edit=AsyncMock())
        channel.get_partial_message.return_value = message
        self.bot.get_channel = Mock(return_value=channel)
        await self.service.refresh(self.row['id'])
        await self.service.refresh(self.row['id'])
        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        self.assertEqual(channel.send.call_args.kwargs['allowed_mentions'].to_dict(), discord.AllowedMentions.none().to_dict())
        await self.bot.close()
        self.bot = TrexBot()
        self.service = self.bot.lottery
        self.bot.add_view = Mock()
        self.service.restore_views()
        self.assertTrue(self.bot.add_view.call_args.args[0].is_persistent())
        self.assertEqual(self.bot.add_view.call_args.kwargs['message_id'], 1000)

    async def test_overdue_draw_and_failed_publish_retry_without_reroll(self):
        for user in (1, 2):
            if user == 2:
                self.store.add_contribution(123, 2, 100, 'seed', 99, 'two')
            self.store.lottery_join(123, self.row['id'], user, 50, self.now)
        self.service.refresh = AsyncMock(side_effect=ValueError('No access'))
        with patch('lottery_store.secrets.choice', return_value='1') as choose:
            await self.service.tick(self.now + timedelta(hours=2))
            choose.assert_called_once()
        row = self.store.lottery_get(123, self.row['id'])
        self.assertEqual((row['status'], row['winner_id'], row['dirty']), ('drawn', '1', 1))
        self.service.refresh = AsyncMock()
        with patch('lottery_store.secrets.choice') as choose:
            await self.service.tick(self.now + timedelta(hours=2, seconds=11))
            choose.assert_not_called()
        self.service.refresh.assert_awaited_once()
        card = LotteryCard(self.service, row)
        self.assertTrue(card.children[0].disabled)
        self.assertFalse(card.children[1].disabled)

    async def test_participant_pagination_and_public_results_without_ping(self):
        for user in range(22):
            self.store.add_contribution(123, 100 + user, 100, 'seed', 99, f'page:{user}')
            self.store.lottery_join(123, self.row['id'], 100 + user, 50, self.now)
        member = self.interaction()
        await self.service.members(member, self.row['id'], 1)
        text = member.response.send_message.call_args.args[0]
        self.assertIn('halaman 2/2', text)
        self.assertIn('21.', text)
        with self.assertRaises(ValueError):
            await self.service.members(member, self.row['id'], 2)
        embed = self.service.embed(self.store.lottery_get(123, self.row['id']))
        self.assertIn('Senjata T-Rex', embed.description)
        self.assertLess(len(embed), 6000)

    async def test_create_posts_to_invoked_channel_and_checks_admin(self):
        command = self.bot.tree.get_command('lotre')
        with self.assertRaises(app_commands.CheckFailure):
            await command.callback(self.interaction(), 'Judul', 'Item', 50, '23:00', '2026-11-10')
        admin = self.interaction(99, True)
        self.service.refresh_safely = AsyncMock(return_value=True)
        tomorrow = (self.now + timedelta(days=1)).date().isoformat()
        await command.callback(admin, 'Judul', 'Item', 50, '23:00', tomorrow)
        created = self.store.db.execute('SELECT * FROM lotteries ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((created['channel_id'], created['title'], created['prize']), ('456', 'Judul', 'Item'))
        self.service.refresh_safely.assert_awaited_once_with(created['id'])
