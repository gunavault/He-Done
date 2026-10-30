"""Optional voice announcements. No microphone recording or message reading."""
import asyncio
import logging
import math
import os
from pathlib import Path

import discord
from schedule import SUPPORTED_INDICES

log = logging.getLogger('trex.voice')


RECORDINGS = {(index, minutes): f'{index.replace(".", "_")}_h{minutes}.mp3'
              for index in SUPPORTED_INDICES for minutes in (30, 15)}


class VoiceAnnouncer:
    def __init__(self, client, guild_id):
        self.client = client
        self.guild_id = guild_id
        raw = os.getenv('VOICE_CHANNEL_ID', '').strip()
        self.channel_id = int(raw) if raw else 0
        if self.channel_id < 0:
            raise ValueError('VOICE_CHANNEL_ID harus ID voice channel, atau kosong untuk menonaktifkan.')
        raw_dir = os.getenv('VOICE_AUDIO_DIR', 'assets/voice').strip() or 'assets/voice'
        self.audio_dir = Path(raw_dir)
        if not self.audio_dir.is_absolute():
            self.audio_dir = Path(__file__).resolve().parent / self.audio_dir
        raw_outro = os.getenv('VOICE_OUTRO_PATH', 'assets/outro.mp3').strip()
        self.outro_path = Path(raw_outro) if raw_outro else None
        if self.outro_path is not None and not self.outro_path.is_absolute():
            self.outro_path = Path(__file__).resolve().parent / self.outro_path
        try:
            self.volume = float(os.getenv('VOICE_VOLUME', '5.0'))
        except ValueError:
            raise ValueError('VOICE_VOLUME harus angka antara 0.1 dan 5.0.') from None
        if not math.isfinite(self.volume) or not 0.1 <= self.volume <= 5.0:
            raise ValueError('VOICE_VOLUME harus angka antara 0.1 dan 5.0.')
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

    def supports(self, reminder):
        return (reminder.index, reminder.minutes_before) in RECORDINGS

    def recording_for(self, reminder=None):
        if reminder is None:
            return self.audio_dir / 'test.mp3'
        if not self.supports(reminder):
            raise ValueError('Rekaman voice tersedia hanya untuk index 3.1, 3.2, 4.1, 4.3 pada H-30/H-15.')
        return self.audio_dir / RECORDINGS[(reminder.index, reminder.minutes_before)]

    def audio_source(self, path):
        import imageio_ffmpeg
        executable = os.getenv('FFMPEG_PATH', '').strip() or imageio_ffmpeg.get_ffmpeg_exe()
        # Opus is encoded by FFmpeg so a separate system libopus isn't required here.
        return discord.FFmpegOpusAudio(
            str(path), executable=executable,
            options=f'-filter:a volume={self.volume:g},alimiter=limit=0.95:level=false')

    async def play_track(self, voice_client, path):
        source = self.audio_source(path)
        try:
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
        finally:
            voice_client.stop()
            source.cleanup()

    async def announce(self, reminder=None, is_current=lambda: True):
        if not self.enabled:
            return False
        async with self.lock:
            if not is_current():
                return False
            voice_client = None
            try:
                async with asyncio.timeout(60):
                    path = self.recording_for(reminder)
                    if not path.is_file():
                        raise ValueError(f'Rekaman tidak ditemukan: {path}. Perbarui folder assets/voice.')
                    if self.outro_path is not None and not self.outro_path.is_file():
                        raise ValueError('Audio penutup tidak ditemukan. Perbarui assets/outro.mp3 '
                                         'atau periksa VOICE_OUTRO_PATH.')
                    channel = await self.destination()
                    if channel.guild.voice_client is not None:
                        raise ValueError('Bot sedang memiliki sesi voice lain; coba lagi setelah selesai.')
                    if not is_current():
                        return False
                    voice_client = await channel.connect(timeout=15, reconnect=False,
                                                         self_deaf=True, self_mute=False)
                    if not is_current():
                        return False
                    await self.play_track(voice_client, path)
                    if self.outro_path is not None:
                        await self.play_track(voice_client, self.outro_path)
                    log.info('Rekaman voice selesai: channel_id=%s file=%s', self.channel_id, path.name)
                    return True
            finally:
                if voice_client is not None:
                    try:
                        voice_client.stop()
                        await asyncio.wait_for(voice_client.disconnect(force=True), timeout=5)
                    except Exception as exc:
                        log.warning('Gagal membersihkan koneksi voice: %s', exc)
