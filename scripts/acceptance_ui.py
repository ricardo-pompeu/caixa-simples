#!/usr/bin/python3
"""Percorre cadastro e finalização reais da UI com falha de impressão controlada."""
import os
from pathlib import Path
import sys
import tempfile
import traceback
sys.path.insert(0, os.environ.get('CAIXA_TEST_PACKAGE', str(Path(__file__).resolve().parents[1])) )

with tempfile.TemporaryDirectory() as temporary:
    os.environ['XDG_DATA_HOME'] = temporary + '/data'
    os.environ['XDG_CACHE_HOME'] = temporary + '/cache'
    from caixa_simples.ui import Application
    from gi.repository import Gtk, Adw, GLib, Gio
    application = Application()
    application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    errors = []
    calls = []

    def walk(widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from walk(child)
            child = child.get_next_sibling()

    def find(kind, predicate):
        dialog = application.get_active_window().get_visible_dialog()
        return next(w for w in walk(dialog) if isinstance(w, kind) and predicate(w))

    def entry(title, text):
        find(Adw.EntryRow, lambda w: w.get_title() == title).set_text(text)

    def click(title):
        find(Gtk.Button, lambda w: w.get_label() == title).emit('clicked')

    def step(callback):
        def wrapped():
            try:
                callback()
            except BaseException as error:
                errors.append(error)
                traceback.print_exc()
                application.quit()
            return False
        GLib.timeout_add(400, wrapped)

    def register():
        window = application.get_active_window()
        window.scan.set_text('7891234567890')
        window.scan.emit('activate')
        entry('Nome do produto', 'Arroz 1 kg')
        entry('Preço de venda (R$)', '7,50')
        click('Salvar e adicionar')
        assert window.store.product('7891234567890').price == 750
        step(checkout)

    def checkout():
        window = application.get_active_window()
        window.scan.set_text('7891234567890')
        window.scan.emit('activate')
        assert window.cart.total == 1500
        window.checkout()
        entry('Recebido (R$, opcional)', '20,00')
        def fail_print(parent, sale, pdf_path, callback):
            calls.append(pdf_path())
            callback(RuntimeError('Falha de impressão de teste'))
        window.printer.print_receipt = fail_print
        click('Concluir e imprimir')
        assert not window.cart.items
        assert len(window.store.recent()) == 1
        assert window.store.sale(1)['change_value'] == 500
        step(reprint)

    def reprint():
        window = application.get_active_window()
        click('Imprimir')
        assert len(calls) == 2
        assert len(window.store.recent()) == 1
        sale = window.store.sale(1)
        pdf = window.receipt_path(sale)
        assert pdf.read_bytes().startswith(b'%PDF-')
        assert any(isinstance(w, Gtk.Label) and 'A venda está salva' in w.get_text() for w in walk(window.get_visible_dialog()))
        print('PASS: cadastro via diálogo, leitor/Enter repetido, troco, conclusão pelo botão, PDF, erro de impressão, reimpressão sem duplicação')
        application.quit()

    def exception_hook(kind, value, tb):
        errors.append(value)
        traceback.print_exception(kind, value, tb)
    sys.excepthook = exception_hook
    step(register)
    application.run([])
    if errors:
        raise SystemExit(1)
