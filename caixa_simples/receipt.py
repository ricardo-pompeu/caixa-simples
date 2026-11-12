# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprovantes térmicos em PDF com texto Pango; impressão nativa assíncrona."""
from datetime import datetime
from pathlib import Path
from threading import Thread
import cairo
import gi
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Pango, PangoCairo
from .core import money
from .thermal import Cups, select_queue


def receipt_lines(sale):
    lines = [sale['store'], 'COMPROVANTE NÃO FISCAL',
             datetime.fromisoformat(sale['created']).strftime('Data: %d/%m/%Y  %H:%M'),
             f"Venda: {sale['id']:06d}", '─' * 24]
    for item in sale['items']:
        lines += [f"{item['quantity']}× {item['name']}", f"{money(item['price'])} un.   {money(item['price'] * item['quantity'])}"]
    lines += ['─' * 24, 'TOTAL: ' + money(sale['total']), 'Pagamento: ' + sale['payment']]
    if sale['received'] is not None:
        lines += ['Recebido: ' + money(sale['received']), 'Troco: ' + money(sale['change_value'])]
    if sale['footer']:
        lines += ['─' * 24, sale['footer']]
    return lines


def render_pdf(sale, path, width_mm=80):
    if width_mm not in (58, 80):
        raise ValueError('Escolha bobina de 58 ou 80 mm.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width = width_mm * 72 / 25.4
    margin = 9
    lines = receipt_lines(sale)
    # Mede e quebra cada parágrafo antes de dimensionar a bobina.
    measure = cairo.Context(cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None))
    layout = PangoCairo.create_layout(measure)
    layout.set_font_description(Pango.FontDescription('Sans 9'))
    layout.set_width(int((width - margin * 2) * Pango.SCALE))
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    heights = []
    for line in lines:
        layout.set_text(line, -1)
        heights.append(layout.get_size()[1] / Pango.SCALE + 4)
    height = max(180, sum(heights) + margin * 2)
    surface = cairo.PDFSurface(str(path), width, height)
    surface.set_metadata(cairo.PDF_METADATA_TITLE, f"Comprovante não fiscal — venda {sale['id']:06d}")
    context = cairo.Context(surface)
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(Pango.FontDescription('Sans 9'))
    layout.set_width(int((width - margin * 2) * Pango.SCALE))
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    y = margin
    for line, line_height in zip(lines, heights):
        layout.set_text(line, -1)
        context.move_to(margin, y)
        PangoCairo.show_layout(context, layout)
        y += line_height
    surface.finish()
    return path


class Printer:
    def __init__(self, store):
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        self.Gtk = Gtk
        self.store = store
        self.setup = None  # Gtk.PrintSetup só é reutilizado durante a sessão.
        self.dialog = Gtk.PrintDialog(title='Imprimir comprovante')
        self.set_paper(int(store.get('width', '80')))
        settings = store.get('print_settings')
        if settings:
            from gi.repository import GLib
            try:
                key = GLib.KeyFile()
                key.load_from_data(settings, len(settings.encode()), GLib.KeyFileFlags.NONE)
                self.dialog.set_print_settings(Gtk.PrintSettings.new_from_key_file(key, 'Print Settings'))
            except GLib.Error:
                pass

    def set_paper(self, width_mm, height_mm=200):
        paper = self.Gtk.PaperSize.new_custom('caixa-thermal', f'Bobina {width_mm} mm', width_mm, height_mm, self.Gtk.Unit.MM)
        page = self.Gtk.PageSetup()
        page.set_paper_size(paper)
        for side in ('top', 'bottom', 'left', 'right'):
            getattr(page, 'set_' + side + '_margin')(0, self.Gtk.Unit.MM)
        self.dialog.set_page_setup(page)
        self.setup = None

    def configure(self, parent, callback):
        from gi.repository import GLib
        def done(dialog, result):
            try:
                self.setup = dialog.setup_finish(result)
                settings = self.setup.get_print_settings()
                self.dialog.set_print_settings(settings)
                key = GLib.KeyFile()
                settings.to_key_file(key, 'Print Settings')
                self.store.configure(print_settings=key.to_data()[0])
                callback(None)
            except Exception as error:
                callback(error)
        self.dialog.setup(parent, None, done)

    @staticmethod
    def _background(action, callback):
        from gi.repository import GLib

        def run():
            try:
                result, error = action(), None
            except (OSError, ValueError) as exc:
                result, error = None, exc
            GLib.idle_add(callback, result, error)

        Thread(target=run, daemon=True).start()

    def detect(self, callback):
        self._background(lambda: Cups().queues(), callback)

    def print_receipt(self, parent, sale, pdf_path, callback, choice=None, cut_enabled=None):
        if choice is None:
            choice = self.store.get('local_printer', 'auto')
        if choice == 'system':
            self.print_pdf(parent, pdf_path(), callback)
            return

        if cut_enabled is None:
            cut_enabled = self.store.get('auto_cut', '1') == '1'
        title = 'Bipe — teste' if not sale['id'] else f"Bipe — venda {sale['id']:06d}"

        def submit():
            try:
                cups = Cups()
                queues = cups.queues()
            except OSError:
                if choice == 'auto':
                    return None
                raise
            queue = select_queue(queues, choice)
            return cups.submit(queue, sale, title, cut_enabled) if queue else None

        def done(job, error):
            if error or job:
                callback(error)
                return
            try:
                self.print_pdf(parent, pdf_path(), callback)
            except Exception as exc:
                callback(exc)

        self._background(submit, done)

    def print_pdf(self, parent, path, callback):
        from gi.repository import Gio
        def done(dialog, result):
            try:
                dialog.print_file_finish(result)
                callback(None)
            except Exception as error:
                self.setup = None
                callback(error)
        self.dialog.print_file(parent, self.setup, Gio.File.new_for_path(str(path)), None, done)
