from pathlib import Path
import runpy
import tempfile
import unittest

from bipe.core import Cart, Store

migration = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'migrar-bipe.py'))


class MigrationTest(unittest.TestCase):
    def test_snapshot_preserves_sales_preferences_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_id = migration['OLD_ID']
            new_id = migration['NEW_ID']
            source = root / old_id / 'data' / old_id / 'caixa.sqlite3'
            target = root / new_id / 'data' / new_id / 'caixa.sqlite3'
            old = Store(source)
            try:
                item = old.save_product('1', 'Café', 300)
                cart = Cart()
                cart.add(item)
                old.checkout(cart, 'PIX')
                old.configure(local_printer='POS-80', auto_cut=1)
                migration['migrate'](root)
                new = Store(target)
                try:
                    self.assertEqual(new.product('1').name, 'Café')
                    self.assertEqual(new.sale(1)['total'], 300)
                    self.assertEqual(new.get('local_printer'), 'POS-80')
                    self.assertEqual(new.get('auto_cut'), '1')
                    new.configure(store='Banco novo')
                    migration['migrate'](root)
                    self.assertEqual(new.get('store'), 'Banco novo')
                    self.assertEqual(old.get('store'), '')
                finally:
                    new.close()
            finally:
                old.close()
