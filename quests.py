"""Persistent guild quest dashboard and recoverable private member/leader panels."""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta

import discord
from discord import app_commands

from schedule import WIB

log = logging.getLogger('trex.quests')
LABELS = {'available': 'Tersedia', 'in_progress': 'Dikerjakan', 'submitted': 'Menunggu persetujuan',
          'completed': 'Selesai', 'withdrawn': 'Ditarik'}


def safe(text):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(text)))


def timestamp(value):
    return int(datetime.fromisoformat(value).timestamp())


class QuestView(discord.ui.View):
    def __init__(self, service, owner=None, leader=False, timeout=300):
        super().__init__(timeout=timeout)
        self.service, self.owner, self.leader = service, owner, leader

    def check(self, interaction):
        self.service.require_member(interaction)
        if self.owner is not None and interaction.user.id != self.owner:
            raise app_commands.CheckFailure('Panel ini milik anggota yang membukanya.')
        if self.leader:
            self.service.require_leader(interaction)

    async def interaction_check(self, interaction):
        try:
            self.check(interaction)
            return True
        except (ValueError, app_commands.CheckFailure) as exc:
            await self.service.bot.command_error(interaction, exc)
            return False

    async def on_error(self, interaction, error, item):
        await self.service.bot.command_error(interaction, error)

    def button(self, label, action, row=1, style=discord.ButtonStyle.secondary, disabled=False, custom_id=None):
        kwargs = dict(label=label, row=row, style=style, disabled=disabled)
        if custom_id:
            kwargs['custom_id'] = custom_id
        button = discord.ui.Button(**kwargs)

        async def callback(interaction):
            self.check(interaction)
            await action(interaction)
        button.callback = callback
        self.add_item(button)
        return button


class QuestMainView(QuestView):
    def __init__(self, service):
        super().__init__(service, timeout=None)
        for action, label, style in (
            ('accept', 'Accept Quest', discord.ButtonStyle.success),
            ('abort', 'Abort Quest', discord.ButtonStyle.danger),
            ('leader', 'Union Leader Panel', discord.ButtonStyle.primary),
        ):
            async def run(interaction, action=action):
                if interaction.channel_id != service.channel_id:
                    raise ValueError('Gunakan card guild quest pada channel yang dikonfigurasi.')
                if action == 'leader':
                    service.require_leader(interaction)
                    await service.open_panel(interaction, leader=True)
                elif action == 'abort':
                    await service.open_abort(interaction)
                else:
                    await service.open_panel(interaction)
            self.button(label, run, row=0, style=style, custom_id=f'guildquest:{action}')


class QuestChoiceView(QuestView):
    def __init__(self, service, owner, leader=False, page=0):
        super().__init__(service, owner, leader)
        self.selected = None
        self.snapshot = None
        self.page = page
        rows = service.store.quest_list(service.guild_id, None if leader else 'available', page=page)
        if rows:
            select = discord.ui.Select(placeholder='Pilih quest', row=0, options=[
                discord.SelectOption(label=row['title'], value=str(row['id']),
                    description=f"#{row['id']} · {row['points']} poin · {row['hours']} jam · {LABELS[row['status']]}"[:100])
                for row in rows])

            async def choose(interaction):
                self.check(interaction)
                self.selected = int(select.values[0])
                self.snapshot = dict(service.store.quest_get(service.guild_id, self.selected))
                for item in self.children:
                    if not isinstance(item, discord.ui.Button):
                        continue
                    if item.label in ('Edit Quest', 'Tarik Quest', 'Accept Quest Terpilih'):
                        item.disabled = self.snapshot['status'] != 'available'
                    elif item.label in ('Setujui Selesai', 'Minta Revisi'):
                        item.disabled = self.snapshot['status'] != 'submitted'
                await interaction.response.edit_message(embed=service.quest_embed(self.snapshot, leader=leader), view=self)
            select.callback = choose
            self.add_item(select)

        def selected():
            if self.snapshot is None:
                raise ValueError('Pilih quest dari menu terlebih dahulu.')
            return self.snapshot

        if leader:
            async def create(interaction):
                await interaction.response.send_modal(QuestForm(service, owner))
            async def edit(interaction):
                row = selected()
                if row['status'] != 'available':
                    raise ValueError('Quest yang sudah diambil tidak bisa diedit.')
                await interaction.response.send_modal(QuestForm(service, owner, row))
            async def withdraw(interaction):
                row = selected()
                await interaction.response.send_message(f"Tarik quest #{row['id']} dari daftar tersedia?", ephemeral=True,
                    view=QuestConfirm(service, owner, 'withdraw', row))
            async def approve(interaction):
                row = selected()
                await service.review(interaction, row, True)
            async def revise(interaction):
                await interaction.response.send_modal(QuestNoteForm(service, owner, selected(), review=True))
            self.button('Post Quest', create, style=discord.ButtonStyle.success)
            self.button('Edit Quest', edit, disabled=True)
            self.button('Tarik Quest', withdraw, style=discord.ButtonStyle.danger, disabled=True)
            self.button('Setujui Selesai', approve, row=2, style=discord.ButtonStyle.success, disabled=True)
            self.button('Minta Revisi', revise, row=2, disabled=True)
        else:
            async def accept(interaction):
                row = selected()
                service.require_member(interaction)
                await service.mutate(interaction,
                    lambda: service.store.quest_claim(service.guild_id, row['id'], owner),
                    lambda result: service.member_render(owner))
            self.button('Accept Quest Terpilih', accept, style=discord.ButtonStyle.success, disabled=True)

        for delta, label in ((-1, 'Sebelumnya'), (1, 'Berikutnya')):
            disabled = page == 0 if delta < 0 else not service.store.quest_list(
                service.guild_id, None if leader else 'available', page=page + 1)
            async def navigate(interaction, delta=delta):
                await service.open_panel(interaction, leader=leader, page=page + delta, edit=True)
            self.button(label, navigate, row=3, disabled=disabled)


class QuestMemberView(QuestView):
    def __init__(self, service, owner, row):
        super().__init__(service, owner)
        snapshot = dict(row)
        async def submit(interaction):
            await interaction.response.send_modal(QuestNoteForm(service, owner, snapshot))
        async def abort(interaction):
            await interaction.response.send_message('Batalkan quest dan kembalikan ke daftar tersedia? Tidak ada poin diberikan.',
                ephemeral=True, view=QuestConfirm(service, owner, 'abort', snapshot))
        self.button('Submit Selesai', submit, style=discord.ButtonStyle.success, disabled=row['status'] != 'in_progress')
        self.button('Abort Quest', abort, style=discord.ButtonStyle.danger)


class QuestConfirm(QuestView):
    def __init__(self, service, owner, action, row):
        super().__init__(service, owner, leader=action == 'withdraw', timeout=120)
        row = dict(row)
        async def confirm(interaction):
            if action == 'withdraw':
                service.require_leader(interaction)
                operation = lambda: service.store.quest_withdraw(service.guild_id, row['id'], owner, row['revision'])
                renderer = lambda result: service.leader_render(owner, 'Quest ditarik.')
            else:
                operation = lambda: service.store.quest_abort(service.guild_id, row['id'], owner,
                    row.get('attempt_id', row['active_attempt_id']))
                renderer = lambda result: service.member_render(owner, 'Quest dibatalkan dan tersedia kembali. Tidak ada poin diberikan.')
            await service.mutate(interaction, operation, renderer)
            self.stop()
        async def cancel(interaction):
            await interaction.response.edit_message(content='Konfirmasi ditutup. Tidak ada perubahan.', embed=None, view=None)
            self.stop()
        self.button('Ya, konfirmasi', confirm, row=0, style=discord.ButtonStyle.danger)
        self.button('Batal', cancel, row=0)


class QuestForm(discord.ui.Modal):
    def __init__(self, service, owner, row=None):
        super().__init__(title='Edit Guild Quest' if row else 'Post Guild Quest', timeout=300)
        self.service, self.owner, self.row = service, owner, row
        self.request_id = 'quest:' + uuid.uuid4().hex
        self.title_field = discord.ui.TextInput(label='Judul', max_length=100, default=row['title'] if row else None)
        self.detail = discord.ui.TextInput(label='Detail', style=discord.TextStyle.paragraph, max_length=1500,
                                           default=row['detail'] if row else None)
        self.points = discord.ui.TextInput(label='Poin (1–1000000)', max_length=7, default=str(row['points']) if row else None)
        self.hours = discord.ui.TextInput(label='Durasi pengerjaan dalam jam (1–720)', max_length=3,
                                          default=str(row['hours']) if row else None)
        for field in (self.title_field, self.detail, self.points, self.hours):
            self.add_item(field)

    async def on_submit(self, interaction):
        self.service.require_leader(interaction)
        if interaction.user.id != self.owner:
            raise app_commands.CheckFailure('Form ini milik leader yang membukanya.')
        try:
            points, hours = int(self.points.value), int(self.hours.value)
        except ValueError:
            raise ValueError('Poin dan durasi harus angka bulat.') from None
        if self.row:
            operation = lambda: self.service.store.quest_edit(self.service.guild_id, self.row['id'], self.owner,
                self.row['revision'], self.title_field.value, self.detail.value, points, hours)
        else:
            operation = lambda: self.service.store.quest_create(self.service.guild_id, self.owner,
                self.title_field.value, self.detail.value, points, hours, self.request_id)
        await self.service.mutate(interaction, operation,
            lambda result: self.service.leader_render(self.owner, 'Quest tersimpan. Card utama diperbarui.'), modal=True)

    async def on_error(self, interaction, error):
        await self.service.bot.command_error(interaction, error)


class QuestNoteForm(discord.ui.Modal):
    def __init__(self, service, owner, row, review=False):
        super().__init__(title='Catatan Revisi' if review else 'Submit Quest Selesai', timeout=300)
        self.service, self.owner, self.row, self.review = service, owner, dict(row), review
        self.note = discord.ui.TextInput(label='Alasan revisi' if review else 'Catatan atau link bukti (opsional)',
            style=discord.TextStyle.paragraph, max_length=1000, required=review)
        self.add_item(self.note)

    async def on_submit(self, interaction):
        self.service.require_member(interaction)
        if interaction.user.id != self.owner:
            raise app_commands.CheckFailure('Form ini milik anggota yang membukanya.')
        if self.review:
            await self.service.review(interaction, self.row, False, self.note.value, modal=True)
        else:
            await self.service.mutate(interaction,
                lambda: self.service.store.quest_submit(self.service.guild_id, self.row['id'], self.owner,
                    self.row.get('attempt_id', self.row['active_attempt_id']), self.note.value),
                lambda result: self.service.member_render(self.owner, 'Submission dikirim. Tunggu persetujuan leader.'), modal=True)

    async def on_error(self, interaction, error):
        await self.service.bot.command_error(interaction, error)


class QuestService:
    def __init__(self, bot):
        self.bot, self.guild_id, self.store = bot, bot.guild_id, bot.raids.store
        self.channel_id = int(os.getenv('GUILD_QUEST_CHANNEL_ID', '').strip() or '0')
        self.leader_role_id = int(os.getenv('UNION_LEADER_ROLE_ID', '').strip() or bot.raids.leader_role_id)
        if self.channel_id < 0 or self.leader_role_id <= 0:
            raise ValueError('ID channel/role guild quest tidak valid.')
        self.lock = asyncio.Lock()
        self.dirty = True
        self.next_tick = datetime.min.replace(tzinfo=WIB)
        self.register_commands()

    @property
    def enabled(self):
        return bool(self.channel_id)

    def require_member(self, interaction):
        self.bot.raids.require_guild(interaction)
        if not self.enabled:
            raise ValueError('Isi GUILD_QUEST_CHANNEL_ID di env lalu restart untuk mengaktifkan guild quest.')
        if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            raise app_commands.CheckFailure('Guild quest hanya untuk anggota server.')

    def require_leader(self, interaction):
        self.require_member(interaction)
        if self.leader_role_id == self.guild_id or not any(role.id == self.leader_role_id for role in interaction.user.roles):
            raise app_commands.CheckFailure('Panel ini hanya untuk role Union Leader yang dikonfigurasi.')

    def restore_views(self):
        if self.enabled:
            self.bot.add_view(QuestMainView(self))

    def quest_embed(self, row, leader=False):
        lines = [safe(row['detail']), f"\n**Hadiah:** {row['points']} poin · **Durasi:** {row['hours']} jam",
                 f"**Status:** {LABELS[row['status']]}"]
        if row['user_id']:
            lines.append(f"**Pengambil:** <@{row['user_id']}>")
        if row['deadline']:
            if row['status'] == 'in_progress':
                lines.append(f"**Batas waktu:** <t:{timestamp(row['deadline'])}:F> · <t:{timestamp(row['deadline'])}:R>")
            elif row['status'] == 'submitted':
                lines.append('**Timer berhenti:** menunggu pemeriksaan leader.')
        embed = discord.Embed(title=f"Quest #{row['id']} · {row['title']}", description='\n'.join(lines), color=0x3498DB)
        if row['review_note']:
            embed.add_field(name='Catatan leader', value=safe(row['review_note'])[:1000], inline=False)
        if leader and row['proof']:
            embed.add_field(name='Catatan/bukti', value=safe(row['proof'])[:1000], inline=False)
        embed.set_footer(text='Panel tertutup? Klik Accept Quest pada card utama untuk membukanya kembali.')
        return embed

    def board_embed(self):
        counts = self.store.quest_counts(self.guild_id)
        embed = discord.Embed(title='📜 Guild Quest', description='Pilih quest, kerjakan, lalu submit untuk persetujuan Union Leader.', color=0x2ECC71)
        for status, title in (('available', '🆕 Quest Baru'), ('in_progress', '⚒️ Sedang Dikerjakan'),
                              ('submitted', '🔎 Menunggu Persetujuan'), ('completed', '✅ Selesai Terbaru')):
            lines = []
            for row in self.store.quest_list(self.guild_id, status, limit=3):
                line = f"**#{row['id']} {safe(row['title'][:45])}** · {row['points']} poin"
                if status == 'available':
                    line += f" · {row['hours']} jam setelah Accept"
                elif row['user_id']:
                    line += f"\n<@{row['user_id']}>"
                    if status == 'in_progress':
                        line += f" · batas <t:{timestamp(row['deadline'])}:R>"
                lines.append(line)
            if counts.get(status, 0) > 3:
                if status == 'completed':
                    lines.append(f"+{counts[status] - 3} penyelesaian lain tersimpan.")
                else:
                    lines.append(f"+{counts[status] - 3} lainnya; buka panel untuk daftar lengkap.")
            embed.add_field(name=f'{title} ({counts.get(status, 0)})', value='\n\n'.join(lines) or '—', inline=False)
        embed.set_footer(text='Poin setelah disetujui • 1 quest aktif per anggota • Accept Quest membuka kembali panelmu')
        return embed

    def member_render(self, owner, text=None, page=0):
        row = self.store.quest_current(self.guild_id, owner)
        if row:
            return dict(content=text, embed=self.quest_embed(row), view=QuestMemberView(self, owner, row))
        return dict(content=text or 'Pilih quest tersedia, lalu klik Accept Quest Terpilih.', embed=None,
                    view=QuestChoiceView(self, owner, page=page))

    def leader_render(self, owner, text=None, page=0):
        return dict(content=text or 'Pilih quest untuk diperiksa, atau klik Post Quest.', embed=None,
                    view=QuestChoiceView(self, owner, leader=True, page=page))

    def expire(self, now=None):
        if self.store.quest_expire(self.guild_id, now):
            self.dirty = True

    async def refresh_board(self):
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('GUILD_QUEST_CHANNEL_ID harus channel teks di server GUILD_ID.')
        board = self.store.quest_board(self.guild_id)
        kwargs = dict(embed=self.board_embed(), view=QuestMainView(self), allowed_mentions=discord.AllowedMentions.none())
        if board and int(board['channel_id']) == self.channel_id:
            try:
                await channel.get_partial_message(int(board['message_id'])).edit(**kwargs)
                self.dirty = False
                return
            except discord.NotFound:
                pass  # Recreate a deleted dashboard, without touching quest state.
        message = await channel.send(**kwargs)
        self.store.quest_set_board(self.guild_id, self.channel_id, message.id)
        self.dirty = False

    async def refresh_notice(self):
        try:
            await self.refresh_board()
            return ''
        except (discord.HTTPException, ValueError) as exc:
            self.dirty = True
            log.warning('Data guild quest tersimpan; dashboard gagal diperbarui: %s', exc)
            return ' Data tersimpan, tetapi card belum berhasil diperbarui; bot akan mencoba lagi.'

    async def startup(self):
        if not self.enabled:
            return
        async with self.lock:
            self.expire()
            await self.refresh_notice()

    async def tick(self, now=None):
        if not self.enabled:
            return
        now = now or datetime.now(WIB)
        if now < self.next_tick:
            return
        self.next_tick = now + timedelta(seconds=15)
        async with self.lock:
            self.expire(now)
            if self.dirty:
                await self.refresh_notice()

    async def open_panel(self, interaction, leader=False, page=0, edit=False):
        self.require_leader(interaction) if leader else self.require_member(interaction)
        if edit:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock:
            self.expire()
            render = self.leader_render(interaction.user.id, page=page) if leader else self.member_render(interaction.user.id, page=page)
        await interaction.edit_original_response(**render, allowed_mentions=discord.AllowedMentions.none())

    async def open_abort(self, interaction):
        self.require_member(interaction)
        self.expire()
        row = self.store.quest_current(self.guild_id, interaction.user.id)
        if not row:
            raise ValueError('Kamu tidak memiliki quest aktif untuk dibatalkan.')
        await interaction.response.send_message('Batalkan quest dan kembalikan ke daftar tersedia? Tidak ada poin diberikan.',
            ephemeral=True, view=QuestConfirm(self, interaction.user.id, 'abort', row))

    async def mutate(self, interaction, operation, renderer, modal=False):
        self.require_member(interaction)
        if modal:
            await interaction.response.defer(ephemeral=True, thinking=True)
        else:
            await interaction.response.defer()
        async with self.lock:
            self.expire()
            result = operation()
            self.dirty = True
            render = renderer(result)
            warning = await self.refresh_notice()
            if warning:
                render['content'] = (render.get('content') or '') + warning
        await interaction.edit_original_response(**render, allowed_mentions=discord.AllowedMentions.none())

    async def review(self, interaction, row, approve, note='', modal=False):
        self.require_leader(interaction)
        def operation():
            return self.store.quest_review(self.guild_id, row['id'], row['active_attempt_id'],
                interaction.user.id, approve, note, revision=row['revision'])
        def render(changed):
            text = ('Quest disetujui. Poin dan jumlah quest selesai sudah tercatat.' if approve else
                    'Catatan revisi dikirim. Jika waktu habis, quest kembali tersedia.') if changed else 'Submission sudah diproses. Poin tidak ditambahkan lagi.'
            return self.leader_render(interaction.user.id, text)
        await self.mutate(interaction, operation, render, modal=modal)

    def register_commands(self):
        @self.bot.tree.command(name='guildquest', description='Union Leader membuat atau menyegarkan card utama guild quest')
        @app_commands.guild_only()
        async def guildquest(interaction: discord.Interaction):
            self.require_leader(interaction)
            await interaction.response.defer(ephemeral=True)
            async with self.lock:
                self.expire()
                self.dirty = True
                warning = await self.refresh_notice()
            if warning:
                await interaction.followup.send(warning.strip(), ephemeral=True)
            else:
                board = self.store.quest_board(self.guild_id)
                await interaction.followup.send(f"Card guild quest siap: https://discord.com/channels/{self.guild_id}/{board['channel_id']}/{board['message_id']}", ephemeral=True)
