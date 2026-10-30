import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from schedule import WIB, Store, daily_reminders, due_reminders, parse_times, parse_offsets, next_spawn_message, calculate_timer, effective_reminders, SUPPORTED_INDICES, Reminder

from voice_alerts import VoiceAnnouncer

ROOT = Path(__file__).resolve().parent
log = logging.getLogger('trex')


def required(name):
    value = os.getenv(name, '').strip()
    if not value or value.startswith('ISI_'):
        raise ValueError(f'Isi {name} di file .env terlebih dahulu.')
    return value


class TrexBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.guild_id = int(required('GUILD_ID'))
        self.channel_id = int(required('CHANNEL_ID'))
        self.role_id = int(required('ROLE_ID'))
        self.slots = tuple(sorted(
            [(index, at) for index, env_name, default in (
                ('3.1', 'INDEX_31_TIMES', '11:20,18:00'),
                ('3.2', 'INDEX_32_TIMES', '12:47,19:27'))
             for at in parse_times(os.getenv(env_name, default))], key=lambda slot: slot[1]))
        self.offsets = parse_offsets(os.getenv('REMINDER_MINUTES', '30,15'))
        path = Path(os.getenv('DB_PATH', 'data/trex.sqlite3'))
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(path)
        self.lock = asyncio.Lock()
        self.tree = app_commands.CommandTree(self)
        self.target_guild = discord.Object(id=self.guild_id)
        self.voice = VoiceAnnouncer(self, self.guild_id)
        self._voice_tasks = {}
        self._voice_retry_after = {}
        self.register_commands()

    def require_timer_role(self, interaction):
        member = interaction.user
        if (interaction.guild_id != self.guild_id or self.role_id == self.guild_id
                or not isinstance(member, discord.Member)
                or not any(role.id == self.role_id for role in member.roles)):
            raise app_commands.CheckFailure(
                'Hanya anggota dengan role yang ditentukan pada ROLE_ID di .env '
                'yang dapat memperbarui timer.')

    def register_commands(self):
        async def check_server(interaction):
            if interaction.guild_id != self.guild_id:
                raise app_commands.CheckFailure('Perintah hanya untuk server yang diatur di .env.')
            return True

        @self.tree.command(name='trex', description='Lihat spawn terdekat atau perbarui timer index dengan index dan waktu')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.choices(index=[app_commands.Choice(name=x, value=x) for x in SUPPORTED_INDICES])
        @app_commands.describe(index='Index yang timernya diperbarui', waktu='Waktu terakhir muncul, HH:MM WIB',
                               tanggal='Opsional YYYY-MM-DD; default hari ini WIB')
        async def trex(interaction: discord.Interaction, index: str | None = None,
                       waktu: str | None = None, tanggal: str | None = None):
            if index is None and waktu is None and tanggal is None:
                await interaction.response.send_message(
                    next_spawn_message(datetime.now(WIB), self.slots, self.store.timers(self.guild_id)),
                    allowed_mentions=discord.AllowedMentions.none())
                return
            if index is None or waktu is None:
                raise ValueError('Untuk update, isi keduanya: /trex index:3.1 waktu:11:20. Tanpa opsi untuk melihat jadwal.')
            self.require_timer_role(interaction)
            await interaction.response.defer(ephemeral=True)
            # The same lock is held by the sender: no old timer can be queued after this update.
            async with self.lock:
                now = datetime.now(WIB)
                timer = calculate_timer(index, waktu, tanggal, now)
                self.store.set_timer(self.guild_id, timer)
                events = [event for delta in (0, 1)
                          for event in effective_reminders(now.date() + timedelta(days=delta),
                              self.slots, (0,), self.store.timers(self.guild_id))
                          if event.index == index and (event.start >= now or event.end > now)]
                event = min(events, key=lambda event: event.start)
            lines = [f'✅ Timer index **{index}** diperbarui.',
                     f'Terakhir muncul: {timer.observed:%d-%m-%Y %H:%M} WIB',
                     f'Perkiraan spawn berikut: **{event.start:%d-%m-%Y %H:%M}–{event.end:%H:%M} WIB**']
            for offset in self.offsets:
                at = event.start - timedelta(minutes=offset)
                label = f'H-{offset}' if offset else 'Jendela spawn dimulai'
                status = ' (sudah lewat; dilewati)' if at + timedelta(seconds=60) <= now else ''
                lines.append(f'{label}: {at:%d-%m %H:%M} WIB{status}')
            lines.append('Jadwal lama index ini diganti. Berulang setiap hari sampai diperbarui lagi.')
            await interaction.followup.send('\n'.join(lines), ephemeral=True,
                                             allowed_mentions=discord.AllowedMentions.none())

        @self.tree.command(name='jadwal', description='Lihat jadwal T-Rex berikutnya dan pengingat dalam WIB')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def jadwal(interaction: discord.Interaction):
            now = datetime.now(WIB)
            timers = self.store.timers(self.guild_id)
            events = [event for delta in (0, 1)
                      for event in effective_reminders(now.date() + timedelta(days=delta),
                          self.slots, (0,), timers) if event.start >= now or (event.end and event.end > now)]
            lines = ['🦖 **Jadwal berikutnya — WIB, berulang setiap hari**']
            overridden = {timer.index for timer in timers}
            daily_count = sum(index not in overridden for index, _ in self.slots) + len(timers)
            for event in sorted(events, key=lambda event: event.start)[:daily_count]:
                window = f'{event.start:%H:%M}' + (f'–{event.end:%H:%M}' if event.end else '')
                lines.append(f'\n**Index {event.index} — {event.start:%d-%m} {window} WIB**')
                for offset in self.offsets:
                    at = event.start - timedelta(minutes=offset)
                    label = f'H-{offset}' if offset else 'Spawn dimulai'
                    lines.append(f'{label}: {at:%d-%m %H:%M} WIB')
            active_indices = {index for index, _ in self.slots} | overridden
            unconfigured = [index for index in SUPPORTED_INDICES if index not in active_indices]
            if unconfigured:
                lines.append('\nIndex belum diisi: ' + ', '.join(unconfigured) + '. Isi lewat /trex index:<index> waktu:<HH:MM>.')
            await interaction.response.send_message('\n'.join(lines), ephemeral=True)

        @self.tree.command(name='tes', description='Kirim pesan uji ke channel tujuan, termasuk tag role')
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.checks.has_permissions(manage_guild=True)
        @app_commands.check(check_server)
        async def tes(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            await self.send_notice('🦖 **Tes notifikasi T-Rex** — ini hanya pesan uji.')
            await interaction.followup.send('Pesan uji dan tag role dikirim.', ephemeral=True)

        @self.tree.command(name='tesvoice', description='Tes pengumuman suara di voice channel yang diatur')
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.checks.has_permissions(manage_guild=True)
        @app_commands.check(check_server)
        @app_commands.choices(
            index=[app_commands.Choice(name=x, value=x) for x in SUPPORTED_INDICES],
            menit=[app_commands.Choice(name='H-30 menit', value=30),
                   app_commands.Choice(name='H-15 menit', value=15)])
        @app_commands.describe(index='Opsional: pilih index rekaman yang ingin diuji',
                               menit='Isi bersama index: H-30 atau H-15; langsung diputar sekarang')
        async def tesvoice(interaction: discord.Interaction, index: str | None = None,
                           menit: int | None = None):
            if (index is None) != (menit is None):
                raise ValueError('Isi keduanya: /tesvoice index:3.1 menit:30. Tanpa opsi untuk test.mp3.')
            if index is not None and (index not in SUPPORTED_INDICES or menit not in (30, 15)):
                raise ValueError('Pilih index 3.1, 3.2, 4.1, atau 4.3 dan menit 30 atau 15.')
            await interaction.response.defer(ephemeral=True)
            if not self.voice.enabled:
                raise ValueError('Voice belum aktif. Isi VOICE_CHANNEL_ID lalu restart bot.')
            try:
                if index is None:
                    await self.voice.announce()
                else:
                    await self.voice.announce(Reminder(index, datetime.now(WIB), menit))
            except Exception as exc:
                log.warning('Tes voice gagal: %s', exc)
                await interaction.followup.send(
                    'Tes voice gagal. Periksa izin Connect/Speak, dependencies voice, '
                    'dan koneksi jaringan. Detail ada di Console Wispbyte.', ephemeral=True)
            else:
                label = f' index {index} H-{menit}' if index is not None else ''
                await interaction.followup.send(f'Tes suara{label} selesai. Bot sudah keluar dari voice channel.', ephemeral=True)

        self.tree.on_error = self.command_error

    async def setup_hook(self):
        # Sync optional /trex parameters and remove obsolete commands from this guild.
        self.tree.copy_global_to(guild=self.target_guild)
        await self.tree.sync(guild=self.target_guild)
        self.notify.start()

    async def on_ready(self):
        log.info('Bot terhubung: user=%s bot_id=%s; GUILD_ID=%s CHANNEL_ID=%s ROLE_ID=%s; '
                 'guilds_intent=%s; cached_guilds=%s; pengingat=%s menit',
                 self.user, self.user.id if self.user else None, self.guild_id,
                 self.channel_id, self.role_id, self.intents.guilds,
                 [(guild.id, guild.name) for guild in self.guilds], self.offsets)
        log.info('Voice: enabled=%s VOICE_CHANNEL_ID=%s mode=recorded_mp3 VOICE_AUDIO_DIR=%s',
                 self.voice.enabled, self.voice.channel_id, self.voice.audio_dir)
        try:
            channel, role = await self.destination()
        except (discord.HTTPException, ValueError) as exc:
            log.warning('Validasi tujuan gagal saat startup: %s', exc)
        else:
            log.info('Tujuan siap: guild_id=%s channel_id=%s role_id=%s',
                     channel.guild.id, channel.id, role.id)

    async def destination(self):
        guild = self.get_guild(self.guild_id)
        if guild is None or guild.unavailable:
            # A cache miss doesn't prove that the bot isn't a member. Verify through REST.
            log.warning('Guild %s belum tersedia di cache; memeriksa Discord API. '
                        'bot_id=%s cached_guild_ids=%s', self.guild_id,
                        self.user.id if self.user else None, [g.id for g in self.guilds])
            try:
                guild = await self.fetch_guild(self.guild_id)
            except (discord.Forbidden, discord.NotFound) as exc:
                raise ValueError(
                    f'Discord API menolak akses server {self.guild_id} (HTTP {exc.status}); '
                    f'bot_id aktif={self.user.id if self.user else None}. '
                    'Cocokkan ID bot ini dengan bot yang diundang, serta GUILD_ID aktif di Startup/.env.'
                ) from exc
        channel = guild.get_channel(self.channel_id)
        if channel is None:
            # fetch_guild doesn't populate channel/member caches.
            channel = await guild.fetch_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('CHANNEL_ID harus channel teks di server GUILD_ID yang diatur.')
        role = guild.get_role(self.role_id)
        if role is None or role.is_default():
            raise ValueError(f'ROLE_ID {self.role_id} tidak ditemukan di server {self.guild_id}, atau menggunakan @everyone.')
        member = guild.me
        if member is None:
            if self.user is None:
                raise ValueError('Identitas bot belum tersedia; tunggu koneksi Discord siap.')
            member = await guild.fetch_member(self.user.id)
        perms = channel.permissions_for(member)
        if not perms.view_channel or not perms.send_messages:
            raise ValueError('Bot perlu View Channel dan Send Messages pada channel tujuan.')
        if not role.mentionable and not perms.mention_everyone:
            raise ValueError('Aktifkan Allow anyone to @mention this role, atau izin Mention @everyone, @here, and All Roles untuk bot.')
        return channel, role

    async def send_notice(self, body):
        channel, role = await self.destination()
        await channel.send(
            f'{role.mention}\n{body}',
            allowed_mentions=discord.AllowedMentions(
                everyone=False, users=False, roles=[role], replied_user=False))

    async def deliver_due(self, now=None):
        """One scheduler tick, injectable clock for offline delivery tests."""
        async with self.lock:
            now = now or datetime.now(WIB)
            for reminder in due_reminders(now, self.slots, self.offsets, self.store.timers(self.guild_id)):
                key = f'{self.guild_id}|{reminder.key}'
                if not self.store.was_sent(key):
                    try:
                        await self.send_notice(reminder.message())
                    except (discord.HTTPException, ValueError) as exc:
                        log.warning('Gagal mengirim %s: %s; dicoba lagi selama tenggang 60 detik.', key, exc)
                    else:
                        self.store.mark_sent(key, now)
                        log.info('Terkirim: %s', key)
                self.queue_voice(reminder, key, now)

    def voice_is_current(self, reminder):
        now = datetime.now(WIB)
        return any(event.key == reminder.key for event in due_reminders(
            now, self.slots, self.offsets, self.store.timers(self.guild_id)))

    def queue_voice(self, reminder, key, now):
        voice_key = 'voice|' + key
        if (not self.voice.enabled or not self.voice.supports(reminder) or voice_key in self._voice_tasks
                or self.store.was_sent(voice_key)):
            return
        # Retry voice independently; never resend a successful text message for a voice failure.
        self._voice_retry_after = {k: at for k, at in self._voice_retry_after.items() if at > now}
        if voice_key in self._voice_retry_after:
            return
        self._voice_retry_after[voice_key] = now + timedelta(seconds=15)
        self._voice_tasks[voice_key] = asyncio.create_task(
            self.deliver_voice(reminder, voice_key), name='trex-voice')

    async def deliver_voice(self, reminder, voice_key):
        try:
            spoken = await self.voice.announce(reminder,
                                           is_current=lambda: self.voice_is_current(reminder))
            if spoken:
                self.store.mark_sent(voice_key, datetime.now(WIB))
                log.info('Voice terkirim: %s', voice_key)
        except Exception as exc:
            log.warning('Pengumuman voice gagal (%s): %s; notifikasi teks tetap terpisah.', voice_key, exc)
        finally:
            self._voice_tasks.pop(voice_key, None)

    @tasks.loop(seconds=5)
    async def notify(self):
        if self.is_ready():
            await self.deliver_due()

    @notify.before_loop
    async def before_notify(self):
        await self.wait_until_ready()

    async def command_error(self, interaction, error):
        original = getattr(error, 'original', error)
        if isinstance(original, app_commands.MissingPermissions):
            message = 'Perintah ini memerlukan izin Manage Server.'
        elif isinstance(original, (ValueError, app_commands.CheckFailure)):
            message = str(original)
        else:
            log.error('Perintah gagal', exc_info=(type(original), original, original.__traceback__))
            message = 'Perintah gagal. Periksa log bot dan izin channel.'
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def close(self):
        self.notify.cancel()
        task = self.notify.get_task()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
        voice_tasks = list(self._voice_tasks.values())
        for voice_task in voice_tasks:
            voice_task.cancel()
        if voice_tasks:
            await asyncio.gather(*voice_tasks, return_exceptions=True)
        self.store.close()
        await super().close()


if __name__ == '__main__':
    load_dotenv(ROOT / '.env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = required('DISCORD_TOKEN')
    TrexBot().run(token)
