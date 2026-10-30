"""Optional voice announcements. No microphone recording or message reading."""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

import discord

log = logging.getLogger('trex.voice')


def speech_for(reminder):
    words = {'0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
             '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine', '.': 'point'}
    index = ' '.join(words.get(char, char) for char in reminder.index)
    if reminder.minutes_before:
        return (f'T-Rex on index {index} is expected to spawn in '
                f'{reminder.minutes_before} minutes. Get ready!')
    return f'The T-Rex spawn window on index {index} is starting now. Get ready!'


class VoiceAnnouncer:
    def __init__(self, client, guild_id):
        self.client = client
        self.guild_id = guild_id
        raw = os.getenv('VOICE_CHANNEL_ID', '').strip()
        self.channel_id = int(raw) if raw else 0
        if self.channel_id < 0:
            raise ValueError('VOICE_CHANNEL_ID harus ID voice channel, atau kosong untuk menonaktifkan.')
        self.voice = os.getenv('TTS_VOICE', 'en-US-GuyNeural').strip() or 'en-US-GuyNeural'
        self.lock = asyncio.Lock()

    @property
    def enabled(self):
        return bool(self.channel_id)

    async def destination(self):
        if not self.enabled:
            raise ValueError('Voice belum aktif. Isi VOICE_CHANNEL_ID lalu restart bot.')
        guild = self.client.get_guild(self.guild_id)
        if guild is None or guild.unavailable:
            raise ValueError('Server voice belum tersedia di koneksi bot. Periksa log startup.')
        channel = guild.get_channel(self.channel_id)
        if channel is None:
            channel = await guild.fetch_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel) or channel.guild.id != self.guild_id:
            raise ValueError('VOICE_CHANNEL_ID harus voice channel biasa pada GUILD_ID yang sama, bukan channel teks atau Stage.')
        member = guild.me
        if member is None:
            if self.client.user is None:
                raise ValueError('Identitas bot belum siap untuk voice.')
            member = await guild.fetch_member(self.client.user.id)
        perms = channel.permissions_for(member)
        if not (perms.view_channel and perms.connect and perms.speak):
            raise ValueError('Bot perlu View Channel, Connect, dan Speak pada voice channel tujuan.')
        return channel

    async def synthesize(self, text, path):
        # Loaded only when enabled; text notifications still work without voice packages.
        import edge_tts
        await edge_tts.Communicate(text, self.voice).save(str(path))

    def audio_source(self, path):
        import imageio_ffmpeg
        executable = os.getenv('FFMPEG_PATH', '').strip() or imageio_ffmpeg.get_ffmpeg_exe()
        # Opus is encoded by FFmpeg so a separate system libopus isn't required here.
        return discord.FFmpegOpusAudio(str(path), executable=executable)

    async def speak(self, text, is_current=lambda: True):
        if not self.enabled:
            return False
        async with self.lock:
            if not is_current():
                return False
            voice_client = None
            source = None
            try:
                async with asyncio.timeout(60):
                    channel = await self.destination()
                    # Don't move/disconnect a session belonging to a different operation.
                    if channel.guild.voice_client is not None:
                        raise ValueError('Bot sedang memiliki sesi voice lain; coba lagi setelah selesai.')
                    with tempfile.TemporaryDirectory(prefix='trex-voice-') as tmp:
                        path = Path(tmp) / 'announcement.mp3'
                        await asyncio.wait_for(self.synthesize(text, path), timeout=20)
                        if not is_current():
                            return False
                        voice_client = await channel.connect(timeout=15, reconnect=False,
                                                             self_deaf=True, self_mute=False)
                        # Recheck after the network handshake: an index may have been updated.
                        if not is_current():
                            return False
                        source = self.audio_source(path)
                        loop = asyncio.get_running_loop()
                        finished = loop.create_future()

                        def complete(error):
                            if not finished.done():
                                if error:
                                    finished.set_exception(error)
                                else:
                                    finished.set_result(None)

                        def after(error):
                            loop.call_soon_threadsafe(complete, error)

                        voice_client.play(source, after=after)
                        await asyncio.wait_for(finished, timeout=30)
                        log.info('Pengumuman voice selesai: channel_id=%s', self.channel_id)
                        return True
            finally:
                if voice_client is not None:
                    try:
                        voice_client.stop()
                        await asyncio.wait_for(voice_client.disconnect(force=True), timeout=5)
                    except Exception as exc:
                        log.warning('Gagal membersihkan koneksi voice: %s', exc)
                if source is not None:
                    source.cleanup()
