import asyncio
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from discord import app_commands

from bot import TrexBot
from raid_store import RaidStore
from redeem import RedeemConfirmView, CatalogPublicView
from redeem_store import DEFAULT_CATALOG


class RedeemStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        self.store = RaidStore(self.path)
        self.store.seed_catalog(123)
        self.items = self.store.catalog_items(123)
        self.store.add_contribution(123, 1, 1000, 'Initial', 99, 'initial')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def buy(self, item=None, request='test', user=1, store=None):
        item = item if item is not None else self.items[0]
        return (store or self.store).redeem_item(123, user, item['id'], item['name'], item['price'], request)

    def test_seed_prices_remove_restart_and_add_duplicate_validation(self):
        self.assertEqual([(x['name'], x['price']) for x in self.items], list(DEFAULT_CATALOG))
        self.store.catalog_remove(123, self.items[0]['id'], 99)
        self.store.close()
        self.store = RaidStore(self.path)
        self.store.seed_catalog(123)
        self.assertEqual(len(self.store.catalog_items(123)), 7)
        new_id = self.store.catalog_add(123, 'Senjata Tarbo', 250, 99)
        self.assertNotEqual(new_id, self.items[0]['id'])
        with self.assertRaises(ValueError):
            self.store.catalog_add(123, 'senjata tarbo', 200, 99)
        for name, price in (('', 1), ('x' * 101, 1), ('Test', 0), ('Test', True)):
            with self.assertRaises(ValueError):
                self.store.catalog_add(123, name, price, 99)
        self.store.seed_catalog(124)
        self.assertEqual(len(self.store.catalog_items(124)), 8)

    def test_charge_once_snapshot_counts_and_restart(self):
        item = self.items[3]  # T-Rex 500 points
        order = self.buy(item)
        self.assertEqual(self.buy(item)['id'], order['id'])
        summary = self.store.point_summary(123, 1)
        self.assertEqual((summary['points'], summary['redeem_points'], summary['events'], summary['contributions']), (500, 500, 0, 1))
        self.assertEqual(self.store.leaderboard(123)[0]['points'], 500)
        self.store.catalog_remove(123, item['id'], 99)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(self.store.redeem_order(123, order['id'])['item_name'], 'Senjata T-Rex')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 500)
        self.assertEqual(self.buy(item)['id'], order['id'])

    def test_not_enough_stale_quote_inactive_item_and_cross_guild(self):
        item = self.items[0]
        with self.assertRaisesRegex(ValueError, 'cukup'):
            self.buy(user=2)
        with self.assertRaises(ValueError):
            self.store.redeem_item(123, 1, item['id'], item['name'], 1, 'cheap')
        with self.assertRaises(ValueError):
            self.store.redeem_item(124, 1, item['id'], item['name'], item['price'], 'other')
        self.store.catalog_remove(123, item['id'], 99)
        with self.assertRaises(ValueError):
            self.buy()
        self.assertEqual(self.store.redeem_orders(123), [])
        self.assertEqual(self.store.point_summary(123, 1)['points'], 1000)

    def test_cancel_refund_once_fulfil_no_second_charge_and_history_isolation(self):
        first = self.buy(request='first')
        row, changed, refund = self.store.set_redeem_status(123, first['id'], 'cancelled', 99)
        self.assertEqual((changed, refund), (True, 200))
        self.assertEqual(self.store.set_redeem_status(123, first['id'], 'cancelled', 99)[1:], (False, 0))
        self.assertEqual(self.store.point_summary(123, 1)['points'], 1000)
        second = self.buy(request='second')
        self.store.set_redeem_status(123, second['id'], 'fulfilled', 99)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 800)
        with self.assertRaises(ValueError):
            self.store.set_redeem_status(123, second['id'], 'cancelled', 99)
        self.assertEqual(self.store.redeem_orders(123, pending_only=True), [])
        self.assertEqual(len(self.store.redeem_orders(123, user_id=1)), 2)
        self.assertEqual(self.store.redeem_orders(123, user_id=2), [])
        with self.assertRaises(ValueError):
            self.store.redeem_order(124, first['id'])

    def test_reset_preserves_orders_no_old_refund_or_charge_after_restart(self):
        first = self.buy(request='first')
        second = self.buy(request='second')
        reset = self.store.wipe_points(123, 'console', 'reset')
        self.assertEqual(reset['redemptions'], 2)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        self.assertEqual(self.store.set_redeem_status(123, first['id'], 'cancelled', 99)[2], 0)
        self.store.set_redeem_status(123, second['id'], 'fulfilled', 99)
        self.buy(request='second')  # Same confirmation cannot re-charge wiped points.
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        self.store.add_contribution(123, 1, 200, 'New', 99, 'new')
        self.buy(request='new-order')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)

    def test_concurrent_two_connections_cannot_overspend(self):
        self.store.remove_points(123, 1, 800, 'Set to 200', 99, 'deduct')
        barrier = threading.Barrier(2)

        def spend(request):
            store = RaidStore(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    self.buy(request=request, store=store)
                    return True
                except ValueError:
                    return False
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(spend, str(i)) for i in range(2)]
            self.assertEqual(sorted(f.result(timeout=10) for f in futures), [False, True])
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        self.assertEqual(len(self.store.redeem_orders(123)), 1)


class RedeemUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789',
            'RAID_CHANNEL_ID': '', 'RAID_COMMAND_CHANNEL_ID': '', 'RAID_LEADER_ROLE_ID': '',
            'VOICE_CHANNEL_ID': '', 'DB_PATH': str(Path(self.tmp.name) / 'db.sqlite3')})
        self.env.start()
        self.bot = TrexBot()
        self.service = self.bot.redeem
        self.store = self.bot.raids.store
        self.store.add_contribution(123, 20, 1000, 'Initial', 99, 'initial')

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    def interaction(self, uid=20, admin=False, guild=123):
        user = MagicMock(spec=discord.Member)
        user.id, user.bot, user.guild = uid, False, SimpleNamespace(id=guild)
        user.guild_permissions = SimpleNamespace(administrator=admin)
        return SimpleNamespace(user=user, guild_id=guild,
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock(), defer=AsyncMock(), is_done=Mock(return_value=False)),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    async def test_catalog_public_persistent_button_and_private_confirmation_once(self):
        member = self.interaction()
        await self.bot.tree.get_command('katalog').callback(member)
        kwargs = member.response.send_message.call_args.kwargs
        self.assertNotIn('ephemeral', kwargs)
        self.assertTrue(kwargs['view'].is_persistent())
        self.assertIn('Senjata Tarbo', kwargs['embed'].description)
        await kwargs['view'].children[0].callback(member)
        private = member.response.send_message.call_args.kwargs
        self.assertTrue(private['ephemeral'])
        item = self.store.catalog_items(123)[0]
        await self.bot.tree.get_command('redeem').callback(member, item['id'])
        view = member.response.send_message.call_args.kwargs['view']
        self.assertIsInstance(view, RedeemConfirmView)
        with self.assertRaises(app_commands.CheckFailure):
            await view.children[0].callback(self.interaction(uid=21))
        for _ in range(2):
            await view.children[0].callback(member)
        self.assertEqual(self.store.point_summary(123, 20)['points'], 800)
        self.assertEqual(len(self.store.redeem_orders(123)), 1)
        self.assertIsNone(member.edit_original_response.call_args.kwargs['view'])

    async def test_admin_commands_require_administrator_and_catalog_changes_persist(self):
        member, admin = self.interaction(), self.interaction(admin=True)
        for name, values in (('katalogadd', ('Item Baru', 100)), ('katalogremove', (1,)),
                             ('redeemqueue', ()), ('redeemstatus', (1, 'fulfilled'))):
            command = self.bot.tree.get_command(name)
            self.assertTrue(command.default_permissions.administrator)
            with self.assertRaises(app_commands.CheckFailure):
                await command.callback(member, *values)
        await self.bot.tree.get_command('katalogadd').callback(admin, 'Item Baru', 100)
        item = self.store.catalog_items(123)[-1]
        await self.bot.tree.get_command('katalogremove').callback(admin, item['id'])
        with self.assertRaises(ValueError):
            self.store.catalog_item(123, item['id'])
        with self.assertRaises(app_commands.CheckFailure):
            await self.bot.tree.get_command('redeem').callback(self.interaction(guild=124))

    async def test_cancel_confirmation_does_not_charge_and_history_only_own(self):
        item = self.store.catalog_items(123)[0]
        member = self.interaction()
        await self.service.quote(member, item['id'])
        view = member.response.send_message.call_args.kwargs['view']
        await view.children[1].callback(member)
        self.assertEqual(self.store.point_summary(123, 20)['points'], 1000)
        self.store.redeem_item(123, 20, item['id'], item['name'], item['price'], 'history')
        other = self.interaction(uid=21)
        await self.bot.tree.get_command('redeemhistory').callback(other)
        self.assertIn('Belum ada', other.response.send_message.call_args.kwargs['embed'].description)
        admin = self.interaction(admin=True)
        await self.bot.tree.get_command('redeemqueue').callback(admin)
        self.assertIn('Senjata Tarbo', admin.response.send_message.call_args.kwargs['embed'].description)
        self.bot.add_view = Mock()
        self.service.restore_views()
        self.assertIsInstance(self.bot.add_view.call_args.args[0], CatalogPublicView)

    async def test_admin_cancels_confirmed_order_and_member_balance_refunded_once(self):
        item = self.store.catalog_items(123)[0]
        member = self.interaction()
        await self.bot.tree.get_command('redeem').callback(member, item['id'])
        view = member.response.send_message.call_args.kwargs['view']
        await view.children[0].callback(member)
        order = self.store.redeem_orders(123, 20)[0]
        admin = self.interaction(admin=True)
        for _ in range(2):
            await self.bot.tree.get_command('redeemstatus').callback(admin, order['id'], 'cancelled')
        self.assertEqual(self.store.point_summary(123, 20)['points'], 1000)
        self.assertIn('sebelumnya', admin.followup.send.call_args.args[0])
        await self.bot.tree.get_command('redeemhistory').callback(member)
        self.assertIn('Dibatalkan', member.response.send_message.call_args.kwargs['embed'].description)
