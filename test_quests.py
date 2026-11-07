import asyncio
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from discord import app_commands

from bot import TrexBot
from quest_store import quest_now
from raid_store import RaidStore
from quests import QuestChoiceView, QuestConfirm, QuestForm, QuestMainView, QuestMemberView, QuestNoteForm
from schedule import WIB

NOW = datetime(2026, 11, 7, 12, tzinfo=WIB)


class QuestStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'quests.sqlite3'
        self.store = RaidStore(self.path)
        self.q = self.create()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create(self, request='first', points=100, hours=2):
        return self.store.quest_create(123, 99, 'Kumpulkan Rubber Log', 'Kumpulkan 100 log', points, hours, request, NOW)

    def claim(self, user=1, quest=None, now=NOW):
        return self.store.quest_claim(123, quest or self.q['id'], user, now)

    def submit(self, row, now=None):
        self.store.quest_submit(123, row['id'], row['user_id'], row['attempt_id'], 'https://discord.com/channels/123/4/5', now or NOW)

    def test_post_claim_submit_approve_reward_and_resume_after_restart(self):
        self.assertEqual(self.store.quest_create(123, 99, self.q['title'], self.q['detail'], 100, 2, 'first', NOW)['id'], self.q['id'])
        claimed = self.claim()
        again = self.claim(now=NOW + timedelta(minutes=10))
        self.assertEqual(again['deadline'], claimed['deadline'])
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        self.store.close()
        self.store = RaidStore(self.path)
        resumed = self.store.quest_current(123, 1)
        self.assertEqual(resumed['attempt_id'], claimed['attempt_id'])
        self.submit(resumed, NOW + timedelta(hours=1))
        self.assertEqual(self.store.quest_expire(123, NOW + timedelta(days=2)), 0)
        self.assertEqual(self.store.point_summary(123, 1)['quests'], 0)
        self.assertTrue(self.store.quest_review(123, self.q['id'], claimed['attempt_id'], 99, True, now=NOW + timedelta(days=2)))
        self.assertFalse(self.store.quest_review(123, self.q['id'], claimed['attempt_id'], 99, True, now=NOW + timedelta(days=2)))
        summary = self.store.point_summary(123, 1)
        self.assertEqual((summary['points'], summary['quests'], summary['quest_points'], summary['contributions']), (100, 1, 100, 0))
        board = self.store.leaderboard(123)[0]
        self.assertEqual((board['user_id'], board['quests'], board['points']), ('1', 1, 100))
        self.assertIsNone(self.store.quest_current(123, 1))
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'completed')

    def test_abort_releases_quest_and_stale_attempt_cannot_submit_or_abort_new_one(self):
        first = self.claim()
        self.store.quest_abort(123, self.q['id'], 1, first['attempt_id'], NOW)
        second = self.claim(now=NOW + timedelta(hours=1))
        self.assertNotEqual(first['attempt_id'], second['attempt_id'])
        with self.assertRaises(ValueError):
            self.store.quest_submit(123, self.q['id'], 1, first['attempt_id'], 'Old', NOW)
        with self.assertRaises(ValueError):
            self.store.quest_abort(123, self.q['id'], 1, first['attempt_id'], NOW)
        with self.assertRaises(ValueError):
            self.store.quest_abort(123, self.q['id'], 2, second['attempt_id'], NOW)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)

    def test_expiry_exact_deadline_and_offline_recovery(self):
        row = self.claim()
        deadline = datetime.fromisoformat(row['deadline'])
        with self.assertRaises(ValueError):
            self.store.quest_submit(123, self.q['id'], 1, row['attempt_id'], '', deadline)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertEqual(self.store.quest_expire(123, deadline), 1)
        self.assertIsNone(self.store.quest_current(123, 1))
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'available')
        self.assertEqual(self.store.quest_expire(123, deadline), 0)
        self.assertEqual(self.store.db.execute('SELECT status FROM guild_quest_attempts WHERE id=?', (row['attempt_id'],)).fetchone()[0], 'expired')

    def test_member_limit_and_review_revision_no_deadline_extension(self):
        other = self.create('second')
        row = self.claim()
        with self.assertRaises(ValueError):
            self.claim(quest=other['id'])
        self.submit(row, NOW + timedelta(minutes=10))
        selected = self.store.quest_get(123, self.q['id'])
        self.store.quest_review(123, self.q['id'], row['attempt_id'], 99, False, 'Kurang log', NOW + timedelta(minutes=20))
        revised = self.store.quest_current(123, 1)
        self.assertEqual(revised['deadline'], row['deadline'])
        self.assertEqual(revised['review_note'], 'Kurang log')
        self.submit(revised, NOW + timedelta(minutes=30))
        with self.assertRaisesRegex(ValueError, 'berubah'):
            self.store.quest_review(123, self.q['id'], row['attempt_id'], 99, True, now=NOW + timedelta(minutes=40), revision=selected['revision'])
        self.store.quest_review(123, self.q['id'], row['attempt_id'], 99, False, 'Belum lengkap', NOW + timedelta(hours=3))
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'available')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)

    def test_edit_only_available_revision_guard_withdraw_and_guild_scope(self):
        self.store.quest_edit(123, self.q['id'], 99, self.q['revision'], 'Updated', 'Details', 200, 4, NOW)
        with self.assertRaises(ValueError):
            self.store.quest_withdraw(123, self.q['id'], 99, self.q['revision'], NOW)
        row = self.claim()
        with self.assertRaises(ValueError):
            self.store.quest_edit(123, self.q['id'], 99, row['revision'], 'No', 'No', 1, 1, NOW)
        with self.assertRaises(ValueError):
            self.store.quest_get(124, self.q['id'])
        with self.assertRaises(ValueError):
            self.store.quest_claim(124, self.q['id'], 2, NOW)
        self.assertEqual(self.store.quest_list(124), [])
        self.store.quest_abort(123, self.q['id'], 1, row['attempt_id'], NOW)
        current = self.store.quest_get(123, self.q['id'])
        self.store.quest_withdraw(123, self.q['id'], 99, current['revision'], NOW)
        with self.assertRaises(ValueError):
            self.claim()

    def test_quest_rewards_redeem_remove_salary_and_wipe_do_not_resurrect(self):
        q = self.create('big', points=300)
        row = self.claim(quest=q['id'])
        self.submit(row)
        self.store.quest_review(123, q['id'], row['attempt_id'], 99, True, now=NOW)
        self.store.seed_catalog(123)
        item = self.store.catalog_items(123)[0]
        self.store.redeem_item(123, 1, item['id'], item['name'], item['price'], 'quest-redeem')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 100)
        self.assertEqual(self.store.point_summary(123, 1)['quests'], 1)
        self.store.remove_points(123, 1, 10, 'Correction', 99, 'remove')
        self.store.salary_set(123, 1, 50, 'Salary', 99, now=NOW)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 140)
        reset = self.store.wipe_points(123, 'console', 'wipe')
        self.assertEqual(reset['quest_rewards'], 1)
        self.store.close()
        self.store = RaidStore(self.path)
        self.assertFalse(self.store.quest_review(123, q['id'], row['attempt_id'], 99, True, now=NOW))
        self.assertEqual((self.store.point_summary(123, 1)['points'], self.store.point_summary(123, 1)['quests']), (0, 0))
        self.assertEqual(self.store.quest_get(123, q['id'])['status'], 'completed')

    def test_two_members_cannot_claim_same_quest_concurrently(self):
        barrier = threading.Barrier(2)
        def claim(user):
            store = RaidStore(self.path)
            try:
                barrier.wait(timeout=5)
                try:
                    store.quest_claim(123, self.q['id'], user, NOW)
                    return True
                except ValueError:
                    return False
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(claim, user) for user in (1, 2)]
            self.assertEqual(sorted(job.result(timeout=10) for job in jobs), [False, True])
        self.assertEqual(self.store.quest_counts(123)['in_progress'], 1)

    def test_bad_post_inputs_and_proof_length(self):
        for title, detail, points, hours in (('', 'd', 1, 1), ('t', '', 1, 1), ('t', 'd', 0, 1),
                                              ('t', 'd', True, 1), ('t', 'd', 1, 0), ('t', 'd', 1, 721)):
            with self.assertRaises(ValueError):
                self.store.quest_create(123, 99, title, detail, points, hours, 'invalid', NOW)
        row = self.claim()
        with self.assertRaises(ValueError):
            self.store.quest_submit(123, self.q['id'], 1, row['attempt_id'], 'x' * 1001, NOW)


class QuestUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789',
            'VOICE_CHANNEL_ID': '', 'GUILD_QUEST_CHANNEL_ID': '555', 'UNION_LEADER_ROLE_ID': '777',
            'DB_PATH': str(Path(self.tmp.name) / 'bot.sqlite3')})
        self.env.start()
        self.bot = TrexBot()
        self.service = self.bot.quests
        self.store = self.bot.raids.store
        self.service.refresh_board = AsyncMock()
        self.now = datetime.now(WIB)
        self.q = self.store.quest_create(123, 99, 'Rubber log', 'Kumpulkan 100 log', 100, 2, 'ui-first', self.now)

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    def interaction(self, uid=1, leader=False, guild=123):
        user = MagicMock(spec=discord.Member)
        user.id, user.bot, user.guild = uid, False, SimpleNamespace(id=guild)
        user.roles = [SimpleNamespace(id=777)] if leader else []
        user.guild_permissions = SimpleNamespace(administrator=True, manage_guild=True)
        message = SimpleNamespace(id=uid, flags=SimpleNamespace(ephemeral=True), delete=AsyncMock())
        return SimpleNamespace(original_response=AsyncMock(return_value=message), user=user, guild_id=guild, channel_id=555,
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock(), defer=AsyncMock(),
                                     send_modal=AsyncMock(), is_done=Mock(return_value=False)),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock(return_value=message))

    async def test_private_panel_auto_dismiss_and_reopen_preserves_quest(self):
        row = self.store.quest_claim(123, self.q['id'], 1, self.now)
        interaction = self.interaction()
        message = await interaction.original_response()
        with patch('quests.asyncio.sleep', new_callable=AsyncMock) as delay:
            await self.service.open_panel(interaction)
            await self.service._dismiss_tasks[message.id]
            delay.assert_awaited_once_with(20)
        message.delete.assert_awaited_once()
        self.assertEqual(self.store.quest_current(123, 1)['attempt_id'], row['attempt_id'])
        await self.service.open_panel(interaction)
        self.assertIsInstance(interaction.edit_original_response.call_args.kwargs['view'], QuestMemberView)

    async def test_panel_update_resets_expiry_and_public_card_is_not_deleted(self):
        interaction = self.interaction()
        message = await interaction.original_response()
        with patch('quests.asyncio.sleep', new_callable=AsyncMock) as delay:
            await self.service.dismiss_later(interaction, message)
            old = self.service._dismiss_tasks[message.id]
            await self.service.dismiss_later(interaction, message)
            current = self.service._dismiss_tasks[message.id]
            await asyncio.gather(old, current, return_exceptions=True)
            self.assertTrue(old.cancelled())
            delay.assert_awaited_once_with(20)
        message.delete.assert_awaited_once()
        message.flags.ephemeral = False
        await self.service.dismiss_later(interaction, message)
        self.assertFalse(self.service._dismiss_tasks)
        message.delete.assert_awaited_once()

    async def test_dismissed_message_not_found_is_harmless(self):
        interaction = self.interaction()
        message = await interaction.original_response()
        message.delete.side_effect = discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'Unknown Message')
        with patch('quests.asyncio.sleep', new_callable=AsyncMock):
            await self.service.dismiss_later(interaction, message)
            await self.service._dismiss_tasks[message.id]
        self.assertFalse(self.service._dismiss_tasks)

    async def test_dashboard_buttons_role_checks_and_no_admin_bypass(self):
        view = QuestMainView(self.service)
        self.assertTrue(view.is_persistent())
        self.assertEqual([b.label for b in view.children], ['Accept Quest', 'Abort Quest', 'Union Leader Panel'])
        with self.assertRaises(app_commands.CheckFailure):
            await view.children[2].callback(self.interaction())
        with self.assertRaises(app_commands.CheckFailure):
            await view.children[0].callback(self.interaction(guild=124))
        leader = self.interaction(99, leader=True)
        await view.children[2].callback(leader)
        self.assertIsInstance(leader.edit_original_response.call_args.kwargs['view'], QuestChoiceView)
        self.service.leader_role_id = 123
        with self.assertRaises(app_commands.CheckFailure):
            self.service.require_leader(leader)

    async def test_accept_dismiss_reopen_submit_and_approve_flow(self):
        member = self.interaction()
        await self.service.open_panel(member)
        view = member.edit_original_response.call_args.kwargs['view']
        self.assertIsInstance(view, QuestChoiceView)
        select = view.children[0]
        select._values = [str(self.q['id'])]
        await select.callback(member)
        self.assertIn('Kumpulkan 100 log', member.response.edit_message.call_args.kwargs['embed'].description)
        accept = next(b for b in view.children if isinstance(b, discord.ui.Button) and b.label == 'Accept Quest Terpilih')
        await accept.callback(member)
        picked = self.store.quest_current(123, 1)
        self.assertIsInstance(member.edit_original_response.call_args.kwargs['view'], QuestMemberView)
        # Dismiss does not call Abort. Opening the main button recovers the same attempt.
        await QuestMainView(self.service).children[0].callback(member)
        resumed_view = member.edit_original_response.call_args.kwargs['view']
        self.assertIsInstance(resumed_view, QuestMemberView)
        self.assertEqual(self.store.quest_current(123, 1)['attempt_id'], picked['attempt_id'])
        await resumed_view.children[0].callback(member)
        modal = member.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, QuestNoteForm)
        modal.note._value = 'https://discord.com/channels/123/4/5'
        await modal.on_submit(member)
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'submitted')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        leader = self.interaction(99, leader=True)
        row = dict(self.store.quest_get(123, self.q['id']))
        for _ in range(2):
            await self.service.review(leader, row, True)
        self.assertEqual((self.store.point_summary(123, 1)['points'], self.store.point_summary(123, 1)['quests']), (100, 1))
        self.assertGreaterEqual(self.service.refresh_board.await_count, 3)
        await self.bot.tree.get_command('leaderboard').callback(member)
        self.assertIn('1 quest', member.response.send_message.call_args.args[0])
        await self.bot.tree.get_command('point').callback(member)
        self.assertIn('Quest selesai: **1 quest** · 100 poin', member.response.send_message.call_args.args[0])

    async def test_abort_confirm_required_and_old_panel_cannot_abort_reclaimed_quest(self):
        picked = self.store.quest_claim(123, self.q['id'], 1, self.now)
        member = self.interaction()
        await self.service.open_abort(member)
        confirmation = member.response.send_message.call_args.kwargs['view']
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'in_progress')
        with self.assertRaises(app_commands.CheckFailure):
            await confirmation.children[0].callback(self.interaction(2))
        await confirmation.children[0].callback(member)
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'available')
        self.store.quest_claim(123, self.q['id'], 1, self.now)
        with self.assertRaises(ValueError):
            await confirmation.children[0].callback(member)

    async def test_leader_form_post_validation_and_no_edit_after_pickup(self):
        leader = self.interaction(99, leader=True)
        form = QuestForm(self.service, 99)
        form.title_field._value = 'Buat box'
        form.detail._value = 'Buat 5 box'
        form.points._value = '150'
        form.hours._value = '4'
        with self.assertRaises(app_commands.CheckFailure):
            await form.on_submit(self.interaction(1))
        await form.on_submit(leader)
        await form.on_submit(leader)
        self.assertEqual(self.store.quest_counts(123)['available'], 2)
        created = self.store.quest_list(123, 'available')[0]
        edit = QuestForm(self.service, 99, dict(created))
        edit.title_field._value, edit.detail._value = 'Edited', 'Details'
        edit.points._value, edit.hours._value = '200', '5'
        self.store.quest_claim(123, created['id'], 1, self.now)
        with self.assertRaises(ValueError):
            await edit.on_submit(leader)

    async def test_expiry_and_dashboard_failure_retries_without_losing_state(self):
        self.store.quest_claim(123, self.q['id'], 1, self.now)
        self.service.refresh_board.side_effect = ValueError('No access')
        await self.service.tick(self.now + timedelta(hours=3))
        self.assertEqual(self.store.quest_get(123, self.q['id'])['status'], 'available')
        self.assertTrue(self.service.dirty)
        self.service.refresh_board.side_effect = None
        await self.service.tick(self.now + timedelta(hours=3, seconds=16))
        self.assertEqual(self.service.refresh_board.await_count, 2)

    async def test_existing_dashboard_is_edited_and_restored_after_restart(self):
        # Exercise the real Discord-facing update with a mocked channel.
        from quests import QuestService
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = SimpleNamespace(id=123)
        channel.send = AsyncMock(return_value=SimpleNamespace(id=1000))
        message = SimpleNamespace(edit=AsyncMock())
        channel.get_partial_message.return_value = message
        self.bot.get_channel = Mock(return_value=channel)
        await QuestService.refresh_board(self.service)
        await QuestService.refresh_board(self.service)
        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        await self.bot.close()
        self.bot = TrexBot()
        self.service = self.bot.quests
        self.bot.get_channel = Mock(return_value=channel)
        self.bot.add_view = Mock()
        self.service.restore_views()
        self.assertTrue(self.bot.add_view.call_args.args[0].is_persistent())
        await self.service.startup()
        channel.send.assert_awaited_once()
        self.assertEqual(self.service.store.quest_board(123)['message_id'], '1000')

    async def test_large_board_and_quest_previews_fit_discord_limits(self):
        for i in range(12):
            self.store.quest_create(123, 99, '*' * 100, '*' * 1500, 100, 2, f'long-{i}', self.now)
        row = self.store.quest_list(123, 'available')[0]
        attempt = self.store.quest_claim(123, row['id'], 1, self.now)
        self.store.quest_submit(123, row['id'], 1, attempt['attempt_id'], '*' * 1000, self.now)
        preview = self.service.quest_embed(self.store.quest_get(123, row['id']), leader=True)
        self.assertLessEqual(len(preview.description), 4096)
        self.assertLessEqual(len(preview), 6000)
        board = self.service.board_embed()
        self.assertLessEqual(len(board), 6000)
        self.assertTrue(all(len(field.value) <= 1024 for field in board.fields))
        self.assertEqual(len(QuestChoiceView(self.service, 99, leader=True).children[0].options), 10)
