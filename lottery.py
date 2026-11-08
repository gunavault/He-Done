"""Persistent public item lottery cards with private ticket confirmation."""
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from schedule import WIB
from raid_store import raid_time

log = logging.getLogger('trex.lottery')
STATUS = {'open': 'Pendaftaran dibuka', 'drawn': 'Menunggu penyerahan hadiah',
          'delivered': 'Hadiah sudah diserahkan', 'cancelled': 'Dibatalkan · biaya tiket dikembalikan'}


def safe(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


class LotteryView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        await self.service.bot.command_error(interaction, error)


class LotteryCard(LotteryView):
    def __init__(self, service, row):
        super().__init__(timeout=None)
        self.service, self.lottery_id = service, row['id']
        for action, label in (('join', 'Ikut Lotre'), ('members', 'Lihat Peserta')):
            button = discord.ui.Button(label=label, custom_id=f"lottery:{row['id']}:{action}",
                style=discord.ButtonStyle.success if action == 'join' else discord.ButtonStyle.secondary,
                disabled=action == 'join' and row['status'] != 'open')
            async def callback(interaction, action=action):
                service.require_member(interaction)
                if action == 'join':
                    await service.quote(interaction, self.lottery_id)
                else:
                    await service.members(interaction, self.lottery_id)
            button.callback = callback
            self.add_item(button)


class LotteryConfirm(LotteryView):
    def __init__(self, service, owner, row, action='join'):
        super().__init__(timeout=180)
        self.service, self.owner, self.row, self.action = service, owner, dict(row), action

    def check(self, interaction):
        self.service.require_member(interaction)
        if interaction.user.id != self.owner:
            raise app_commands.CheckFailure('Konfirmasi ini milik anggota yang membukanya.')
        if self.action != 'join':
            self.service.raids.require_admin(interaction)

    @discord.ui.button(label='Ya, konfirmasi', style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.check(interaction)
        await interaction.response.defer()
        async with self.service.raids.lock:
            if self.action == 'join':
                changed = self.service.store.lottery_join(self.service.guild_id, self.row['id'], self.owner, self.row['cost'])
                balance = self.service.store.point_summary(self.service.guild_id, self.owner)['points']
                text = (f"✅ Terdaftar lotre #{self.row['id']}. Biaya **{self.row['cost']} poin** sudah dipotong."
                        if changed else f"Kamu sudah terdaftar lotre #{self.row['id']}; tidak dipotong lagi.")
                text += f'\nSaldo: **{balance} poin**. Satu anggota satu tiket.'
            else:
                self.service.store.lottery_status(self.service.guild_id, self.row['id'], self.action, self.owner)
                text = 'Lotre dibatalkan. Biaya tiket dikembalikan.' if self.action == 'cancel' else 'Penyerahan hadiah dicatat.'
        await interaction.edit_original_response(content=text, embed=None, view=None,
                                                  allowed_mentions=discord.AllowedMentions.none())
        self.stop()
        await self.service.refresh_safely(self.row['id'])

    @discord.ui.button(label='Batal', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.check(interaction)
        await interaction.response.edit_message(content='Konfirmasi ditutup. Tidak ada perubahan.', embed=None, view=None)
        self.stop()


class LotteryService:
    def __init__(self, bot):
        self.bot, self.raids, self.guild_id = bot, bot.raids, bot.guild_id
        self.store = self.raids.store
        self.next_tick = datetime.min.replace(tzinfo=WIB)
        self.register_commands()

    def require_member(self, interaction):
        self.raids.require_guild(interaction)
        if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            raise app_commands.CheckFailure('Lotre hanya untuk anggota server, bukan bot.')

    def restore_views(self):
        for row in self.store.db.execute('SELECT * FROM lotteries WHERE guild_id=? AND message_id IS NOT NULL', (str(self.guild_id),)):
            self.bot.add_view(LotteryCard(self, row), message_id=int(row['message_id']))

    def embed(self, row):
        count = self.store.lottery_count(self.guild_id, row['id'])
        closes = int(datetime.fromisoformat(row['closes_at']).timestamp())
        description = (f"**Hadiah item:** {safe(row['prize'])}\n**Biaya:** {row['cost']} poin per anggota\n"
                       f"**Peserta:** {count} · satu anggota satu tiket\n**Tutup:** <t:{closes}:F> (<t:{closes}:R>)\n"
                       f"**Status:** {STATUS[row['status']]}\n")
        if row['winner_id']:
            description += f"\n🏆 **Pemenang: <@{row['winner_id']}>**\nAdministrator menyerahkan item di game."
        elif row['status'] == 'cancelled':
            description += '\nTidak ada pemenang. Saldo tiket yang belum direset dikembalikan.'
        else:
            description += '\nPoin tiket dihabiskan; hadiah berupa item. Minimal dua peserta. Tidak dapat menarik tiket sendiri.'
        result = discord.Embed(title=f"🎟️ Lotre #{row['id']} — {safe(row['title'])}", description=description,
                               color=0xF1C40F if row['status'] == 'open' else 0x2ECC71)
        result.set_footer(text='WIB · Pengundian otomatis. Pembatalan sebelum tutup oleh Administrator mengembalikan biaya.')
        return result

    async def refresh(self, lottery_id):
        row = self.store.lottery_get(self.guild_id, lottery_id)
        channel = self.bot.get_channel(int(row['channel_id'])) or await self.bot.fetch_channel(int(row['channel_id']))
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('Channel lotre harus channel teks pada server yang diatur.')
        kwargs = dict(embed=self.embed(row), view=LotteryCard(self, row), allowed_mentions=discord.AllowedMentions.none())
        if row['message_id']:
            try:
                await channel.get_partial_message(int(row['message_id'])).edit(**kwargs)
            except discord.NotFound:
                message = await channel.send(**kwargs)
                with self.store.db:
                    self.store.db.execute('UPDATE lotteries SET message_id=? WHERE id=?', (str(message.id), lottery_id))
        else:
            message = await channel.send(**kwargs)
            with self.store.db:
                self.store.db.execute('UPDATE lotteries SET message_id=? WHERE id=?', (str(message.id), lottery_id))
        with self.store.db:
            self.store.db.execute('UPDATE lotteries SET dirty=0 WHERE id=?', (lottery_id,))

    async def refresh_safely(self, lottery_id):
        # Serializes card updates so a late join cannot overwrite a drawn result.
        async with self.raids.lock:
            try:
                await self.refresh(lottery_id)
                return True
            except (discord.HTTPException, ValueError) as exc:
                log.warning('Data lotre #%s tersimpan; card akan dicoba lagi: %s', lottery_id, exc)
                return False

    async def quote(self, interaction, lottery_id):
        self.require_member(interaction)
        row = self.store.lottery_get(self.guild_id, lottery_id)
        if row['status'] != 'open' or datetime.now(WIB) >= datetime.fromisoformat(row['closes_at']):
            raise ValueError('Pendaftaran lotre sudah ditutup.')
        joined = self.store.db.execute('SELECT 1 FROM lottery_tickets WHERE lottery_id=? AND user_id=?',
                                       (lottery_id, str(interaction.user.id))).fetchone()
        if joined:
            await interaction.response.send_message('Kamu sudah terdaftar. Satu anggota satu tiket; tidak ada potongan tambahan.', ephemeral=True)
            return
        balance = self.store.point_summary(self.guild_id, interaction.user.id)['points']
        await interaction.response.send_message(
            f"Ikut lotre **#{lottery_id} — {safe(row['title'])}**?\nHadiah: **{safe(row['prize'])}**\n"
            f"Biaya **{row['cost']} poin**, saldo **{balance} poin**. Poin dipotong setelah konfirmasi.\n"
            'Tiket tidak bisa ditarik sendiri. Jika lotre dibatalkan, biaya dikembalikan.', ephemeral=True,
            view=LotteryConfirm(self, interaction.user.id, row), allowed_mentions=discord.AllowedMentions.none())

    async def members(self, interaction, lottery_id, page=0):
        self.require_member(interaction)
        rows = self.store.lottery_members(self.guild_id, lottery_id, page)
        total = self.store.lottery_count(self.guild_id, lottery_id)
        pages = max(1, (total + 19) // 20)
        if page >= pages:
            raise ValueError(f'Halaman tersedia: 1–{pages}.')
        names = '\n'.join(f'{page * 20 + i}. <@{r["user_id"]}>' for i, r in enumerate(rows, 1)) or 'Belum ada peserta.'
        await interaction.response.send_message(f'**Peserta lotre #{lottery_id} · {total} anggota · halaman {page+1}/{pages}**\n{names}\n'
            f'Halaman lain: /lotrepeserta id:{lottery_id} halaman:<nomor>', ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    async def tick(self, now=None):
        now = now or datetime.now(WIB)
        if now < self.next_tick:
            return
        self.next_tick = now + timedelta(seconds=10)
        async with self.raids.lock:
            due = self.store.db.execute("SELECT id,closes_at FROM lotteries WHERE guild_id=? AND status='open'", (str(self.guild_id),)).fetchall()
            for row in due:
                if datetime.fromisoformat(row['closes_at']) <= now:
                    result = self.store.lottery_draw(self.guild_id, row['id'], now)
                    log.info('Lotre #%s ditutup: status=%s winner_id=%s', row['id'], result['status'], result['winner_id'])
            dirty = [r[0] for r in self.store.db.execute('SELECT id FROM lotteries WHERE guild_id=? AND dirty=1', (str(self.guild_id),))]
        for lottery_id in dirty:
            await self.refresh_safely(lottery_id)

    def register_commands(self):
        @self.bot.tree.command(name='lotre', description='Administrator membuat lotre berhadiah item; satu anggota satu tiket')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.describe(judul='Judul lotre', hadiah='Item yang diserahkan di game', biaya='Biaya satu tiket dalam poin',
                               jam='Jam tutup HH:MM WIB', tanggal='YYYY-MM-DD; kosong untuk hari ini WIB')
        async def lotre(interaction: discord.Interaction, judul: str, hadiah: str,
                        biaya: app_commands.Range[int, 1, 1000000], jam: str, tanggal: str | None = None):
            self.require_member(interaction)
            self.raids.require_admin(interaction)
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
                raise ValueError('Jalankan /lotre di channel teks tujuan lotre.')
            perms = channel.permissions_for(channel.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError('Bot perlu View Channel, Send Messages, dan Embed Links di channel ini.')
            closes = raid_time(jam, tanggal)
            await interaction.response.defer(ephemeral=True)
            async with self.raids.lock:
                row = self.store.lottery_create(self.guild_id, channel.id, interaction.user.id, judul, hadiah,
                                                 biaya, closes, f'lottery:{interaction.id}')
            success = await self.refresh_safely(row['id'])
            await interaction.followup.send(f"Lotre #{row['id']} dibuat. " + ('Card dikirim ke channel ini.' if success else
                'Card belum berhasil dikirim; bot akan mencoba lagi. Data sudah tersimpan.'), ephemeral=True)

        @self.bot.tree.command(name='lotrestatus', description='Administrator membatalkan lotre atau mencatat penyerahan hadiah')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.choices(aksi=[app_commands.Choice(name='Batalkan dan refund poin', value='cancel'),
                                   app_commands.Choice(name='Hadiah sudah diserahkan', value='deliver')])
        async def lotrestatus(interaction: discord.Interaction, id: app_commands.Range[int, 1], aksi: str):
            self.require_member(interaction)
            self.raids.require_admin(interaction)
            row = self.store.lottery_get(self.guild_id, id)
            if aksi not in ('cancel', 'deliver'):
                raise ValueError('Aksi tidak dikenal.')
            text = 'Batalkan lotre dan kembalikan biaya seluruh peserta?' if aksi == 'cancel' else 'Konfirmasi item sudah diberikan kepada pemenang?'
            await interaction.response.send_message(f'**Lotre #{id} — {safe(row["title"])}**\n{text}', ephemeral=True,
                view=LotteryConfirm(self, interaction.user.id, row, aksi), allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='lotrepeserta', description='Lihat daftar peserta lotre')
        @app_commands.guild_only()
        async def lotrepeserta(interaction: discord.Interaction, id: app_commands.Range[int, 1], halaman: app_commands.Range[int, 1] = 1):
            await self.members(interaction, id, halaman - 1)

        @self.bot.tree.command(name='lotrelihat', description='Lihat status dan hasil lotre berdasarkan ID')
        @app_commands.guild_only()
        async def lotrelihat(interaction: discord.Interaction, id: app_commands.Range[int, 1]):
            self.require_member(interaction)
            row = self.store.lottery_get(self.guild_id, id)
            await interaction.response.send_message(embed=self.embed(row), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
