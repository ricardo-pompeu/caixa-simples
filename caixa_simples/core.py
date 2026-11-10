# SPDX-License-Identifier: GPL-3.0-or-later
"""Regras de negócio, persistência e cópias consistentes; sem dependência gráfica."""
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import sqlite3
import unicodedata
import uuid

MAX_CENTS = 999_999_999


def money(cents):
    sign = '-' if cents < 0 else ''
    whole, fraction = divmod(abs(cents), 100)
    return f'{sign}R$ {whole:,}'.replace(',', '.') + f',{fraction:02d}'


def parse_money(text):
    text = text.strip().replace('R$', '').replace(' ', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        value = Decimal(text)
        if not value.is_finite() or value < 0 or value > Decimal(MAX_CENTS) / 100:
            raise ValueError('Informe um valor válido e positivo.')
        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValueError('Use no máximo duas casas decimais.')
        return int(cents)
    except InvalidOperation:
        raise ValueError('Informe o preço, por exemplo: 7,50.') from None


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class Product:
    id: int
    barcode: str
    name: str
    price: int


@dataclass
class Item:
    product_id: int
    name: str
    price: int
    quantity: int = 1

    @property
    def subtotal(self):
        return self.price * self.quantity


class Cart:
    def __init__(self):
        self.items = {}
        self.token = str(uuid.uuid4())

    def add(self, product):
        if product.id in self.items:
            self.change(product.id, 1)
        else:
            self.items[product.id] = Item(product.id, product.name, product.price)

    def change(self, product_id, delta):
        item = self.items[product_id]
        quantity = item.quantity + delta
        if quantity > 99999:
            raise ValueError('Quantidade máxima atingida.')
        if quantity <= 0:
            del self.items[product_id]
        else:
            item.quantity = quantity

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.values())

    def clear(self):
        self.items.clear()
        self.token = str(uuid.uuid4())


def change_due(total, received):
    if received is not None and received < total:
        raise ValueError('O valor recebido é menor que o total da compra.')
    return 0 if received is None else received - total


SCHEMA = '''
CREATE TABLE products (
 id INTEGER PRIMARY KEY, barcode TEXT NOT NULL UNIQUE CHECK(length(barcode)>0),
 name TEXT NOT NULL CHECK(length(name)>0), price INTEGER NOT NULL CHECK(price>0 AND price<=999999999));
CREATE TABLE sales (
 id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE,
 created TEXT NOT NULL, total INTEGER NOT NULL CHECK(total>0),
 payment TEXT NOT NULL CHECK(payment IN ('Dinheiro','PIX','Cartão')),
 received INTEGER CHECK(received IS NULL OR received>=total),
 change_value INTEGER NOT NULL CHECK(change_value>=0),
 store TEXT NOT NULL, footer TEXT NOT NULL);
CREATE TABLE sale_items (
 id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id),
 product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
 name TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>0),
 quantity INTEGER NOT NULL CHECK(quantity>0));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
PRAGMA user_version=1;
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        try:
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError('Este arquivo não é um banco do Caixa Simples.')
                self.db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
            elif version != 1:
                raise ValueError('Este banco precisa de uma versão mais recente do Caixa Simples.')
            if self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Não foi possível verificar seus dados. Restaure um backup.')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            os.chmod(self.path, 0o600)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def product(self, barcode):
        row = self.db.execute('SELECT * FROM products WHERE barcode=?', (barcode.strip(),)).fetchone()
        return Product(**dict(row)) if row else None

    def products(self, query=''):
        needle = normalized(query.strip())
        rows = self.db.execute('SELECT * FROM products ORDER BY name COLLATE NOCASE')
        return [Product(**dict(row)) for row in rows if needle in normalized(row['name']) or needle in normalized(row['barcode'])]

    def save_product(self, barcode, name, price, product_id=None):
        barcode, name = barcode.strip(), name.strip()
        if not barcode or len(barcode) > 200 or any(ord(c) < 32 for c in barcode):
            raise ValueError('Informe um código de barras válido, com até 200 caracteres.')
        if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError('Informe um nome com até 200 caracteres.')
        if type(price) is not int or not 0 < price <= MAX_CENTS:
            raise ValueError('O preço deve ser maior que zero.')
        try:
            with self.db:
                if product_id is None:
                    self.db.execute('INSERT INTO products(barcode,name,price) VALUES(?,?,?)', (barcode, name, price))
                else:
                    self.db.execute('UPDATE products SET barcode=?,name=?,price=? WHERE id=?', (barcode, name, price, product_id))
        except sqlite3.IntegrityError:
            raise ValueError('Este código já está cadastrado. Procure o produto na lista.') from None
        return self.product(barcode)

    def get(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def configure(self, **settings):
        with self.db:
            self.db.executemany('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', [(key, str(value)) for key, value in settings.items()])

    def checkout(self, cart, payment, received=None):
        # O token permanece no carrinho até a confirmação persistida: cliques/retries são idempotentes.
        existing = self.db.execute('SELECT id FROM sales WHERE token=?', (cart.token,)).fetchone()
        if existing:
            return existing[0]
        if not cart.items or cart.total <= 0:
            raise ValueError('Adicione um produto antes de finalizar.')
        if payment not in ('Dinheiro', 'PIX', 'Cartão'):
            raise ValueError('Escolha a forma de pagamento.')
        if received is not None and type(received) is not int:
            raise ValueError('Informe um valor recebido válido.')
        if payment != 'Dinheiro':
            received = None
        change = change_due(cart.total, received)
        with self.db:
            cur = self.db.execute('INSERT INTO sales(token,created,total,payment,received,change_value,store,footer) VALUES(?,?,?,?,?,?,?,?)',
                (cart.token, datetime.now().astimezone().isoformat(), cart.total, payment, received, change,
                 self.get('store', 'Meu estabelecimento'), self.get('footer', 'Obrigado pela preferência!')))
            sale_id = cur.lastrowid
            self.db.executemany('INSERT INTO sale_items(sale_id,product_id,name,price,quantity) VALUES(?,?,?,?,?)',
                [(sale_id, item.product_id, item.name, item.price, item.quantity) for item in cart.items.values()])
        return sale_id

    def sale(self, sale_id):
        row = self.db.execute('SELECT * FROM sales WHERE id=?', (sale_id,)).fetchone()
        if row is None:
            raise ValueError('Venda não encontrada.')
        sale = dict(row)
        sale['items'] = [dict(r) for r in self.db.execute('SELECT * FROM sale_items WHERE sale_id=? ORDER BY id', (sale_id,))]
        return sale

    def recent(self, limit=200, offset=0):
        return [dict(row) for row in self.db.execute('SELECT * FROM sales ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset))]

    def daily_summary(self, day=None):
        """Quantidades pelo dia local registrado em cada venda concluída."""
        day = date.fromisoformat(day).isoformat() if day else date.today().isoformat()
        count = self.db.execute('SELECT COUNT(*) FROM sales WHERE substr(created,1,10)=?', (day,)).fetchone()[0]
        products = {}
        rows = self.db.execute("""
            SELECT i.product_id, i.name, i.quantity
            FROM sale_items i JOIN sales s ON s.id=i.sale_id
            WHERE substr(s.created,1,10)=? ORDER BY s.created DESC, i.id DESC
        """, (day,))
        for row in rows:
            key = ('id', row['product_id']) if row['product_id'] is not None else ('name', row['name'])
            product = products.setdefault(key, {'name': row['name'], 'quantity': 0})
            product['quantity'] += row['quantity']
        ranking = sorted(products.values(), key=lambda item: (-item['quantity'], normalized(item['name'])))
        return {'day': day, 'sales_count': count, 'quantity': sum(p['quantity'] for p in ranking), 'products': ranking}

    def backup(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError('Escolha outro arquivo para o backup.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with closing(sqlite3.connect(temporary)) as target:
                self.db.backup(target)
            os.chmod(temporary, 0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def auto_backup(self):
        folder = self.path.parent / 'backups'
        folder.mkdir(exist_ok=True, mode=0o700)
        name = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3'
        self.backup(folder / name)
        for old in sorted(folder.glob('*.sqlite3'), reverse=True)[10:]:
            old.unlink()

    def restore(self, source):
        source = Path(source)
        if source.resolve() == self.path.resolve():
            raise ValueError('Escolha uma cópia de segurança exportada.')
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as backup:
            self.validate_backup(backup)
            self.auto_backup()  # Sempre preservar o estado anterior à restauração.
            backup.backup(self.db)
        self.db.execute('PRAGMA foreign_keys=ON')

    @staticmethod
    def validate_backup(db):
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Este arquivo não é um backup válido do Caixa Simples.')
        expected = {'products': {'id','barcode','name','price'}, 'sales': {'id','token','created','total','payment','received','change_value','store','footer'}, 'sale_items': {'id','sale_id','product_id','name','price','quantity'}, 'settings': {'key','value'}}
        for table, columns in expected.items():
            if {r[1] for r in db.execute(f'PRAGMA table_info({table})')} != columns:
                raise ValueError('O backup está incompleto ou é incompatível.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('O backup tem registros inconsistentes.')
        if db.execute('SELECT 1 FROM sales s WHERE total != (SELECT COALESCE(SUM(price*quantity),0) FROM sale_items WHERE sale_id=s.id)').fetchone():
            raise ValueError('O backup tem vendas inconsistentes.')
