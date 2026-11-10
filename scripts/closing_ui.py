#!/usr/bin/python3
"""Verifica a aba Fechamento com dados isolados e calendário real."""
import os
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import traceback
sys.path.insert(0, os.environ.get('CAIXA_TEST_PACKAGE', str(Path(__file__).resolve().parents[1])) )

with tempfile.TemporaryDirectory() as temporary:
    os.environ['XDG_DATA_HOME'] = temporary + '/data'
    os.environ['XDG_CACHE_HOME'] = temporary + '/cache'
    from caixa_simples.ui import Application
    from caixa_simples.core import Cart
    from gi.repository import Gtk, GLib, Gio, Gdk
    application = Application()
    application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    errors = []

    def walk(widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from walk(child)
            child = child.get_next_sibling()

    def step(callback):
        def run():
            try:
                callback()
            except BaseException as error:
                errors.append(error)
                traceback.print_exc()
                application.quit()
            return False
        GLib.timeout_add(350, run)

    def initial():
        window = application.get_active_window()
        assert window.stack.get_visible_child_name() == 'sell'
        window.stack.set_visible_child_name('closing')
        assert window.closing_sales_value.get_label() == '0'
        assert window.closing_product_list.get_first_child().get_title() == 'Nenhum produto vendido neste dia'
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme.has_icon('document-open-recent-symbolic')
        product = window.store.save_product('arroz', 'Arroz 1 kg', 750)
        cart = Cart()
        cart.add(product)
        cart.add(product)
        window.store.checkout(cart, 'PIX')
        window.stack.set_visible_child_name('sell')
        window.stack.set_visible_child_name('closing')
        assert window.closing_sales_value.get_label() == '2'
        assert window.closing_product_list.get_first_child().get_title() == '1. Arroz 1 kg'
        window.choose_closing_day()
        step(select_date)

    def select_date():
        window = application.get_active_window()
        dialog = window.get_visible_dialog()
        calendar = next(w for w in walk(dialog) if isinstance(w, Gtk.Calendar))
        yesterday = date.today() - timedelta(days=1)
        calendar.select_day(GLib.DateTime.new_local(yesterday.year, yesterday.month, yesterday.day, 12, 0, 0))
        next(w for w in walk(dialog) if isinstance(w, Gtk.Button) and w.get_label() == 'Ver este dia').emit('clicked')
        assert window.closing_day == yesterday
        assert not window.closing_follow_today
        assert window.closing_sales_value.get_label() == '0'
        step(back_today)

    def back_today():
        window = application.get_active_window()
        window.choose_closing_day()
        dialog = window.get_visible_dialog()
        next(w for w in walk(dialog) if isinstance(w, Gtk.Button) and w.get_label() == 'Voltar para hoje').emit('clicked')
        assert window.closing_follow_today
        assert window.closing_sales_value.get_label() == '2'
        # Uma consulta antiga não é trocada pela atualização automática.
        window.closing_follow_today = False
        window.closing_day = date.today() - timedelta(days=1)
        window.closing_tick()
        assert window.closing_sales_value.get_label() == '0'
        window.closing_follow_today = True
        window.closing_tick()
        assert window.closing_sales_value.get_label() == '2'
        print('PASS: aba Fechamento, estado vazio, quantidades, ranking, atualização, calendário, consulta anterior, retorno a hoje e ícone')
        application.quit()

    def exception_hook(kind, value, tb):
        errors.append(value)
        traceback.print_exception(kind, value, tb)
    sys.excepthook = exception_hook
    step(initial)
    application.run([])
    if errors:
        raise SystemExit(1)
