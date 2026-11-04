"""Manual raid registration, leader attendance, and weighted event points."""
import asyncio
import logging
import os
from datetime import datetime

import discord
from discord import app_commands

from raid_store import RaidStore, KINDS, STATUSES, EVENT_POINTS, raid_time
from schedule import WIB, SUPPORTED_INDICES

log = logging.getLogger('trex.raids')
EVENT_STATUSES = {'publishing': 'Menerbitkan', 'open': 'Terbuka',
                  'completed': 'Selesai', 'cancelled': 'Dibatalkan', 'failed': 'Gagal terbit'}


async def index_autocomplete(interaction, current):
    prefix = current.strip()
    return [app_commands.Choice(name=index, value=index)
            for index in SUPPORTED_INDICES if index.startswith(prefix)][:25]


def event_embed(event, participants):
    title = KINDS[event['kind']]
    if event['idx']:
        title += f" — Index {event['idx']}"
    start = datetime.fromisoformat(event['starts_at']).astimezone(WIB)
    embed = discord.Embed(title=f"⚔️ Raid #{event['id']} · {title}", color=0x2ECC71 if event['status'] == 'open' else 0x7F8C8D)
    embed.description = (f"**Waktu:** {start:%d-%m-%Y %H:%M} WIB\n"
                         f"**Tempat:** {discord.utils.escape_markdown(discord.utils.escape_mentions(event['place']))}\n"
                         f"**Leader:** <@{event['leader_id']}>\n"
                         f"**Status:** {EVENT_STATUSES[event['status']]}\n"
                         f"**Poin:** langsung +{EVENT_POINTS[event['kind']]} saat leader menandai Hadir.")
    if event['status'] == 'cancelled':
        embed.description = embed.description.replace(f"langsung +{EVENT_POINTS[event['kind']]} saat leader menandai Hadir.", 'dibatalkan untuk seluruh peserta event ini.')
    for status, label in STATUSES.items():
        users = [p for p in participants if p['status'] == status]
        value = ', '.join(f"<@{p['user_id']}>" for p in users[:12]) or '—'
        if len(users) > 12:
            value += f' · +{len(users) - 12} lainnya (lihat panel leader)'
        embed.add_field(name=f'{label} ({len(users)})', value=value, inline=False)
    embed.set_footer(text='Daftar → leader Hadir → poin sesuai jenis raid. Tidak Hadir membatalkan poin selama event terbuka.')
    return embed


class RaidView(discord.ui.View):
    def __init__(self, service, event_id, closed=False):
        super().__init__(timeout=None)
        self.service, self.event_id = service, event_id
        for action, label, style in (
            ('join', 'Daftar', discord.ButtonStyle.success),
            ('absent', 'Tidak Hadir', discord.ButtonStyle.danger),
            ('manage', 'Kelola — Leader', discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, style=style,
                                       custom_id=f'raid:{event_id}:{action}', disabled=closed)

            async def callback(interaction, action=action):
                await self.service.handle_public(interaction, self.event_id, action)
            button.callback = callback
            self.add_item(button)

    async def on_error(self, interaction, error, item):
        await self.service.error(interaction, error)


class LeaderView(discord.ui.View):
    def __init__(self, service, event_id, owner_id, page=0):
        super().__init__(timeout=300)
        self.service, self.event_id, self.owner_id = service, event_id, owner_id
        people = service.store.participants(event_id)
        self.page = min(max(0, page), max(0, (len(people) - 1) // 25))
        self.selected = None
        subset = people[self.page * 25:(self.page + 1) * 25]
        if subset:
            select = discord.ui.Select(placeholder='Pilih peserta untuk dikelola', row=0, options=[
                discord.SelectOption(label=f"{p['name']} · {STATUSES[p['status']]}"[:100],
                                     value=p['user_id'], description=f"Discord ID: {p['user_id']}")
                for p in subset])

            async def choose(interaction):
                self.selected = select.values[0]
                await interaction.response.defer()
            select.callback = choose
            self.add_item(select)
        for action, label, style in (
            ('accepted', 'Hadir', discord.ButtonStyle.success),
            ('absent', 'Tidak Hadir', discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style, row=1, disabled=not subset)

            async def moderate(interaction, action=action):
                if self.selected is None:
                    raise ValueError('Pilih peserta di menu terlebih dahulu.')
                await self.service.moderate(interaction, self.event_id, self.selected, action, self.page)
            button.callback = moderate
            self.add_item(button)
        for delta, label in ((-1, 'Sebelumnya'), (1, 'Berikutnya')):
            button = discord.ui.Button(label=label, row=2, disabled=(self.page == 0 if delta < 0 else (self.page + 1) * 25 >= len(people)))

            async def navigate(interaction, delta=delta):
                self.service.require_manager(interaction, self.service.store.event(self.service.guild_id, self.event_id))
                await interaction.response.edit_message(content=f'Panel leader raid #{self.event_id} · halaman {self.page + delta + 1}',
                    view=LeaderView(self.service, self.event_id, self.owner_id, self.page + delta))
            button.callback = navigate
            self.add_item(button)
        for cancel, label, style in ((False, 'Selesaikan Event', discord.ButtonStyle.success),
                                     (True, 'Batalkan Event', discord.ButtonStyle.danger)):
            button = discord.ui.Button(label=label, row=3, style=style)

            async def close_event(interaction, cancel=cancel):
                event = self.service.store.event(self.service.guild_id, self.event_id)
                self.service.require_manager(interaction, event)
                if event['status'] != 'open':
                    raise ValueError('Event sudah ditutup.')
                people = self.service.store.participants(self.event_id)
                accepted = sum(p['status'] == 'accepted' for p in people)
                text = ('Batalkan event? Semua poin event ini akan ditarik.' if cancel else
                        f'Tutup event? Poin {accepted} peserta Hadir sudah tercatat, '
                        'tidak akan ditambahkan lagi. Pastikan daftar benar; event tertutup tidak bisa diedit.')
                await interaction.response.send_message(text, ephemeral=True,
                    view=ConfirmView(self.service, self.event_id, self.owner_id, cancel))
            button.callback = close_event
            self.add_item(button)

    async def interaction_check(self, interaction):
        try:
            if interaction.user.id != self.owner_id:
                raise ValueError('Panel ini milik leader yang membukanya.')
            self.service.require_manager(interaction, self.service.store.event(self.service.guild_id, self.event_id))
            return True
        except (ValueError, app_commands.CheckFailure) as exc:
            await self.service.error(interaction, exc)
            return False

    async def on_error(self, interaction, error, item):
        await self.service.error(interaction, error)


class ConfirmView(discord.ui.View):
    def __init__(self, service, event_id, owner_id, cancel):
        super().__init__(timeout=120)
        self.service, self.event_id, self.owner_id, self.cancel = service, event_id, owner_id, cancel

    @discord.ui.button(label='Ya, konfirmasi', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            raise ValueError('Konfirmasi ini milik leader yang membukanya.')
        await self.service.finish(interaction, self.event_id, self.cancel)
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

    async def on_error(self, interaction, error, item):
        await self.service.error(interaction, error)


class RaidService:
    def __init__(self, bot, db_path):
        self.bot, self.guild_id = bot, bot.guild_id
        self.channel_id = int(os.getenv('RAID_CHANNEL_ID', '').strip() or bot.channel_id)
        self.command_channel_id = int(os.getenv('RAID_COMMAND_CHANNEL_ID', '').strip() or self.channel_id)
        self.leader_role_id = int(os.getenv('RAID_LEADER_ROLE_ID', '').strip() or bot.role_id)
        if min(self.channel_id, self.command_channel_id, self.leader_role_id) <= 0:
            raise ValueError('ID konfigurasi raid harus ID Discord positif atau kosong.')
        self.store = RaidStore(db_path)
        self.lock = asyncio.Lock()
        self._cards_refreshed = False
        self.register_commands()

    def require_guild(self, interaction):
        if interaction.guild_id != self.guild_id:
            raise app_commands.CheckFailure('Raid hanya untuk server yang diatur di GUILD_ID.')

    def is_leader_role(self, user):
        return (self.leader_role_id != self.guild_id and isinstance(user, discord.Member)
                and any(role.id == self.leader_role_id for role in user.roles))

    def require_manager(self, interaction, event):
        self.require_guild(interaction)
        if str(interaction.user.id) != event['leader_id'] and not self.is_leader_role(interaction.user):
            raise app_commands.CheckFailure('Hanya leader event atau pemegang RAID_LEADER_ROLE_ID yang dapat mengelola.')

    def require_admin(self, interaction):
        self.require_guild(interaction)
        if (not isinstance(interaction.user, discord.Member)
                or not interaction.user.guild_permissions.administrator):
            raise app_commands.CheckFailure('Perintah ini memerlukan izin Administrator pada server Discord.')

    async def error(self, interaction, error):
        await self.bot.command_error(interaction, error)

    def restore_views(self):
        events = self.store.open_events(self.guild_id)
        for event in events:
            self.bot.add_view(RaidView(self, event['id']), message_id=int(event['message_id']))
        log.info('Raid siap: channel_id=%s command_channel_id=%s leader_role_id=%s; event terbuka=%s',
                 self.channel_id, self.command_channel_id, self.leader_role_id, len(events))

    async def channel(self, channel_id):
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('RAID_CHANNEL_ID harus channel teks pada GUILD_ID yang sama.')
        return channel

    async def refresh(self, event_id):
        event = self.store.event(self.guild_id, event_id)
        channel = await self.channel(int(event['channel_id']))
        message = channel.get_partial_message(int(event['message_id']))
        await message.edit(embed=event_embed(event, self.store.participants(event_id)),
                           view=RaidView(self, event_id, closed=event['status'] != 'open'),
                           allowed_mentions=discord.AllowedMentions.none())

    async def refresh_notice(self, event_id):
        try:
            await self.refresh(event_id)
            return ''
        except (discord.HTTPException, ValueError) as exc:
            log.warning('Raid #%s tersimpan tetapi kartu gagal diperbarui: %s', event_id, exc)
            return f' Data tersimpan, tetapi kartu gagal diperbarui. Gunakan /raid event:{event_id} untuk melihat data terbaru.'

    async def refresh_open_cards(self):
        # Update existing cards to the current display after restoring their buttons.
        if self._cards_refreshed:
            return
        self._cards_refreshed = True
        async with self.lock:
            for event in self.store.open_events(self.guild_id):
                await self.refresh_notice(event['id'])

    async def create_event(self, interaction, kind, jam, tempat, tanggal=None, index=None):
        self.require_guild(interaction)
        if not self.is_leader_role(interaction.user):
            raise app_commands.CheckFailure('Membuat raid memerlukan role RAID_LEADER_ROLE_ID (default ROLE_ID).')
        if interaction.channel_id != self.command_channel_id:
            raise ValueError(f'Buat event di <#{self.command_channel_id}>.')
        start = raid_time(jam, tanggal)
        await interaction.response.defer(ephemeral=True)
        channel = await self.channel(self.channel_id)
        async with self.lock:
            event_id = self.store.create(self.guild_id, self.channel_id, interaction.user.id, kind, start, tempat, index)
            event = self.store.event(self.guild_id, event_id)
            view = RaidView(self, event_id)
            # Persist the published state only once Discord returns the message ID.
            public_event = dict(event)
            public_event['status'] = 'open'
            embed = event_embed(public_event, [])
            try:
                message = await channel.send(content=f'<@&{self.bot.role_id}>', embed=embed, view=view,
                    allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                        roles=[discord.Object(id=self.bot.role_id)], replied_user=False))
            except Exception:
                view.stop()
                self.store.publication_failed(self.guild_id, event_id)
                raise
            self.store.publish(self.guild_id, event_id, message.id)
        await interaction.followup.send(f'Raid #{event_id} dibuat: {message.jump_url}', ephemeral=True)

    async def handle_public(self, interaction, event_id, action):
        self.require_guild(interaction)
        event = self.store.event(self.guild_id, event_id)
        if event['status'] != 'open':
            raise ValueError('Event sudah ditutup.')
        if action == 'manage':
            self.require_manager(interaction, event)
            await interaction.response.send_message(f'Panel leader raid #{event_id} · pilih peserta, lalu tindakan.',
                view=LeaderView(self, event_id, interaction.user.id), ephemeral=True)
            return
        if action not in ('join', 'absent'):
            raise ValueError('Tindakan tidak dikenal.')
        if interaction.user.bot:
            raise ValueError('Pendaftaran hanya untuk anggota manusia.')
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            status = self.store.respond(self.guild_id, event_id, interaction.user.id,
                                       interaction.user.display_name, action == 'join')
            warning = await self.refresh_notice(event_id)
        credit = self.store.event_credit(self.guild_id, event_id, interaction.user.id)
        points = f'{credit} poin tercatat untuk event ini.'
        message = f'Status kamu: **{STATUSES[status]}**.'
        if status != 'pending':
            message += f' {points}'
        await interaction.followup.send(message + warning,
                                        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def moderate(self, interaction, event_id, user_id, action, page=0):
        self.require_manager(interaction, self.store.event(self.guild_id, event_id))
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            self.store.moderate(self.guild_id, event_id, user_id, interaction.user.id, action)
            warning = await self.refresh_notice(event_id)
        credit = self.store.event_credit(self.guild_id, event_id, user_id)
        points = f'{credit} poin tercatat untuk event ini; tidak digandakan.' if action == 'accepted' else 'Poin event ini dibatalkan jika sebelumnya Hadir.'
        await interaction.edit_original_response(content=f'Peserta <@{user_id}>: {STATUSES[action]}. {points}' + warning,
            view=LeaderView(self, event_id, interaction.user.id, page), allowed_mentions=discord.AllowedMentions.none())

    async def finish(self, interaction, event_id, cancel):
        self.require_manager(interaction, self.store.event(self.guild_id, event_id))
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            count = self.store.finish(self.guild_id, event_id, interaction.user.id, cancel)
            warning = await self.refresh_notice(event_id)
        weight = EVENT_POINTS[self.store.event(self.guild_id, event_id)['kind']]
        text = 'Event dibatalkan. Semua poin event ini ditarik.' if cancel else f'Event ditutup. {count} peserta masing-masing memiliki {weight} poin; tidak ada poin tambahan.'
        await interaction.followup.send(text + warning, ephemeral=True)

    def register_commands(self):
        async def check_server(interaction):
            self.require_guild(interaction)
            return True

        @self.bot.tree.command(name='worldbossraid', description='Leader membuat pendaftaran raid T-Rex manual; tidak mengubah timer')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.autocomplete(index=index_autocomplete)
        @app_commands.describe(jam='Jam mulai HH:MM WIB', tempat='Lokasi raid', index='Index T-Rex',
                               tanggal='Opsional YYYY-MM-DD; default hari ini WIB')
        async def worldbossraid(interaction: discord.Interaction, jam: str, tempat: str, index: str, tanggal: str | None = None):
            await self.create_event(interaction, 'trex', jam, tempat, tanggal, index)

        @self.bot.tree.command(name='rift', description='Leader membuat pendaftaran raid Rift manual')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.describe(jam='Jam mulai HH:MM WIB', tempat='Lokasi raid', tanggal='Opsional YYYY-MM-DD; default hari ini WIB')
        async def rift(interaction: discord.Interaction, jam: str, tempat: str, tanggal: str | None = None):
            await self.create_event(interaction, 'rift', jam, tempat, tanggal)

        @self.bot.tree.command(name='savage', description='Leader membuat pendaftaran raid Savage manual')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.describe(jam='Jam mulai HH:MM WIB', tempat='Lokasi raid', tanggal='Opsional YYYY-MM-DD; default hari ini WIB')
        async def savage(interaction: discord.Interaction, jam: str, tempat: str, tanggal: str | None = None):
            await self.create_event(interaction, 'savage', jam, tempat, tanggal)

        @self.bot.tree.command(name='raid', description='Lihat event raid terbaru atau kartu event berdasarkan ID')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def raid(interaction: discord.Interaction, event: int | None = None):
            if event is not None:
                row = self.store.event(self.guild_id, event)
                if row['status'] not in ('open', 'completed', 'cancelled'):
                    raise ValueError('Event belum berhasil diterbitkan.')
                view = RaidView(self, event, closed=row['status'] != 'open')
                # Ephemeral copies are short lived; the channel card remains persistent.
                view.timeout = 300
                await interaction.response.send_message(embed=event_embed(row, self.store.participants(event)),
                    view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                rows = self.store.recent_events(self.guild_id)
                lines = ['**Event raid terbaru**']
                for row in rows:
                    start = datetime.fromisoformat(row['starts_at']).astimezone(WIB)
                    url = f"https://discord.com/channels/{self.guild_id}/{row['channel_id']}/{row['message_id']}"
                    lines.append(f"[#{row['id']} {KINDS[row['kind']]}]({url}) · {start:%d-%m %H:%M} WIB · {EVENT_STATUSES[row['status']]}")
                await interaction.response.send_message('\n'.join(lines) if rows else 'Belum ada event raid.', ephemeral=True)

        @self.bot.tree.command(name='addpoint', description='Administrator server menambah poin kontribusi untuk satu anggota')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.describe(user='Anggota yang mendapat poin kontribusi', point='Jumlah poin kontribusi (positif)',
                               detail='Detail kontribusi, maksimal 500 karakter')
        async def addpoint(interaction: discord.Interaction, user: discord.Member,
                           point: app_commands.Range[int, 1, 1000000], detail: str):
            self.require_admin(interaction)
            if not isinstance(user, discord.Member) or user.guild.id != self.guild_id or user.bot:
                raise ValueError('Pilih satu anggota manusia pada server ini.')
            if not 1 <= len(detail.strip()) <= 500:
                raise ValueError('Detail kontribusi harus 1–500 karakter.')
            await interaction.response.defer(ephemeral=False)
            async with self.lock:
                receipt = self.store.add_contribution(self.guild_id, user.id, point, detail,
                                                      interaction.user.id, interaction.id)
            log.info('Contribution #%s: guild_id=%s user_id=%s points=%s actor_id=%s',
                     receipt, self.guild_id, user.id, point, interaction.user.id)
            safe_detail = discord.utils.escape_markdown(discord.utils.escape_mentions(detail.strip()))
            await interaction.followup.send(
                f'<@&{self.bot.role_id}>\n'
                f'✅ Contribution #{receipt}: <@{user.id}> mendapat **{point} poin** · 1 contribution.\n'
                f'Detail: {safe_detail}', ephemeral=False,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                    roles=[discord.Object(id=self.bot.role_id)], replied_user=False))

        @self.bot.tree.command(name='remove', description='Administrator server mengurangi poin satu anggota dengan alasan')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.describe(user='Anggota yang poinnya dikurangi', point='Jumlah poin yang dikurangi (positif)',
                               detail='Alasan pengurangan, maksimal 500 karakter')
        async def remove(interaction: discord.Interaction, user: discord.Member,
                         point: app_commands.Range[int, 1, 1000000], detail: str):
            self.require_admin(interaction)
            if not isinstance(user, discord.Member) or user.guild.id != self.guild_id or user.bot:
                raise ValueError('Pilih satu anggota manusia pada server ini.')
            if not 1 <= len(detail.strip()) <= 500:
                raise ValueError('Alasan pengurangan harus 1–500 karakter.')
            await interaction.response.defer(ephemeral=False)
            async with self.lock:
                receipt = self.store.remove_points(self.guild_id, user.id, point, detail,
                                                   interaction.user.id, interaction.id)
                total = self.store.point_summary(self.guild_id, user.id)['points']
            log.info('Deduction #%s: guild_id=%s user_id=%s points=%s actor_id=%s',
                     receipt, self.guild_id, user.id, point, interaction.user.id)
            safe_detail = discord.utils.escape_markdown(discord.utils.escape_mentions(detail.strip()))
            await interaction.followup.send(
                f'<@&{self.bot.role_id}>\n'
                f'➖ Pengurangan #{receipt}: <@{user.id}> dikurangi **{point} poin**.\n'
                f'Alasan: {safe_detail}\nTotal sekarang: **{total} poin**.', ephemeral=False,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                    roles=[discord.Object(id=self.bot.role_id)], replied_user=False))

        @self.bot.tree.command(name='point', description='Lihat poin sendiri atau poin satu anggota server')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.describe(user='Opsional: anggota yang diperiksa; kosong untuk poin sendiri')
        async def point(interaction: discord.Interaction, user: discord.Member | None = None):
            self.require_guild(interaction)
            member = user if user is not None else interaction.user
            if not isinstance(member, discord.Member) or member.guild.id != self.guild_id:
                raise ValueError('Pilih anggota pada server ini.')
            summary = self.store.point_summary(self.guild_id, member.id)
            await interaction.response.send_message(
                f'🏅 **Poin <@{member.id}>**\n'
                f"Total: **{summary['points']} poin**\n"
                f"Event: **{summary['events']} event** · {summary['event_points']} poin\n"
                f"Contribution: **{summary['contributions']} contribution** · {summary['contribution_points']} poin\n"
                f"Pengurangan: **{summary['deduction_points']} poin**\n"
                f"Redeem terpakai: **{summary['redeem_points']} poin**\n"
                f"Gaji diterima: **{self.store.salary_summary(self.guild_id, member.id)['points']} poin**",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='leaderboard', description='Peringkat total poin event dan kontribusi anggota server')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def leaderboard(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            if not 1 <= halaman <= 10000:
                raise ValueError('Halaman harus 1–10000.')
            rows = self.store.leaderboard(self.guild_id, halaman - 1)
            lines = [f'🏆 **Leaderboard — halaman {halaman}**', 'Saldo poin setelah pengurangan dan redeem. World Boss/T-Rex: 40 · War di Savage: 50 · Rift: 35 poin.']
            for i, row in enumerate(rows, (halaman - 1) * 10 + 1):
                lines.append(f"{i}. **<@{row['user_id']}>** — **{row['points']} poin** · {row['events']} event, {row['contributions']} contribution")
            if not rows:
                lines.append('Belum ada poin pada halaman ini.')
            await interaction.response.send_message('\n'.join(lines), allowed_mentions=discord.AllowedMentions.none())
