"""Optional voice announcements. No microphone recording or message reading."""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

import discord

log = logging.getLogger('trex.voice')


ROAR = 'RAWWRRRRR!'
TEST_SPEECH = f'Ini adalah tes notifikasi T-Rex. Pengumuman suara sudah siap. Bersiaplah! {ROAR}'


def speech_for(reminder):
    words = {'0': 'nol', '1': 'satu', '2': 'dua', '3': 'tiga', '4': 'empat',
             '5': 'lima', '6': 'enam', '7': 'tujuh', '8': 'delapan', '9': 'sembilan', '.': 'titik'}
    index = ' '.join(words.get(char, char) for char in reminder.index)
    if reminder.minutes_before:
        message = (f'Perhatian! T-Rex di indeks {index} diperkirakan muncul dalam '
                   f'{reminder.minutes_before} menit. Bersiaplah!')
    else:
        message = f'Perhatian! Jendela kemunculan T-Rex di indeks {index} dimulai sekarang. Bersiaplah!'
    return f'{message} {ROAR}'


class VoiceAnnouncer:
    def __init__(self, client, guild_id):
        self.client = client
        self.guild_id = guild_id
        raw = os.getenv('VOICE_CHANNEL_ID', '').strip()
        self.channel_id = int(raw) if raw else 0
        if self.channel_id < 0:
            raise ValueError('VOICE_CHANNEL_ID harus ID voice channel, atau kosong untuk menonaktifkan.')
        self.voice = os.getenv('TTS_VOICE', 'id-ID-ArdiNeural').strip() or 'id-ID-ArdiNeural'
        raw_outro = os.getenv('VOICE_OUTRO_PATH', 'assets/outro.mp3').strip()
        self.outro_path = Path(raw_outro) if raw_outro else None
        if self.outro_path is not None and not self.outro_path.is_absolute():
            self.outro_path = Path(__file__).resolve().parent / self.outro_path
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

    async def speak(self, text, is_current=lambda: True):
        if not self.enabled:
            return False
        async with self.lock:
            if not is_current():
                return False
            voice_client = None
            try:
                async with asyncio.timeout(60):
                    if self.outro_path is not None and not self.outro_path.is_file():
                        raise ValueError('Audio penutup tidak ditemukan. Perbarui assets/outro.mp3 '
                                         'atau periksa VOICE_OUTRO_PATH.')
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
                        # Stay in the same connection until speech + roar + original MP3 finish.
                        await self.play_track(voice_client, path)
                        if self.outro_path is not None:
                            await self.play_track(voice_client, self.outro_path)
                        log.info('Pengumuman voice selesai: channel_id=%s', self.channel_id)
                        return True
            finally:
                if voice_client is not None:
                    try:
                        voice_client.stop()
                        await asyncio.wait_for(voice_client.disconnect(force=True), timeout=5)
                    except Exception as exc:
                        log.warning('Gagal membersihkan koneksi voice: %s', exc)
