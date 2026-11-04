"""Redeem catalog, member confirmations, and administrator delivery queue."""
import uuid

import discord
from discord import app_commands

ORDER_STATUS = {'pending': 'Menunggu penyerahan', 'fulfilled': 'Sudah diserahkan', 'cancelled': 'Dibatalkan'}


def safe(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))


class RedeemView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        await self.service.bot.command_error(interaction, error)


class CatalogPublicView(RedeemView):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label='Tukar Poin', style=discord.ButtonStyle.success, custom_id='redeem:catalog:open')
    async def open_catalog(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.service.require_member(interaction)
        await self.service.show_private_catalog(interaction)


class CatalogSelectView(RedeemView):
    def __init__(self, service, owner_id, page=0):
        super().__init__(timeout=180)
        self.service, self.owner_id, self.page = service, owner_id, page
        items = service.store.catalog_items(service.guild_id, page)
        if items:
            select = discord.ui.Select(placeholder='Pilih item untuk ditukar', options=[
                discord.SelectOption(label=item['name'], value=str(item['id']), description=f"{item['price']} poin")
                for item in items], row=0)

            async def choose(interaction):
                await service.quote(interaction, int(select.values[0]), edit=True)
            select.callback = choose
            self.add_item(select)
        for delta, label in ((-1, 'Sebelumnya'), (1, 'Berikutnya')):
            disabled = page == 0 if delta == -1 else not service.store.catalog_items(service.guild_id, page + 1)
            button = discord.ui.Button(label=label, row=1, disabled=disabled)

            async def navigate(interaction, delta=delta):
                await service.show_private_catalog(interaction, page + delta, edit=True)
            button.callback = navigate
            self.add_item(button)

    async def interaction_check(self, interaction):
        try:
            self.service.require_member(interaction)
            if interaction.user.id != self.owner_id:
                raise ValueError('Menu redeem ini milik anggota yang membukanya.')
            return True
        except (ValueError, app_commands.CheckFailure) as exc:
            await self.service.bot.command_error(interaction, exc)
            return False


class RedeemConfirmView(RedeemView):
    def __init__(self, service, owner_id, item):
        super().__init__(timeout=180)
        self.service, self.owner_id, self.item = service, owner_id, dict(item)
        # Stable across repeated clicks on this confirmation, unlike interaction IDs.
        self.request_id = 'redeem:' + uuid.uuid4().hex

    def require_owner(self, interaction):
        self.service.require_member(interaction)
        if interaction.user.id != self.owner_id:
            raise app_commands.CheckFailure('Konfirmasi redeem ini hanya untuk anggota yang membukanya.')

    @discord.ui.button(label='Konfirmasi Redeem', style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.require_owner(interaction)
        await interaction.response.defer()
        async with self.service.raids.lock:
            order = self.service.store.redeem_item(self.service.guild_id, self.owner_id,
                self.item['id'], self.item['name'], self.item['price'], self.request_id)
            balance = self.service.store.point_summary(self.service.guild_id, self.owner_id)['points']
        await interaction.edit_original_response(content=(
            f"✅ Redeem #{order['id']} — **{safe(order['item_name'])}** · {order['price']} poin.\n"
            f"Status: **{ORDER_STATUS[order['status']]}**. Saldo: **{balance} poin**.\n"
            'Hubungi Administrator untuk penyerahan barang. Riwayat: /redeemhistory.'), embed=None, view=None,
            allowed_mentions=discord.AllowedMentions.none())
        self.stop()

    @discord.ui.button(label='Batal', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.require_owner(interaction)
        await interaction.response.edit_message(content='Konfirmasi ditutup. Tidak ada penukaran baru.', embed=None, view=None)
        self.stop()


class RedeemService:
    def __init__(self, bot):
        self.bot, self.raids, self.guild_id = bot, bot.raids, bot.guild_id
        self.store = self.raids.store
        self.store.seed_catalog(self.guild_id)
        self.register_commands()

    def require_member(self, interaction):
        self.raids.require_guild(interaction)
        if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            raise app_commands.CheckFailure('Redeem hanya untuk anggota manusia di server ini.')

    def restore_views(self):
        self.bot.add_view(CatalogPublicView(self))

    def catalog_embed(self, page=0, balance=None):
        items = self.store.catalog_items(self.guild_id, page)
        lines = [f"**#{item['id']} · {safe(item['name'])}** — {item['price']} poin" for item in items]
        if not lines:
            lines = ['Tidak ada item aktif pada halaman ini.']
        if balance is not None:
            lines.insert(0, f'**Saldo kamu: {balance} poin**\n')
        embed = discord.Embed(title=f'🎁 Katalog Redeem — halaman {page + 1}', description='\n'.join(lines), color=0xF1C40F)
        embed.set_footer(text='Satu redeem = satu item. Poin dipotong setelah konfirmasi; barang diserahkan Administrator.')
        return embed

    async def show_private_catalog(self, interaction, page=0, edit=False):
        self.require_member(interaction)
        balance = self.store.point_summary(self.guild_id, interaction.user.id)['points']
        kwargs = dict(embed=self.catalog_embed(page, balance),
                      view=CatalogSelectView(self, interaction.user.id, page), allowed_mentions=discord.AllowedMentions.none())
        if edit:
            await interaction.response.edit_message(**kwargs)
        else:
            await interaction.response.send_message(**kwargs, ephemeral=True)

    async def quote(self, interaction, item_id, edit=False):
        self.require_member(interaction)
        item = self.store.catalog_item(self.guild_id, item_id)
        balance = self.store.point_summary(self.guild_id, interaction.user.id)['points']
        if balance < item['price']:
            raise ValueError(f"Poin tidak cukup. Saldo {balance}; perlu {item['price']} poin.")
        embed = discord.Embed(title='Konfirmasi penukaran', description=(
            f"**{safe(item['name'])}**\nHarga: **{item['price']} poin**\n"
            f"Saldo: {balance} → **{balance - item['price']} poin**\n"
            'Klik Konfirmasi Redeem untuk memotong poin. Barang diserahkan manual oleh Administrator.'), color=0xF1C40F)
        kwargs = dict(embed=embed, view=RedeemConfirmView(self, interaction.user.id, item),
                      allowed_mentions=discord.AllowedMentions.none())
        if edit:
            await interaction.response.edit_message(**kwargs)
        else:
            await interaction.response.send_message(**kwargs, ephemeral=True)

    def orders_embed(self, rows, title):
        lines = []
        for row in rows:
            lines.append(f"**#{row['id']}** · <@{row['user_id']}> · {safe(row['item_name'])}\n"
                         f"{row['price']} poin · **{ORDER_STATUS[row['status']]}**")
        return discord.Embed(title=title, description='\n\n'.join(lines) or 'Belum ada penukaran pada halaman ini.', color=0xF1C40F)

    def register_commands(self):
        async def check_server(interaction):
            self.raids.require_guild(interaction)
            return True

        @self.bot.tree.command(name='katalog', description='Tampilkan katalog penukaran poin di channel ini')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def katalog(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            self.require_member(interaction)
            await interaction.response.send_message(embed=self.catalog_embed(halaman - 1), view=CatalogPublicView(self),
                                                    allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='katalogadd', description='Administrator menambah satu item katalog redeem')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.describe(nama='Nama item baru, maksimal 100 karakter', harga='Harga tukar dalam poin')
        async def katalogadd(interaction: discord.Interaction, nama: str, harga: app_commands.Range[int, 1, 1000000]):
            self.raids.require_admin(interaction)
            await interaction.response.defer(ephemeral=True)
            async with self.raids.lock:
                item_id = self.store.catalog_add(self.guild_id, nama, harga, interaction.user.id)
            await interaction.followup.send(f'Item #{item_id} **{safe(nama.strip())}** ditambahkan · {harga} poin. Buka /katalog untuk daftar terbaru.',
                                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='katalogremove', description='Administrator menghapus item dari katalog aktif')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.describe(item='Nomor item dari /katalog')
        async def katalogremove(interaction: discord.Interaction, item: int):
            self.raids.require_admin(interaction)
            await interaction.response.defer(ephemeral=True)
            async with self.raids.lock:
                old = self.store.catalog_remove(self.guild_id, item, interaction.user.id)
            await interaction.followup.send(f"Item #{item} **{safe(old['name'])}** dihapus dari katalog aktif. Penukaran yang sudah tercatat tetap diproses.",
                                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='redeem', description='Pilih item atau konfirmasi penukaran poin milikmu')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        @app_commands.describe(item='Opsional: nomor item dari /katalog')
        async def redeem(interaction: discord.Interaction, item: int | None = None):
            if item is None:
                await self.show_private_catalog(interaction)
            else:
                await self.quote(interaction, item)

        @self.bot.tree.command(name='redeemhistory', description='Lihat riwayat penukaran poin milikmu')
        @app_commands.guild_only()
        @app_commands.check(check_server)
        async def redeemhistory(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            self.require_member(interaction)
            rows = self.store.redeem_orders(self.guild_id, interaction.user.id, page=halaman - 1)
            await interaction.response.send_message(embed=self.orders_embed(rows, f'Riwayat Redeem — halaman {halaman}'),
                                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='redeemqueue', description='Administrator melihat antrean barang yang belum diserahkan')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        async def redeemqueue(interaction: discord.Interaction, halaman: app_commands.Range[int, 1, 10000] = 1):
            self.raids.require_admin(interaction)
            rows = self.store.redeem_orders(self.guild_id, pending_only=True, page=halaman - 1)
            await interaction.response.send_message(embed=self.orders_embed(rows, f'Antrean Redeem — halaman {halaman}'),
                                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @self.bot.tree.command(name='redeemstatus', description='Administrator menandai barang diserahkan atau membatalkan redeem')
        @app_commands.guild_only()
        @app_commands.default_permissions(administrator=True)
        @app_commands.check(check_server)
        @app_commands.choices(status=[app_commands.Choice(name='Sudah diserahkan', value='fulfilled'),
                                     app_commands.Choice(name='Batalkan dan kembalikan poin', value='cancelled')])
        @app_commands.describe(id='Nomor penukaran dari antrean', status='Tindakan untuk penukaran yang menunggu')
        async def redeemstatus(interaction: discord.Interaction, id: int, status: str):
            self.raids.require_admin(interaction)
            await interaction.response.defer(ephemeral=True)
            async with self.raids.lock:
                order, changed, refund = self.store.set_redeem_status(self.guild_id, id, status, interaction.user.id)
            text = f"Redeem #{id}: **{ORDER_STATUS[order['status']]}**."
            if not changed:
                text += ' Sudah diproses sebelumnya; tidak ada perubahan poin.'
            elif status == 'cancelled':
                text += f' {refund} poin dikembalikan (0 jika poin sudah direset dari console).'
            await interaction.followup.send(text, ephemeral=True)
