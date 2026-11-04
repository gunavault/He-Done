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
from schedule import WIB, daily_reminders, effective_reminders


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'GUILD_ID': '123', 'CHANNEL_ID': '456', 'ROLE_ID': '789',
            'INDEX_31_TIMES': '11:20,18:00', 'INDEX_32_TIMES': '12:47,19:27',
            'REMINDER_MINUTES': '30,15,5,0', 'VOICE_CHANNEL_ID': '',
            'DB_PATH': str(Path(self.tmp.name) / 'test.sqlite3'),
        })
        self.env.start()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.tmp.cleanup()

    async def test_registered_delivery_once_and_no_default_or_next_day_after_restart(self):
        self.assertEqual(self.bot.slots, ())
        for event in daily_reminders(date(2026, 10, 30)):
            await self.bot.deliver_due(event.trigger)
        self.bot.send_notice.assert_not_awaited()
        await self.update_timer()
        events = effective_reminders(date(2026, 10, 30), slots=(), timers=self.bot.store.timers(123))
        for event in events:
            await self.bot.deliver_due(event.trigger)
            await self.bot.deliver_due(event.trigger + timedelta(seconds=5))
        self.assertEqual(self.bot.send_notice.await_count, 4)

        await self.bot.close()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()
        await self.bot.deliver_due(events[-1].trigger)
        for event in events:
            await self.bot.deliver_due(event.trigger + timedelta(days=1))
        self.bot.send_notice.assert_not_awaited()
        await self.update_timer(now=datetime(2026, 10, 31, 13, 0, tzinfo=WIB))
        for event in effective_reminders(date(2026, 10, 31), slots=(), timers=self.bot.store.timers(123)):
            await self.bot.deliver_due(event.trigger)
        self.assertEqual(self.bot.send_notice.await_count, 4)


    async def test_same_index_different_islands_deliver_independently_and_update_only_one(self):
        await self.update_timer(tempat='Volcano')
        await self.update_timer(tempat='Snowfield')
        parameter = next(p for p in self.bot.tree.get_command('worldbossregister').parameters if p.name == 'tempat')
        self.assertEqual([c.value for c in parameter.choices], ['Volcano', 'Snowfield', 'Tundra', 'Swamp', 'Desert', 'Tropical'])
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        now = datetime(2026, 10, 30, 17, 30, tzinfo=WIB)
        await self.bot.deliver_due(now)
        await self.flush_voice()
        self.assertEqual(self.bot.send_notice.await_count, 2)
        self.assertEqual(self.bot.voice.announce.await_count, 2)
        messages = [call.args[0] for call in self.bot.send_notice.call_args_list]
        self.assertTrue(any('Volcano' in m for m in messages))
        self.assertTrue(any('Snowfield' in m for m in messages))
        self.bot.send_notice.reset_mock()
        await self.update_timer(tempat='Volcano', waktu='11:30')
        await self.bot.deliver_due(datetime(2026, 10, 30, 17, 45, tzinfo=WIB))
        self.assertIn('Snowfield', self.bot.send_notice.call_args.args[0])
        await self.bot.close()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()
        self.assertEqual(len(self.bot.store.timers(123)), 2)
        await self.bot.deliver_due(datetime(2026, 10, 30, 17, 45, tzinfo=WIB))
        self.bot.send_notice.assert_not_awaited()
    async def morning_timer(self):
        await self.update_timer(waktu='04:40', now=datetime(2026, 10, 30, 5, 0, tzinfo=WIB))

    async def test_expired_register_is_not_shifted_to_tomorrow_and_can_be_replaced(self):
        interaction = await self.update_timer(now=datetime(2026, 10, 30, 20, 0, tzinfo=WIB))
        self.assertIn('Jendela ini sudah lewat', interaction.followup.send.call_args.args[0])
        for now in (datetime(2026, 10, 30, 20, 0, tzinfo=WIB), datetime(2026, 10, 31, 13, 0, tzinfo=WIB)):
            reader = AsyncMock()
            with patch('bot.datetime') as clock:
                clock.now.return_value = now
                await self.bot.tree.get_command('worldbossregister').callback(reader)
                await self.bot.tree.get_command('jadwal').callback(reader)
            messages = [call.args[0] for call in reader.response.send_message.call_args_list]
            self.assertIn('Belum ada jadwal world boss aktif', messages[0])
            self.assertNotIn('**Index 3.1', messages[1])
        await self.update_timer(waktu='20:00', now=datetime(2026, 10, 30, 20, 0, tzinfo=WIB))
        self.assertEqual(self.bot.store.timers(123)[0].start, datetime(2026, 10, 31, 2, 40, tzinfo=WIB))

    async def test_failed_delivery_retries_but_stale_reminder_is_skipped(self):
        await self.morning_timer()
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
        await self.update_timer()
        interaction = AsyncMock()
        command = self.bot.tree.get_command('worldbossregister')
        with patch('bot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await command.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn('Index: **3.1**', args[0])
        self.assertIn('18:00–18:20 WIB', args[0])
        self.assertIn('5 jam', args[0])
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.bot.send_notice.assert_not_awaited()

    async def update_timer(self, index='3.1', waktu='11:20', now=None, tempat='Volcano'):
        interaction = AsyncMock()
        interaction.guild_id = self.bot.guild_id
        interaction.permissions = SimpleNamespace(manage_guild=False)
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.roles = [SimpleNamespace(id=self.bot.role_id)]
        with patch('bot.datetime') as clock:
            clock.now.return_value = now or datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await self.bot.tree.get_command('worldbossregister').callback(interaction, index=index, tempat=tempat, waktu=waktu)
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
        self.bot.send_notice.assert_not_awaited()

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
            await self.bot.tree.get_command('worldbossregister').callback(interaction)
        self.assertIn('18:10–18:30 WIB', interaction.response.send_message.call_args.args[0])

    async def test_partial_and_unauthorized_updates_do_not_mutate(self):
        interaction = AsyncMock()
        interaction.permissions = SimpleNamespace(manage_guild=False)
        callback = self.bot.tree.get_command('worldbossregister').callback
        with self.assertRaises(ValueError):
            await callback(interaction, index='3.1')
        with self.assertRaises(app_commands.CheckFailure):
            await callback(interaction, index='3.1', tempat='Volcano', waktu='11:20')
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), ())

    async def test_timer_edit_requires_exact_env_role_even_for_admins(self):
        interaction = AsyncMock()
        interaction.guild_id = self.bot.guild_id
        interaction.user = MagicMock(spec=discord.Member)
        interaction.permissions = SimpleNamespace(manage_guild=True, administrator=True)
        callback = self.bot.tree.get_command('worldbossregister').callback
        for roles in ([], [SimpleNamespace(id=111, name='Hunter')]):
            interaction.user.roles = roles
            with self.assertRaisesRegex(app_commands.CheckFailure, 'ROLE_ID'):
                await callback(interaction, index='3.1', tempat='Volcano', waktu='11:20')
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), ())
        interaction.followup.send.assert_not_awaited()

    async def test_role_holder_can_update_without_manage_server(self):
        interaction = await self.update_timer()
        self.assertFalse(interaction.permissions.manage_guild)
        self.assertEqual(self.bot.store.timers(self.bot.guild_id)[0].index, '3.1')
        self.assertIn('Timer index **3.1** diperbarui', interaction.followup.send.call_args.args[0])

    async def test_role_check_rejects_wrong_server_nonmember_and_everyone_role(self):
        interaction = AsyncMock()
        interaction.guild_id = self.bot.guild_id
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.roles = [SimpleNamespace(id=self.bot.role_id)]
        interaction.guild_id = 999
        with self.assertRaises(app_commands.CheckFailure):
            self.bot.require_timer_role(interaction)
        interaction.guild_id = self.bot.guild_id
        interaction.user = SimpleNamespace(roles=[SimpleNamespace(id=self.bot.role_id)])
        with self.assertRaises(app_commands.CheckFailure):
            self.bot.require_timer_role(interaction)
        interaction.user = MagicMock(spec=discord.Member)
        self.bot.role_id = self.bot.guild_id
        interaction.user.roles = [SimpleNamespace(id=self.bot.guild_id)]
        with self.assertRaises(app_commands.CheckFailure):
            self.bot.require_timer_role(interaction)

    async def test_members_without_edit_role_can_still_read_schedule(self):
        interaction = AsyncMock()
        interaction.guild_id = self.bot.guild_id
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.roles = []
        for name in ('worldbossregister', 'jadwal'):
            command = self.bot.tree.get_command(name)
            for check in command.checks:
                self.assertTrue(await check(interaction))
            await command.callback(interaction)
        self.assertEqual(interaction.response.send_message.await_count, 2)
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), ())

    async def test_invalid_time_preserves_existing_timer(self):
        await self.update_timer()
        previous = self.bot.store.timers(self.bot.guild_id)
        with self.assertRaises(ValueError):
            await self.update_timer(waktu='bad')
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), previous)

    async def test_new_indices_choices_updates_delivery_and_restart(self):
        command = self.bot.tree.get_command('worldbossregister')
        parameter = next(p for p in command.parameters if p.name == 'index')
        self.assertEqual(parameter.choices, [])
        self.assertTrue(parameter.autocomplete)
        await self.update_timer(index='4.3', waktu='08:20')
        await self.update_timer(index='4.1', waktu='08:30')
        timers = {timer.index: timer for timer in self.bot.store.timers(self.bot.guild_id)}
        self.assertEqual(timers['4.3'].start.strftime('%H:%M'), '15:00')
        self.assertEqual(timers['4.1'].start.strftime('%H:%M'), '15:10')
        await self.bot.deliver_due(datetime(2026, 10, 30, 14, 30, tzinfo=WIB))
        self.assertIn('Index 4.3', self.bot.send_notice.call_args.args[0])
        await self.bot.deliver_due(datetime(2026, 10, 30, 14, 40, tzinfo=WIB))
        self.assertIn('Index 4.1', self.bot.send_notice.call_args.args[0])
        self.assertEqual(self.bot.send_notice.await_count, 2)
        await self.bot.close()
        self.bot = TrexBot()
        self.bot.send_notice = AsyncMock()
        self.assertEqual(len(self.bot.store.timers(self.bot.guild_id)), 2)
        await self.bot.deliver_due(datetime(2026, 10, 31, 14, 30, tzinfo=WIB))
        self.bot.send_notice.assert_not_awaited()

    async def test_jadwal_includes_new_indices_without_truncation(self):
        interaction = AsyncMock()
        with patch('bot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await self.bot.tree.get_command('jadwal').callback(interaction)
        self.assertIn('Belum ada jadwal aktif', interaction.response.send_message.call_args.args[0])
        await self.update_timer(index='4.3', waktu='08:20')
        await self.update_timer(index='4.1', waktu='08:30')
        with patch('bot.datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
            await self.bot.tree.get_command('jadwal').callback(interaction)
        message = interaction.response.send_message.call_args.args[0]
        self.assertIn('Pasangan tempat + index aktif: 2', message)
        self.assertEqual(message.count('**Index'), 2)
        for index in ('4.1', '4.3'):
            self.assertIn(f'**Index {index}', message)

    async def flush_voice(self):
        tasks = list(self.bot._voice_tasks.values())
        if tasks:
            import asyncio
            await asyncio.gather(*tasks)

    async def test_register_place_autocomplete_and_paged_40_index_schedule(self):
        from schedule import SUPPORTED_INDICES
        from raids import index_autocomplete
        self.assertEqual([x.value for x in await index_autocomplete(None, '8.')], ['8.1', '8.2', '8.3', '8.4', '8.5'])
        self.assertLessEqual(len(await index_autocomplete(None, '')), 25)
        command = self.bot.tree.get_command('worldbossregister')
        self.assertEqual([p.name for p in command.parameters], ['index', 'tempat', 'waktu', 'tanggal'])
        for index in SUPPORTED_INDICES:
            await self.update_timer(index=index)
        timers = self.bot.store.timers(self.bot.guild_id)
        self.assertEqual(len(timers), 40)
        self.assertTrue(all(t.place == 'Volcano' for t in timers))
        interaction = AsyncMock()
        for page in range(1, 20):
            with patch('bot.datetime') as clock:
                clock.now.return_value = datetime(2026, 10, 30, 13, 0, tzinfo=WIB)
                try:
                    await self.bot.tree.get_command('jadwal').callback(interaction, halaman=page)
                except ValueError:
                    break
            message = interaction.response.send_message.call_args.args[0]
            self.assertLessEqual(len(message), 2000)
            if page == 1:
                self.assertIn('Tempat: Volcano', message)
        self.assertGreater(interaction.response.send_message.await_count, 1)

    async def test_voice_receipt_prevents_duplicates_independently_of_text(self):
        await self.morning_timer()
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        now = datetime(2026, 10, 30, 10, 50, tzinfo=WIB)
        await self.bot.deliver_due(now)
        await self.flush_voice()
        await self.bot.deliver_due(now + timedelta(seconds=5))
        await self.flush_voice()
        self.bot.send_notice.assert_awaited_once()
        self.bot.voice.announce.assert_awaited_once()
        self.assertEqual(self.bot.voice.announce.call_args.args[0].minutes_before, 30)

    async def test_spawn_trigger_sends_text_and_shared_voice_once(self):
        await self.update_timer()
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        now = datetime(2026, 10, 30, 18, 0, tzinfo=WIB)
        await self.bot.deliver_due(now)
        await self.flush_voice()
        await self.bot.deliver_due(now + timedelta(seconds=5))
        await self.flush_voice()
        self.bot.send_notice.assert_awaited_once()
        self.bot.voice.announce.assert_awaited_once()
        reminder = self.bot.voice.announce.call_args.args[0]
        self.assertEqual((reminder.index, reminder.minutes_before), ('3.1', 0))
        self.assertEqual(self.bot.voice.recording_for(reminder).name, 'spawn.mp3')

    async def test_voice_failure_retries_without_resending_text(self):
        await self.morning_timer()
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(side_effect=RuntimeError('TTS offline'))
        now = datetime(2026, 10, 30, 10, 50, tzinfo=WIB)
        await self.bot.deliver_due(now)
        await self.flush_voice()
        await self.bot.deliver_due(now + timedelta(seconds=5))
        await self.flush_voice()
        self.assertEqual(self.bot.voice.announce.await_count, 1)
        self.bot.voice.announce.side_effect = None
        self.bot.voice.announce.return_value = True
        await self.bot.deliver_due(now + timedelta(seconds=15))
        await self.flush_voice()
        self.assertEqual(self.bot.voice.announce.await_count, 2)
        self.bot.send_notice.assert_awaited_once()

    async def test_voice_can_succeed_even_when_text_fails(self):
        await self.morning_timer()
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        self.bot.send_notice.side_effect = ValueError('Text permission denied')
        await self.bot.deliver_due(datetime(2026, 10, 30, 10, 50, tzinfo=WIB))
        await self.flush_voice()
        self.bot.voice.announce.assert_awaited_once()

    async def test_voice_job_is_invalidated_by_timer_update(self):
        await self.morning_timer()
        event = effective_reminders(date(2026, 10, 30), slots=(), timers=self.bot.store.timers(123))[0]
        with patch('bot.datetime') as clock:
            clock.now.return_value = event.trigger
            self.assertTrue(self.bot.voice_is_current(event))
        await self.update_timer(waktu='11:30')
        with patch('bot.datetime') as clock:
            clock.now.return_value = event.trigger
            self.assertFalse(self.bot.voice_is_current(event))

    async def test_voice_command_is_admin_only_and_reports_disabled_setting(self):
        command = self.bot.tree.get_command('tesvoice')
        self.assertTrue(command.default_permissions.manage_guild)
        with self.assertRaisesRegex(ValueError, 'VOICE_CHANNEL_ID'):
            await command.callback(AsyncMock())

    async def test_voice_test_selects_test_recording(self):
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        await self.bot.tree.get_command('tesvoice').callback(AsyncMock())
        self.bot.voice.announce.assert_awaited_once_with()
        self.assertEqual(self.bot.voice.recording_for().name, 'test.mp3')

    async def test_unsupported_offsets_do_not_queue_voice(self):
        await self.morning_timer()
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        await self.bot.deliver_due(datetime(2026, 10, 30, 11, 15, tzinfo=WIB))
        await self.flush_voice()
        self.bot.send_notice.assert_awaited_once()
        self.bot.voice.announce.assert_not_awaited()

    async def test_voice_index31_h30_h15_select_correct_recordings_without_changing_timers(self):
        await self.update_timer(index='3.1', waktu='11:20')
        original_timers = self.bot.store.timers(self.bot.guild_id)
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        command = self.bot.tree.get_command('tesvoice')
        parameters = {parameter.name: parameter for parameter in command.parameters}
        self.assertEqual([choice.value for choice in parameters['menit'].choices], [30, 15, 0])
        for offset in (30, 15):
            interaction = AsyncMock()
            await command.callback(interaction, index='3.1', menit=offset)
            reminder = self.bot.voice.announce.call_args.args[0]
            self.assertEqual((reminder.index, reminder.minutes_before), ('3.1', offset))
            self.assertEqual(self.bot.voice.recording_for(reminder).name, f'3_1_h{offset}.mp3')
            self.assertIn(f'index 3.1 H-{offset}', interaction.followup.send.call_args.args[0])
        self.assertEqual(self.bot.store.timers(self.bot.guild_id), original_timers)
        self.bot.send_notice.assert_not_awaited()

    async def test_spawn_voice_test_selects_shared_recording(self):
        self.bot.voice.channel_id = 888
        self.bot.voice.announce = AsyncMock(return_value=True)
        await self.bot.tree.get_command('tesvoice').callback(AsyncMock(), index='3.1', menit=0)
        reminder = self.bot.voice.announce.call_args.args[0]
        self.assertEqual(reminder.minutes_before, 0)
        self.assertEqual(self.bot.voice.recording_for(reminder).name, 'spawn.mp3')
        self.bot.send_notice.assert_not_awaited()

    async def test_voice_index_test_rejects_partial_or_unsupported_options(self):
        command = self.bot.tree.get_command('tesvoice')
        for values in ({'index': '3.1'}, {'menit': 30},
                       {'index': '3.1', 'menit': 5}, {'index': '9.9', 'menit': 30}):
            with self.assertRaises(ValueError):
                await command.callback(AsyncMock(), **values)

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
        self.assertEqual({c.name for c in self.bot.tree.get_commands()},
                         {'worldbossregister', 'jadwal', 'tes', 'tesvoice', 'worldbossraid', 'rift', 'savage', 'raid', 'leaderboard', 'addpoint', 'point', 'remove',
                          'katalog', 'katalogadd', 'katalogremove', 'redeem', 'redeemhistory', 'redeemqueue', 'redeemstatus'})
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
