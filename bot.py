import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from schedule import WIB, Store, calculate, describe, times

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
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
        self.minimum = int(os.getenv('SPAWN_MIN_MINUTES', '400'))
        self.maximum = int(os.getenv('SPAWN_MAX_MINUTES', '420'))
        if not 0 <= self.minimum < self.maximum <= 10080:
            raise ValueError('Rentang spawn tidak valid: 0 <= minimum < maximum <= 10080 menit.')
        path = Path(os.getenv('DB_PATH', 'data/trex.sqlite3'))
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(path)
        self.lock = asyncio.Lock()
        self.tree = app_commands.CommandTree(self)
        self.target_guild = discord.Object(id=self.guild_id)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=self.target_guild)
        await self.tree.sync(guild=self.target_guild)
        self.notify.start()

    async def on_ready(self):
        log.info('Bot terhubung: %s; guild=%s', self.user, self.guild_id)

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

    @tasks.loop(seconds=15)
    async def notify(self):
        # Keep replacements/cancellations from racing with a send already in progress.
        async with self.lock:
            for row in self.store.pending():
                base, start, end = times(row)
                now = datetime.now(WIB)
                if now >= end:
                    self.store.mark(row['idx'], 'expired')
                    log.info('Jadwal index %s kedaluwarsa tanpa dikirim.', row['idx'])
                    continue
                if now < start:
                    continue
                try:
                    await self.send_notice(describe(row['idx'], base, start, end))
                except (discord.HTTPException, ValueError) as exc:
                    log.warning('Gagal mengirim index %s: %s; dicoba lagi selama jendela aktif.', row['idx'], exc)
                else:
                    self.store.mark(row['idx'], 'sent')

    @notify.before_loop
    async def before_notify(self):
        await self.wait_until_ready()

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


bot = TrexBot()
INDEX_CHOICES = [app_commands.Choice(name=x, value=x) for x in ('3.1', '3.2')]


async def check_server(interaction):
    if interaction.guild_id != bot.guild_id:
        raise app_commands.CheckFailure('Perintah hanya untuk server yang diatur di .env.')
    return True


@bot.tree.command(name='trex', description='Catat waktu index dan jadwalkan notifikasi T-Rex')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.check(check_server)
@app_commands.choices(index=INDEX_CHOICES)
@app_commands.describe(index='Pilih index', waktu='Waktu index dicatat, HH:MM WIB',
                       tanggal='Opsional: YYYY-MM-DD; default hari ini WIB')
async def trex(interaction: discord.Interaction, index: str, waktu: str, tanggal: str | None = None):
    await interaction.response.defer(ephemeral=True)
    base, start, end = calculate(waktu, tanggal, minimum=bot.minimum, maximum=bot.maximum)
    await bot.destination()
    async with bot.lock:
        bot.store.put(index, base, start, end)
    await interaction.followup.send(
        describe(index, base, start, end) + '\n✅ Jadwal tersimpan. Role akan ditag saat jendela dimulai. '
        'Jadwal lama untuk index ini diganti.', ephemeral=True)


@bot.tree.command(name='jadwal', description='Lihat jadwal T-Rex yang masih menunggu notifikasi')
@app_commands.guild_only()
@app_commands.check(check_server)
async def jadwal(interaction: discord.Interaction):
    now = datetime.now(WIB)
    rows = [row for row in bot.store.pending() if times(row)[2] > now]
    body = '\n\n'.join(describe(row['idx'], *times(row)) for row in rows)
    await interaction.response.send_message(body or 'Belum ada jadwal aktif.', ephemeral=True)


@bot.tree.command(name='hapus', description='Batalkan jadwal untuk satu index')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.check(check_server)
@app_commands.choices(index=INDEX_CHOICES)
async def hapus(interaction: discord.Interaction, index: str):
    await interaction.response.defer(ephemeral=True)
    async with bot.lock:
        removed = bot.store.delete(index)
    await interaction.followup.send('Jadwal dihapus.' if removed else 'Jadwal tidak ditemukan.', ephemeral=True)


@bot.tree.command(name='tes', description='Kirim pesan uji ke channel tujuan, termasuk tag role')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.check(check_server)
async def tes(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await bot.send_notice('🦖 **Tes notifikasi T-Rex** — bot sudah terhubung. Ini hanya pesan uji.')
    await interaction.followup.send('Pesan uji dan tag role dikirim.', ephemeral=True)


@bot.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
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


if __name__ == '__main__':
    bot.run(required('DISCORD_TOKEN'))
