import asyncio
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord
from schedule import daily_reminders, Reminder, SUPPORTED_INDICES
from voice_alerts import VoiceAnnouncer, RECORDINGS


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'VOICE_CHANNEL_ID': '888', 'TTS_VOICE': 'id-ID-ArdiNeural', 'VOICE_OUTRO_PATH': ''})
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
        self.source = MagicMock()
        self.announcer.audio_source = Mock(return_value=self.source)

    async def asyncTearDown(self):
        self.env.stop()

    async def test_join_play_leave_and_preserve_original_recording(self):
        self.assertTrue(await self.announcer.announce())
        self.channel.connect.assert_awaited_once_with(timeout=15, reconnect=False, self_deaf=True, self_mute=False)
        self.voice_client.play.assert_called_once()
        self.voice_client.disconnect.assert_awaited_once_with(force=True)
        self.source.cleanup.assert_called_once()
        self.assertTrue(self.announcer.recording_for().exists())

    async def test_disabled_voice_does_not_connect(self):
        self.announcer.channel_id = 0
        self.assertFalse(await self.announcer.announce())
        self.channel.connect.assert_not_awaited()

    async def test_stale_reminder_is_skipped_before_and_after_destination_check(self):
        self.assertFalse(await self.announcer.announce(is_current=lambda: False))
        self.assertFalse(await self.announcer.announce(is_current=Mock(side_effect=[True, False])))
        self.channel.connect.assert_not_awaited()
        self.assertTrue(self.announcer.recording_for().exists())

    async def test_stale_reminder_after_connect_disconnects_without_speaking(self):
        current = Mock(side_effect=[True, True, False])
        self.assertFalse(await self.announcer.announce(is_current=current))
        self.voice_client.play.assert_not_called()
        self.voice_client.disconnect.assert_awaited_once()

    async def test_missing_recording_does_not_join(self):
        self.announcer.audio_dir = Path('/nonexistent/recordings')
        with self.assertRaisesRegex(ValueError, 'Rekaman tidak ditemukan'):
            await self.announcer.announce()
        self.channel.connect.assert_not_awaited()

    async def test_playback_failure_still_disconnects(self):
        self.voice_client.play.side_effect = lambda source, after: after(RuntimeError('Audio failed'))
        with self.assertRaisesRegex(RuntimeError, 'Audio failed'):
            await self.announcer.announce()
        self.voice_client.disconnect.assert_awaited_once()
        self.source.cleanup.assert_called_once()

    async def test_cancellation_cleans_connection_and_audio(self):
        started = asyncio.Event()
        self.voice_client.play.side_effect = lambda source, after: started.set()
        task = asyncio.create_task(self.announcer.announce())
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.voice_client.disconnect.assert_awaited_once()
        self.source.cleanup.assert_called_once()
        self.assertTrue(self.announcer.recording_for().exists())

    async def test_permissions_and_wrong_channel_are_rejected(self):
        self.channel.permissions_for.return_value.speak = False
        with self.assertRaisesRegex(ValueError, 'Connect, dan Speak'):
            await self.announcer.announce()
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
            await self.announcer.announce()
        self.channel.connect.assert_not_awaited()
        existing.disconnect.assert_not_called()

    async def test_parallel_announcements_are_serialized(self):
        await asyncio.gather(self.announcer.announce(), self.announcer.announce())
        self.assertEqual(self.voice_client.disconnect.await_count, 2)
        self.assertEqual(self.voice_client.play.call_count, 2)

    async def test_default_recordings_directory_and_outro_configuration(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VOICE_AUDIO_DIR', None)
            os.environ.pop('VOICE_OUTRO_PATH', None)
            announcer = VoiceAnnouncer(self.client, 123)
        self.assertEqual(announcer.recording_for().name, 'test.mp3')
        self.assertEqual(announcer.outro_path.name, 'outro.mp3')
        self.assertTrue(announcer.outro_path.is_file())

    async def test_speech_then_original_mp3_then_disconnect(self):
        outro = Path(__file__).resolve().parent / 'assets' / 'outro.mp3'
        self.announcer.outro_path = outro
        speech_source, outro_source = MagicMock(), MagicMock()
        self.announcer.audio_source.side_effect = [speech_source, outro_source]
        self.assertTrue(await self.announcer.announce())
        tracks = [call.args[0] for call in self.announcer.audio_source.call_args_list]
        self.assertEqual(tracks[0].name, 'test.mp3')
        self.assertEqual(tracks[1], outro)
        self.assertEqual([call.args[0] for call in self.voice_client.play.call_args_list],
                         [speech_source, outro_source])
        self.voice_client.disconnect.assert_awaited_once()
        speech_source.cleanup.assert_called_once()
        outro_source.cleanup.assert_called_once()
        self.assertTrue(outro.exists(), 'original outro must not be deleted')

    async def test_missing_outro_has_clear_error_before_joining(self):
        self.announcer.outro_path = Path('/nonexistent/trex-outro.mp3')
        with self.assertRaisesRegex(ValueError, 'assets/outro.mp3'):
            await self.announcer.announce()
        self.channel.connect.assert_not_awaited()

    async def test_outro_playback_error_still_disconnects(self):
        self.announcer.outro_path = Path(__file__).resolve().parent / 'assets' / 'outro.mp3'
        count = 0
        def play(source, after):
            nonlocal count
            count += 1
            after(None if count == 1 else RuntimeError('Outro failed'))
        self.voice_client.play.side_effect = play
        with self.assertRaisesRegex(RuntimeError, 'Outro failed'):
            await self.announcer.announce()
        self.voice_client.disconnect.assert_awaited_once()

    async def test_volume_configuration_accepts_gain_and_rejects_invalid_values(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VOICE_VOLUME', None)
            self.assertEqual(VoiceAnnouncer(self.client, 123).volume, 5.0)
        for value in ('0.1', '1', '2.5', '5'):
            with patch.dict(os.environ, {'VOICE_VOLUME': value}):
                self.assertEqual(VoiceAnnouncer(self.client, 123).volume, float(value))
        for value in ('0', '-1', '5.1', 'nan', 'inf', 'abc'):
            with patch.dict(os.environ, {'VOICE_VOLUME': value}):
                with self.assertRaisesRegex(ValueError, 'VOICE_VOLUME'):
                    VoiceAnnouncer(self.client, 123)

    async def test_gain_and_limiter_apply_to_both_announcement_and_outro(self):
        self.announcer.volume = 3.0
        with patch('voice_alerts.discord.FFmpegOpusAudio') as source:
            # Call the real method; the fixture mocks it for playback tests.
            for path in (self.announcer.recording_for(), Path('assets/outro.mp3')):
                VoiceAnnouncer.audio_source(self.announcer, path)
                self.assertEqual(source.call_args.kwargs['options'],
                                 '-filter:a volume=3,alimiter=limit=0.95:level=false')
        self.assertEqual(source.call_count, 2)

    async def test_all_eight_recording_mappings_and_files(self):
        start = daily_reminders(date(2026, 10, 30))[0].start
        self.assertEqual(len(RECORDINGS), 8)
        for index in SUPPORTED_INDICES:
            for offset in (30, 15):
                reminder = Reminder(index, start, offset)
                path = self.announcer.recording_for(reminder)
                self.assertEqual(path.name, f'{index.replace(".", "_")}_h{offset}.mp3')
                self.assertTrue(path.is_file())
        for offset in (5, 0):
            reminder = Reminder('3.1', start, offset)
            self.assertFalse(self.announcer.supports(reminder))
            with self.assertRaises(ValueError):
                self.announcer.recording_for(reminder)
