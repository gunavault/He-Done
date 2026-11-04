"""Catalog and transactional redemption methods sharing the bot's point ledger."""
import sqlite3
from datetime import datetime
from schedule import WIB

DEFAULT_CATALOG = (
    ('Senjata Tarbo', 200), ('Senjata Iguana', 200), ('Senjata Amarga', 300),
    ('Senjata T-Rex', 500), ('Armor Brachi / RedIguana', 200),
    ('Kepala (helm) Brachi / RedIguana', 100), ('Sarung tangan', 80), ('Sepatu', 80),
)


class RedeemStoreMixin:
    def init_redeem_tables(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS redeem_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,
                name TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>0),
                active INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS redeem_catalog_active_name
                ON redeem_catalog(guild_id,name COLLATE NOCASE) WHERE active=1;
            CREATE TABLE IF NOT EXISTS redeem_catalog_seeds (guild_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS redeem_catalog_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL REFERENCES redeem_catalog(id),
                actor_id TEXT NOT NULL,action TEXT NOT NULL,at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS redeem_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT NOT NULL UNIQUE,
                guild_id TEXT NOT NULL,user_id TEXT NOT NULL,item_id INTEGER NOT NULL REFERENCES redeem_catalog(id),
                item_name TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>0),
                status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,
                handled_by TEXT,handled_at TEXT,voided INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS redeem_orders_user ON redeem_orders(guild_id,user_id);
            CREATE INDEX IF NOT EXISTS redeem_orders_status ON redeem_orders(guild_id,status);
        ''')

    def seed_catalog(self, guild_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM redeem_catalog_seeds WHERE guild_id=?', (str(guild_id),)).fetchone():
                return
            for name, price in DEFAULT_CATALOG:
                self.db.execute('''INSERT OR IGNORE INTO redeem_catalog(guild_id,name,price,created_by,created_at)
                    VALUES(?,?,?,'initial',?)''', (str(guild_id), name, price, datetime.now(WIB).isoformat()))
            self.db.execute('INSERT INTO redeem_catalog_seeds VALUES(?)', (str(guild_id),))

    def catalog_items(self, guild_id, page=0):
        return self.db.execute('SELECT * FROM redeem_catalog WHERE guild_id=? AND active=1 ORDER BY id LIMIT 10 OFFSET ?',
                               (str(guild_id), page * 10)).fetchall()

    def catalog_item(self, guild_id, item_id):
        row = self.db.execute('SELECT * FROM redeem_catalog WHERE id=? AND guild_id=? AND active=1',
                              (item_id, str(guild_id))).fetchone()
        if row is None:
            raise ValueError('Item tidak tersedia. Buka /katalog untuk melihat item aktif.')
        return row

    def catalog_add(self, guild_id, name, price, actor_id):
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError('Nama item harus 1–100 karakter.')
        if type(price) is not int or not 1 <= price <= 1000000:
            raise ValueError('Harga harus bilangan bulat 1–1000000 poin.')
        try:
            with self.db:
                now = datetime.now(WIB).isoformat()
                cur = self.db.execute('''INSERT INTO redeem_catalog(guild_id,name,price,created_by,created_at)
                    VALUES(?,?,?,?,?)''', (str(guild_id), name, price, str(actor_id), now))
                self.db.execute('INSERT INTO redeem_catalog_audit(item_id,actor_id,action,at) VALUES(?,?,?,?)',
                                (cur.lastrowid, str(actor_id), 'add', now))
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Nama item aktif sudah ada di katalog.') from None

    def catalog_remove(self, guild_id, item_id, actor_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            item = self.catalog_item(guild_id, item_id)
            self.db.execute('UPDATE redeem_catalog SET active=0 WHERE id=?', (item_id,))
            self.db.execute('INSERT INTO redeem_catalog_audit(item_id,actor_id,action,at) VALUES(?,?,?,?)',
                            (item_id, str(actor_id), 'remove', datetime.now(WIB).isoformat()))
            return item

    def redeem_item(self, guild_id, user_id, item_id, name, price, request_id):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM redeem_orders WHERE request_id=?', (str(request_id),)).fetchone()
            if old:
                if (old['guild_id'], old['user_id'], old['item_id'], old['item_name'], old['price']) != (str(guild_id), str(user_id), item_id, name, price):
                    raise ValueError('Konfirmasi redeem sudah dipakai untuk data berbeda.')
                return old
            item = self.catalog_item(guild_id, item_id)
            if (item['name'], item['price']) != (name, price):
                raise ValueError('Item atau harga berubah. Buka /redeem lagi untuk konfirmasi terbaru.')
            balance = self.point_summary(guild_id, user_id)['points']
            if balance < item['price']:
                raise ValueError(f"Poin tidak cukup. Saldo {balance} poin; perlu {item['price']} poin.")
            cur = self.db.execute('''INSERT INTO redeem_orders
                (request_id,guild_id,user_id,item_id,item_name,price,created_at) VALUES(?,?,?,?,?,?,?)''',
                (str(request_id), str(guild_id), str(user_id), item_id, item['name'], item['price'], datetime.now(WIB).isoformat()))
            return self.redeem_order(guild_id, cur.lastrowid)

    def redeem_order(self, guild_id, order_id):
        row = self.db.execute('SELECT * FROM redeem_orders WHERE guild_id=? AND id=?', (str(guild_id), order_id)).fetchone()
        if row is None:
            raise ValueError('Penukaran tidak ditemukan di server ini.')
        return row

    def redeem_orders(self, guild_id, user_id=None, pending_only=False, page=0):
        where, params = 'guild_id=?', [str(guild_id)]
        if user_id is not None:
            where += ' AND user_id=?'
            params.append(str(user_id))
        if pending_only:
            where += " AND status='pending'"
        return self.db.execute(f'SELECT * FROM redeem_orders WHERE {where} ORDER BY id DESC LIMIT 10 OFFSET ?',
                               (*params, page * 10)).fetchall()

    def set_redeem_status(self, guild_id, order_id, status, actor_id):
        if status not in ('fulfilled', 'cancelled'):
            raise ValueError('Status harus selesai atau dibatalkan.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.redeem_order(guild_id, order_id)
            if old['status'] == status:
                return old, False, 0
            if old['status'] != 'pending':
                raise ValueError('Penukaran sudah diproses; tidak bisa diubah lagi.')
            self.db.execute('UPDATE redeem_orders SET status=?,handled_by=?,handled_at=? WHERE id=?',
                            (status, str(actor_id), datetime.now(WIB).isoformat(), order_id))
            refund = old['price'] if status == 'cancelled' and not old['voided'] else 0
            return self.redeem_order(guild_id, order_id), True, refund
