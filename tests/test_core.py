import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import closing
from bipe.core import Store, Cart, money, parse_money, change_due
from bipe.receipt import render_pdf, receipt_lines, Printer


class CashTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'db.sqlite3'
        self.store = Store(self.path)
        self.rice = self.store.save_product('7891234567890', 'Arroz 1 kg', 750)
        self.cart = Cart()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def sale(self):
        self.cart.add(self.rice)
        self.cart.add(self.rice)
        return self.store.checkout(self.cart, 'Dinheiro', 2000)

    def test_01_register_lookup_duplicate(self):
        self.assertEqual(self.store.product(self.rice.barcode), self.rice)
        with self.assertRaisesRegex(ValueError, 'já está cadastrado'):
            self.store.save_product(self.rice.barcode, 'Outro', 900)
        product = self.store.save_product('ABC-123', 'Café', 100)
        self.assertEqual(self.store.products('cafe'), [product])
        self.assertEqual(self.store.products('ABC-123'), [product])
        with self.assertRaises(ValueError):
            self.store.save_product('', 'Sem código', 100)
        with self.assertRaises(ValueError):
            self.store.save_product('novo', 'Grátis', 0)

    def test_02_cart_quantities_totals(self):
        self.cart.add(self.rice)
        self.cart.add(self.rice)
        beans = self.store.save_product('002', 'Feijão', 890)
        self.cart.add(beans)
        self.assertEqual(self.cart.items[self.rice.id].quantity, 2)
        self.assertEqual(self.cart.items[self.rice.id].subtotal, 1500)
        self.assertEqual(self.cart.total, 2390)
        self.cart.change(self.rice.id, -1)
        self.assertEqual(self.cart.total, 1640)
        self.cart.change(beans.id, -1)
        self.assertEqual(self.cart.total, 750)

    def test_03_money_change(self):
        self.assertEqual(parse_money('R$ 1.234,56'), 123456)
        self.assertEqual(parse_money('7.50'), 750)
        self.assertEqual(money(123456), 'R$ 1.234,56')
        self.assertEqual(change_due(1850, 2000), 150)
        self.assertEqual(change_due(1850, None), 0)
        for text in ('NaN', 'Infinity', '-1', '1,001', '', '100000000000'):
            with self.assertRaises(ValueError):
                parse_money(text)
        with self.assertRaises(ValueError):
            change_due(1850, 1800)

    def test_04_persistence_and_snapshot(self):
        sale_id = self.sale()
        self.store.save_product(self.rice.barcode, 'Arroz novo', 1000, self.rice.id)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.product(self.rice.barcode).price, 1000)
        sale = self.store.sale(sale_id)
        self.assertEqual(sale['total'], 1500)
        self.assertEqual(sale['items'][0]['name'], 'Arroz 1 kg')
        self.assertEqual(sale['items'][0]['price'], 750)
        self.assertEqual(sale['change_value'], 500)
        self.assertTrue(sale['created'])

    def test_05_checkout_validation_idempotence(self):
        with self.assertRaises(ValueError):
            self.store.checkout(self.cart, 'PIX')
        sale_id = self.sale()
        self.assertEqual(self.store.checkout(self.cart, 'Dinheiro', 2000), sale_id)
        self.assertEqual(len(self.store.recent()), 1)
        self.cart.clear()
        self.cart.add(self.rice)
        self.store.checkout(self.cart, 'PIX', 1)
        self.assertIsNone(self.store.sale(2)['received'])

    def test_06_pdf_and_reprint(self):
        sale_id = self.sale()
        sale = self.store.sale(sale_id)
        lines = '\n'.join(receipt_lines(sale))
        for expected in ('COMPROVANTE NÃO FISCAL', '2× Arroz 1 kg', 'R$ 15,00', 'R$ 5,00'):
            self.assertIn(expected, lines)
        for width in (58, 80):
            path = render_pdf(sale, self.root / f'{width}.pdf', width)
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            render_pdf(self.store.sale(sale_id), path, width)
        self.assertEqual(len(self.store.recent()), 1)

    def test_07_real_print_adapter_failure_preserves_sale(self):
        sale_id = self.sale()
        printer = Printer.__new__(Printer)
        printer.setup = None
        printer.dialog = Mock()
        printer.dialog.print_file_finish.side_effect = RuntimeError('Impressora indisponível')
        printer.dialog.print_file.side_effect = lambda parent, setup, file, cancel, callback: callback(printer.dialog, None)
        callback = Mock()
        printer.print_pdf(None, self.root / 'receipt.pdf', callback)
        self.assertIsInstance(callback.call_args[0][0], RuntimeError)
        self.assertEqual(self.store.sale(sale_id)['total'], 1500)
        self.assertEqual(len(self.store.recent()), 1)
        printer.dialog.print_file_finish.side_effect = None
        printer.print_pdf(None, self.root / 'receipt.pdf', callback)
        callback.assert_called_with(None)
        self.assertEqual(len(self.store.recent()), 1)

    def test_08_backup_restore_retention(self):
        self.sale()
        backup = self.root / 'copy.sqlite3'
        self.store.backup(backup)
        self.store.save_product('novo', 'Novo', 250)
        self.store.restore(backup)
        self.assertIsNone(self.store.product('novo'))
        self.assertEqual(len(self.store.recent()), 1)
        safety = list((self.root / 'backups').glob('*.sqlite3'))
        with closing(sqlite3.connect(safety[0])) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM products WHERE barcode='novo'").fetchone()[0], 1)
        for _ in range(12):
            self.store.auto_backup()
        self.assertEqual(len(list((self.root / 'backups').glob('*.sqlite3'))), 10)

    def test_09_reject_bad_backup_without_changes(self):
        self.sale()
        bad = self.root / 'bad.sqlite3'
        with closing(sqlite3.connect(bad)) as db:
            db.execute('PRAGMA user_version=1')
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        self.assertEqual(len(self.store.recent()), 1)
        self.assertEqual(self.store.product(self.rice.barcode), self.rice)

    def test_10_transaction_rollback(self):
        self.cart.add(self.rice)
        self.cart.items[self.rice.id].product_id = 9999
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.checkout(self.cart, 'PIX')
        self.assertEqual(len(self.store.recent()), 0)

    def test_12_offline(self):
        with patch('socket.socket', side_effect=AssertionError('Rede não deve ser usada')):
            sale_id = self.sale()
            self.store.auto_backup()
            render_pdf(self.store.sale(sale_id), self.root / 'offline.pdf')
            self.assertEqual(self.store.sale(sale_id)['total'], 1500)

    def test_11_long_receipt(self):
        for i in range(40):
            self.cart.add(self.store.save_product(str(i), 'Produto com nome longo e acentuação ' * 3, 333))
        sale_id = self.store.checkout(self.cart, 'Cartão')
        render_pdf(self.store.sale(sale_id), self.root / 'long.pdf', 58)
        self.assertEqual(self.store.sale(sale_id)['total'], 13320)


if __name__ == '__main__':
    unittest.main()
