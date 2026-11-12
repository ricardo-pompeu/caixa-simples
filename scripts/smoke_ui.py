#!/usr/bin/python3
"""Verificação gráfica isolada. Execute com um backend GTK disponível."""
import os
from pathlib import Path
import tempfile
import sys
import traceback
sys.path.insert(0, os.environ.get('CAIXA_TEST_PACKAGE', str(Path(__file__).resolve().parents[1])))
with tempfile.TemporaryDirectory() as temporary:
    os.environ['XDG_DATA_HOME'] = temporary + '/data'
    os.environ['XDG_CACHE_HOME'] = temporary + '/cache'
    from bipe.ui import Application, Window
    from gi.repository import GLib, Gtk, Gio
    application = Application()
    application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    errors = []
    def exception_hook(kind, value, tb):
        errors.append(value)
        traceback.print_exception(kind, value, tb)
    sys.excepthook = exception_hook
    def check():
        try:
            window = application.get_active_window()
            assert isinstance(window, Window), 'Janela principal não abriu'
            assert window.stack.get_visible_child_name() == 'sell'
            product = window.store.save_product('789', 'Arroz 1 kg', 750)
            window.refresh_products()
            window.scan.set_text('789')
            window.scanned(window.scan)
            window.scan.set_text('789')
            window.scanned(window.scan)
            assert window.cart.total == 1500
            assert window.cart.items[product.id].quantity == 2
            window.product_dialog(product=product)
            window.history()
            window.preferences()
            window.checkout()
            sale_id = window.store.checkout(window.cart, 'Dinheiro', 2000)
            window.show_receipt(sale_id)
            window.receipt_path(window.store.sale(sale_id))
            window.about()
            window.clear_cart()
            print('PASS: janela, código HID/Enter, quantidade, produtos, pagamento, histórico, preferências, comprovante e PDF')
        except BaseException as error:
            errors.append(error)
            traceback.print_exc()
        finally:
            application.quit()
        return False
    GLib.timeout_add(800, check)
    application.run([])
    if errors:
        raise SystemExit(1)
