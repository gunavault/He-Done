"""Weekly salary commands and automatic payday service."""
import logging
import os
from datetime import datetime, timedelta

import discord
from discord import app_commands

from schedule import WIB
from salary_store import last_salary_day, parse_salary_hour

log = logging.getLogger('trex.salary')


class SalaryService:
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = bot.guild_id
        self.store = bot.raids.store
        self.lock = bot.raids.lock
        self.hour = parse_salary_hour(os.getenv('GAJIAN_JAM', '09:00').strip())
        self.register_commands()

    def require_admin(self, interaction):
        self.bot.raids.require_admin(interaction)

    def require_guild(self, interaction):
        self.bot.raids.require_guild(interaction)

    async def tick(self, now=None):
        now = (now or datetime.now(WIB)).astimezone(WIB)
        payday = last_salary_day(now)
        scheduled = datetime.combine(payday, self.hour, tzinfo=WIB)
        if now < scheduled:
            return []
        async with self.lock:
            payments = self.store.salary_payweek(self.guild_id, payday, now=now)
        if payments:
            log.info('Gaji Sabtu %s: %s anggota menerima total %s poin',
                     payday, len(payments), sum(p for _, p in payments))
            # Points are committed before any optional Discord message.
            # Avoid mass ping and avoid retrying announcements indefinitely.
            channel_id = int(os.getenv('GAJIAN_CHANNEL_ID', '').strip() or self.bot.channel_id)
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
                    raise ValueError('GAJIAN_CHANNEL_ID harus channel teks dalam server bot.')
                await channel.send(
                    f'💰 **Gaji mingguan** · periode Sabtu {payday:%d-%m-%Y} WIB\n'
                    f'{len(payments)} anggota menerima total **{sum(p for _, p in payments)} poin**. '
                    'Gunakan /gajian untuk melihat daftar penerima.',
                    allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, ValueError) as exc:
                log.warning('Gaji sudah masuk tetapi pengumuman gagal: %s', exc)
        return payments

    def register_commands(self):
        async def check_server(interaction):
            self.require_guild(interaction)
            return True

        @self.bot.tree.command(name='gajianmingguan', description='Administrator mengatur gaji poin otomatis setiap Sabtu')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.describe(user='Anggota yang menerima gaji', point='Poin per minggu (1–1000000)',
                               details='Alasan atau jabatan penerima gaji, maksimal 500 karakter')
        async def gajianmingguan(interaction: discord.Interaction, user: discord.Member,
                                 point: app_commands.Range[int, 1, 1000000], details: str):
            self.require_admin(interaction)
            if not isinstance(user, discord.Member) or user.guild.id != self.guild_id or user.bot:
                raise ValueError('Gaji hanya untuk anggota manusia pada server ini.')
            async with self.lock:
                row = self.store.salary_set(self.guild_id, user.id, point, details, interaction.user.id,
                                            hour=self.hour)
            safe = discord.utils.escape_markdown(discord.utils.escape_mentions(row['detail']))
            await interaction.response.send_message(
                f'✅ Gaji <@{user.id}>: **{row["points"]} poin setiap Sabtu**.\n'
                f'Detail: {safe}\nMulai periode: **{row["effective_payday"]}** WIB · jam {self.hour:%H:%M}.',
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='gajian', description='Lihat seluruh penerima gaji mingguan aktif')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def gajian(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            rows = self.store.salary_list(self.guild_id, halaman - 1)
            total = len(self.store.salary_list(self.guild_id))
            lines = [f'💰 **Daftar gaji mingguan** · halaman {halaman} · Sabtu {self.hour:%H:%M} WIB',
                     f'**{total} penerima aktif** · total {sum(r["points"] for r in self.store.salary_list(self.guild_id))} poin per minggu']
            for row in rows:
                detail = discord.utils.escape_markdown(discord.utils.escape_mentions(row['detail']))
                lines.append(f'<@{row["user_id"]}> — **{row["points"]} poin** · {detail} · mulai {row["effective_payday"]}')
            if not rows:
                lines.append('Tidak ada penerima pada halaman ini.')
            await interaction.response.send_message('\n'.join(lines)[:1950],
                allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='gajianstop', description='Administrator menghentikan gaji mingguan anggota')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        async def gajianstop(interaction: discord.Interaction, user: discord.Member):
            self.require_admin(interaction)
            if not isinstance(user, discord.Member) or user.guild.id != self.guild_id:
                raise ValueError('Pilih anggota dari server ini.')
            async with self.lock:
                stopped = self.store.salary_stop(self.guild_id, user.id, interaction.user.id)
            await interaction.response.send_message(
                (f'🛑 Gaji mingguan <@{user.id}> dihentikan. Poin yang telah dibayar tetap tersimpan.'
                 if stopped else f'<@{user.id}> tidak memiliki gaji mingguan aktif.'),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='gajianriwayat', description='Lihat riwayat gaji yang sudah dibayarkan')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def gajianriwayat(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            rows = self.store.salary_history(self.guild_id, halaman - 1)
            lines = [f'📜 **Riwayat gajian** · halaman {halaman}']
            for row in rows:
                state = ' · direset' if row['voided'] else ''
                lines.append(f'{row["payday"]} · <@{row["user_id"]}> · {row["points"]} poin{state}')
            if not rows:
                lines.append('Belum ada riwayat pada halaman ini.')
            await interaction.response.send_message('\n'.join(lines),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
