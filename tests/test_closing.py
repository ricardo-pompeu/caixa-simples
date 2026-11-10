from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from caixa_simples.core import Store, Cart


class DailySummaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'db.sqlite3')
        self.rice = self.store.save_product('arroz', 'Arroz 1 kg', 750)
        self.beans = self.store.save_product('feijao', 'Feijão', 890)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def sell(self, products, payment='Dinheiro'):
        cart = Cart()
        for product in products:
            cart.add(product)
        return self.store.checkout(cart, payment)

    def test_empty_day(self):
        summary = self.store.daily_summary('2000-01-01')
        self.assertEqual(summary['sales_count'], 0)
        self.assertEqual(summary['products'], [])

    def test_quantities_and_ranking(self):
        self.sell([self.rice, self.rice, self.beans])
        self.sell([self.rice], 'PIX')
        self.sell([self.beans], 'Cartão')
        summary = self.store.daily_summary()
        self.assertEqual(summary['day'], date.today().isoformat())
        self.assertEqual(summary['sales_count'], 3)
        self.assertEqual(summary['quantity'], 5)
        self.assertEqual(summary['products'][0], {'name': 'Arroz 1 kg', 'quantity': 3})

    def test_day_isolation_and_historical_names(self):
        older = self.sell([self.rice])
        with self.store.db:
            self.store.db.execute('UPDATE sales SET created=? WHERE id=?', ('2000-01-01T23:59:59-03:00', older))
        self.store.save_product('arroz', 'Arroz novo', 1000, self.rice.id)
        self.sell([self.store.product('arroz')])
        self.assertEqual(self.store.daily_summary('2000-01-01')['quantity'], 1)
        self.assertEqual(self.store.daily_summary()['quantity'], 1)
        self.assertEqual(self.store.daily_summary('2000-01-01')['products'][0]['name'], 'Arroz 1 kg')

    def test_same_product_renamed_and_unsold_cart(self):
        self.sell([self.rice, self.rice])
        renamed = self.store.save_product('arroz', 'Arroz novo', 1000, self.rice.id)
        self.sell([renamed])
        cart = Cart()
        cart.add(self.beans)
        summary = self.store.daily_summary()
        self.assertEqual(len(summary['products']), 1)
        self.assertEqual(summary['products'][0]['quantity'], 3)
        self.assertEqual(summary['products'][0]['name'], 'Arroz novo')

    def test_backup_restore_and_reopen_summary(self):
        self.sell([self.rice, self.rice])
        backup = Path(self.temp.name) / 'backup.sqlite3'
        self.store.backup(backup)
        self.sell([self.beans])
        self.store.restore(backup)
        self.store.close()
        self.store = Store(Path(self.temp.name) / 'db.sqlite3')
        summary = self.store.daily_summary()
        self.assertEqual(summary['quantity'], 2)
        self.assertEqual(summary['sales_count'], 1)
