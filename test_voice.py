import asyncio
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from schedule import daily_reminders
from voice_alerts import VoiceAnnouncer, speech_for


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'VOICE_CHANNEL_ID': '888', 'TTS_VOICE': 'en-US-GuyNeural'})
        self.env.start()
        member = SimpleNamespace(id=999)
        self.guild = SimpleNamespace(id=123, unavailable=False, me=member, voice_client=None)
        self.channel = MagicMock(spec=discord.VoiceChannel)
        self.channel.guild = self.guild
        self.channel.permissions_for.return_value = SimpleNamespace(view_channel=True, connect=True, speak=True)
        self.guild.get_channel = Mock(return_value=self.channel)
        self.guild.fetch_channel = AsyncMock(return_value=self.channel)
        self.client = SimpleNamespace(get_guild=Mock(return_value=self.guild), user=member)
        self.voice_client = MagicMock()
        self.voice_client.disconnect = AsyncMock()
        self.voice_client.play.side_effect = lambda source, after: after(None)
        self.channel.connect = AsyncMock(return_value=self.voice_client)
        self.announcer = VoiceAnnouncer(self.client, 123)
        self.paths = []

        async def synthesize(text, path):
            path.write_bytes(b'fake mp3')
            self.paths.append(path)

        self.announcer.synthesize = AsyncMock(side_effect=synthesize)
        self.source = MagicMock()
        self.announcer.audio_source = Mock(return_value=self.source)

    async def asyncTearDown(self):
        self.env.stop()

    async def test_join_play_leave_and_remove_temporary_file(self):
        self.assertTrue(await self.announcer.speak('Test announcement'))
        self.channel.connect.assert_awaited_once_with(timeout=15, reconnect=False, self_deaf=True, self_mute=False)
        self.voice_client.play.assert_called_once()
        self.voice_client.disconnect.assert_awaited_once_with(force=True)
        self.source.cleanup.assert_called_once()
        self.assertFalse(self.paths[0].exists())

    async def test_disabled_voice_does_not_connect(self):
        self.announcer.channel_id = 0
        self.assertFalse(await self.announcer.speak('Test'))
        self.channel.connect.assert_not_awaited()

    async def test_stale_reminder_is_skipped_before_and_after_synthesis(self):
        self.assertFalse(await self.announcer.speak('Test', is_current=lambda: False))
        self.announcer.synthesize.assert_not_awaited()
        self.assertFalse(await self.announcer.speak('Test', is_current=Mock(side_effect=[True, False])))
        self.channel.connect.assert_not_awaited()
        self.assertFalse(self.paths[0].exists())

    async def test_stale_reminder_after_connect_disconnects_without_speaking(self):
        current = Mock(side_effect=[True, True, False])
        self.assertFalse(await self.announcer.speak('Test', is_current=current))
        self.voice_client.play.assert_not_called()
        self.voice_client.disconnect.assert_awaited_once()

    async def test_synthesis_failure_does_not_join(self):
        self.announcer.synthesize.side_effect = RuntimeError('TTS offline')
        with self.assertRaisesRegex(RuntimeError, 'TTS offline'):
            await self.announcer.speak('Test')
        self.channel.connect.assert_not_awaited()

    async def test_playback_failure_still_disconnects(self):
        self.voice_client.play.side_effect = lambda source, after: after(RuntimeError('Audio failed'))
        with self.assertRaisesRegex(RuntimeError, 'Audio failed'):
            await self.announcer.speak('Test')
        self.voice_client.disconnect.assert_awaited_once()
        self.source.cleanup.assert_called_once()

    async def test_cancellation_cleans_connection_and_audio(self):
        started = asyncio.Event()
        self.voice_client.play.side_effect = lambda source, after: started.set()
        task = asyncio.create_task(self.announcer.speak('Test'))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.voice_client.disconnect.assert_awaited_once()
        self.source.cleanup.assert_called_once()
        self.assertFalse(self.paths[0].exists())

    async def test_permissions_and_wrong_channel_are_rejected(self):
        self.channel.permissions_for.return_value.speak = False
        with self.assertRaisesRegex(ValueError, 'Connect, dan Speak'):
            await self.announcer.speak('Test')
        self.channel.connect.assert_not_awaited()
        self.channel.permissions_for.return_value.speak = True
        self.channel.guild = SimpleNamespace(id=456)
        with self.assertRaisesRegex(ValueError, 'GUILD_ID'):
            await self.announcer.destination()
        self.guild.get_channel.return_value = MagicMock(spec=discord.TextChannel)
        with self.assertRaisesRegex(ValueError, 'voice channel biasa'):
            await self.announcer.destination()

    async def test_existing_connection_is_not_hijacked(self):
        existing = MagicMock()
        self.guild.voice_client = existing
        with self.assertRaisesRegex(ValueError, 'sesi voice lain'):
            await self.announcer.speak('Test')
        self.channel.connect.assert_not_awaited()
        existing.disconnect.assert_not_called()

    async def test_parallel_announcements_are_serialized(self):
        await asyncio.gather(self.announcer.speak('First'), self.announcer.speak('Second'))
        self.assertEqual(self.voice_client.disconnect.await_count, 2)
        self.assertEqual(self.voice_client.play.call_count, 2)

    async def test_spoken_index_and_reminder(self):
        reminder = daily_reminders(date(2026, 10, 30))[0]
        self.assertIn('index three point one', speech_for(reminder))
        self.assertIn('in 30 minutes', speech_for(reminder))
        reminder = daily_reminders(date(2026, 10, 30))[3]
        self.assertIn('spawn window', speech_for(reminder))
        self.assertNotIn('in 0 minutes', speech_for(reminder))
