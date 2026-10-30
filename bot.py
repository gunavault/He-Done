import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from schedule import WIB, Store, daily_reminders, due_reminders, parse_times, parse_offsets

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
        self.offsets = parse_offsets(os.getenv('REMINDER_MINUTES', '30,15,5,0'))
        path = Path(os.getenv('DB_PATH', 'data/trex.sqlite3'))
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(path)
        self.lock = asyncio.Lock()
        self.tree = app_commands.CommandTree(self)
        self.target_guild = discord.Object(id=self.guild_id)
        self.register_commands()

    def register_commands(self):
        async def check_server(interaction):
            if interaction.guild_id != self.guild_id:
                raise app_commands.CheckFailure('Perintah hanya untuk server yang diatur di .env.')
            return True

        @self.tree.command(name='jadwal', description='Lihat jam pengingat T-Rex harian dalam WIB')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def jadwal(interaction: discord.Interaction):
            day = datetime.now(WIB).date()
            lines = ['🦖 **Jadwal otomatis setiap hari — WIB**']
            for index, at in self.slots:
                reminders = [r for r in daily_reminders(day, self.slots, self.offsets)
                             if r.index == index and r.start.time() == at]
                lines.append(f'\n**Index {index} — Spawn {at:%H:%M} WIB**')
                for r in reminders:
                    label = f'H-{r.minutes_before}' if r.minutes_before else 'Spawn dimulai'
                    # Full date makes a configured midnight reminder clear.
                    lines.append(f'{label}: {r.trigger:%d-%m %H:%M} WIB')
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

        self.tree.on_error = self.command_error

    async def setup_hook(self):
        # Sync also removes the old /trex and /hapus manual commands in this guild.
        self.tree.copy_global_to(guild=self.target_guild)
        await self.tree.sync(guild=self.target_guild)
        self.notify.start()

    async def on_ready(self):
        log.info('Bot %s terhubung; jadwal harian WIB=%s, pengingat=%s menit',
                 self.user, self.slots, self.offsets)

    async def destination(self):
        guild = self.get_guild(self.guild_id)
        if guild is None:
            raise ValueError('Bot belum tergabung di GUILD_ID yang diatur.')
        channel = guild.get_channel(self.channel_id)
        role = guild.get_role(self.role_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError('CHANNEL_ID harus channel teks di server ini.')
        if role is None or role.is_default():
            raise ValueError('ROLE_ID tidak valid atau menggunakan @everyone.')
        member = guild.me
        if member is None:
            raise ValueError('Identitas bot belum tersedia di server.')
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
            for reminder in due_reminders(now, self.slots, self.offsets):
                key = f'{self.guild_id}|{reminder.key}'
                if self.store.was_sent(key):
                    continue
                try:
                    await self.send_notice(reminder.message())
                except (discord.HTTPException, ValueError) as exc:
                    log.warning('Gagal mengirim %s: %s; dicoba lagi selama tenggang 60 detik.', key, exc)
                else:
                    self.store.mark_sent(key, now)
                    log.info('Terkirim: %s', key)

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
        self.store.close()
        await super().close()


if __name__ == '__main__':
    load_dotenv(ROOT / '.env')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = required('DISCORD_TOKEN')
    TrexBot().run(token)
