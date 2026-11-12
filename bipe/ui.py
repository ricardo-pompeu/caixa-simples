# SPDX-License-Identifier: GPL-3.0-or-later
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
import logging
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib
from . import APP_ID, VERSION
from .core import Store, Cart, money, parse_money, change_due
from .receipt import Printer, render_pdf, receipt_lines


def box(spacing=12, horizontal=False):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL, spacing=spacing)


def margins(widget, amount=18):
    for side in ('top', 'bottom', 'start', 'end'):
        getattr(widget, 'set_margin_' + side)(amount)
    return widget


def label(text, style=None, **kwargs):
    widget = Gtk.Label(label=text, **kwargs)
    if style:
        widget.add_css_class(style)
    return widget


def button(text, callback, style=None, icon=None):
    widget = Gtk.Button(label=text) if not icon else Gtk.Button(icon_name=icon, tooltip_text=text)
    if style:
        widget.add_css_class(style)
    widget.connect('clicked', lambda *_: callback())
    return widget


def clear_list(widget):
    while widget.get_first_child():
        widget.remove(widget.get_first_child())


def scroll(child):
    return Gtk.ScrolledWindow(child=child, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)


class Window(Adw.ApplicationWindow):
    def __init__(self, app, store):
        super().__init__(application=app, title='Bipe', default_width=850, default_height=720)
        self.store = store
        self.cart = Cart()
        self.printer = Printer(store)
        self.checkout_open = False
        self.allow_close = False
        self.stack = Adw.ViewStack()
        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)
        layout = box(0)
        self.toast.set_child(layout)
        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        menu = Gio.Menu()
        for title, action, handler in [('Vendas recentes', 'history', self.history), ('Preferências', 'preferences', self.preferences), ('Exportar backup', 'export', self.export_backup), ('Restaurar backup', 'restore', self.restore_backup), ('Sobre Bipe', 'about', self.about)]:
            act = Gio.SimpleAction.new(action, None)
            act.connect('activate', lambda *_, h=handler: h())
            self.add_action(act)
            menu.append(title, 'win.' + action)
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu, tooltip_text='Menu principal'))
        layout.append(header)
        layout.append(self.stack)
        self.stack.set_vexpand(True)
        self.build_sale()
        self.build_products()
        self.build_closing()
        self.stack.connect('notify::visible-child-name', self.page_changed)
        self.connect('close-request', self.close_requested)
        GLib.idle_add(self.focus_scan)
        self.auto_backup()
        self.backup_timer = GLib.timeout_add_seconds(900, self.auto_backup)
        self.closing_timer = GLib.timeout_add_seconds(60, self.closing_tick)

    def page_changed(self, *_):
        if self.stack.get_visible_child_name() == 'sell':
            self.focus_scan()
        elif self.stack.get_visible_child_name() == 'closing':
            self.refresh_closing()

    def notify(self, text):
        self.toast.add_toast(Adw.Toast(title=text))

    def error(self, text, error=None):
        if error:
            logging.error('%s: %s', text, error)
        dialog = Adw.AlertDialog(heading=text, body=str(error) if isinstance(error, ValueError) else 'Seus dados foram preservados. Verifique o arquivo ou tente novamente.')
        dialog.add_response('ok', 'Entendi')
        dialog.present(self)

    def confirm(self, heading, body, action, callback):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response('cancel', 'Voltar')
        dialog.add_response('yes', action)
        dialog.set_response_appearance('yes', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', lambda _, response: callback() if response == 'yes' else None)
        dialog.present(self)

    def build_sale(self):
        content = margins(box(16), 24)
        clamp = Adw.Clamp(maximum_size=850, child=content)
        content.append(label('Nova venda', 'title-1', xalign=0))
        self.scan = Gtk.Entry(placeholder_text='Escaneie ou digite o código e pressione Enter', hexpand=True)
        self.scan.update_property([Gtk.AccessibleProperty.LABEL], ['Código de barras para adicionar à venda'])
        self.scan.connect('activate', self.scanned)
        content.append(self.scan)
        content.append(label('Pronto para receber produtos', 'dim-label', xalign=0))
        self.cart_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.cart_list.add_css_class('boxed-list')
        self.empty_cart = Adw.StatusPage(icon_name='document-new-symbolic', title='Comece uma venda', description='Passe o primeiro produto no leitor.\nSe ele for novo, você poderá cadastrá-lo na hora.')
        self.cart_views = Gtk.Stack(vexpand=True)
        self.cart_views.add_named(self.empty_cart, 'empty')
        self.cart_views.add_named(scroll(self.cart_list), 'items')
        content.append(self.cart_views)
        totals = box(horizontal=True)
        totals.append(label('Total', 'title-3', hexpand=True, xalign=0))
        self.total = label(money(0), 'title-1')
        totals.append(self.total)
        content.append(totals)
        self.finish = button('Finalizar venda', self.checkout, 'suggested-action')
        self.finish.add_css_class('pill')
        self.finish.set_size_request(-1, 48)
        self.finish.set_sensitive(False)
        content.append(self.finish)
        self.cancel = button('Cancelar venda', self.cancel_sale, 'flat')
        self.cancel.set_sensitive(False)
        content.append(self.cancel)
        self.stack.add_titled_with_icon(clamp, 'sell', 'Vender', 'document-new-symbolic')

    def build_products(self):
        content = margins(box(16), 24)
        top = box(horizontal=True)
        self.search = Gtk.SearchEntry(placeholder_text='Pesquisar nome ou código', hexpand=True)
        self.search.connect('search-changed', lambda *_: self.refresh_products())
        top.append(self.search)
        top.append(button('Adicionar produto', lambda: self.product_dialog(), 'suggested-action'))
        content.append(top)
        self.product_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.product_list.add_css_class('boxed-list')
        self.products_empty = Adw.StatusPage(icon_name='view-list-symbolic', title='Seus produtos ficam aqui', description='Cadastre somente código, nome e preço.\nVocê também pode cadastrar durante uma venda.')
        self.product_views = Gtk.Stack(vexpand=True)
        self.product_views.add_named(self.products_empty, 'empty')
        self.product_views.add_named(scroll(self.product_list), 'list')
        content.append(self.product_views)
        self.stack.add_titled_with_icon(Adw.Clamp(maximum_size=850, child=content), 'products', 'Produtos', 'view-list-symbolic')
        self.refresh_products()

    def refresh_products(self):
        clear_list(self.product_list)
        products = self.store.products(self.search.get_text())
        self.products_empty.set_title('Nenhum produto encontrado' if self.search.get_text() else 'Seus produtos ficam aqui')
        self.product_views.set_visible_child_name('list' if products else 'empty')
        for product in products:
            row = Adw.ActionRow(title=product.name, subtitle=product.barcode)
            row.set_use_markup(False)
            row.add_suffix(label(money(product.price)))
            edit = button('Editar produto', lambda p=product: self.product_dialog(product=p), icon='document-edit-symbolic')
            edit.set_valign(Gtk.Align.CENTER)
            row.add_suffix(edit)
            self.product_list.append(row)

    def focus_scan(self):
        if not self.checkout_open and self.stack.get_visible_child_name() == 'sell':
            self.scan.grab_focus()
        return False

    def scanned(self, entry):
        code = entry.get_text().strip()
        if not code:
            return
        try:
            product = self.store.product(code)
            entry.set_text('')
            if product:
                self.add_product(product)
            else:
                self.product_dialog(barcode=code, add=True)
        except Exception as error:
            self.error('Não foi possível adicionar o produto', error)

    def add_product(self, product):
        self.cart.add(product)
        self.refresh_cart()
        self.notify(product.name + ' adicionado')
        self.focus_scan()

    def refresh_cart(self):
        clear_list(self.cart_list)
        for item in self.cart.items.values():
            row = Adw.ActionRow(title=item.name, subtitle=f'{money(item.price)} un. · Subtotal {money(item.subtotal)}')
            row.set_use_markup(False)
            controls = box(6, horizontal=True)
            controls.set_valign(Gtk.Align.CENTER)
            controls.append(button('Diminuir quantidade de ' + item.name, lambda i=item: self.change_quantity(i.product_id, -1), icon='list-remove-symbolic'))
            controls.append(label(str(item.quantity), width_chars=3))
            controls.append(button('Aumentar quantidade de ' + item.name, lambda i=item: self.change_quantity(i.product_id, 1), icon='list-add-symbolic'))
            controls.append(button('Remover ' + item.name, lambda i=item: self.remove_item(i.product_id), 'flat', 'user-trash-symbolic'))
            row.add_suffix(controls)
            self.cart_list.append(row)
        self.cart_views.set_visible_child_name('items' if self.cart.items else 'empty')
        self.total.set_label(money(self.cart.total))
        self.finish.set_sensitive(bool(self.cart.items))
        self.cancel.set_sensitive(bool(self.cart.items))

    def change_quantity(self, product_id, delta):
        try:
            self.cart.change(product_id, delta)
            self.refresh_cart()
            self.focus_scan()
        except ValueError as error:
            self.notify(str(error))

    def remove_item(self, product_id):
        self.cart.items.pop(product_id, None)
        self.refresh_cart()
        self.focus_scan()

    def cancel_sale(self):
        self.confirm('Cancelar esta venda?', 'Os produtos desta compra serão removidos.', 'Cancelar venda', self.clear_cart)

    def clear_cart(self):
        self.cart.clear()
        self.refresh_cart()
        self.focus_scan()

    def form_dialog(self, title, width=460):
        dialog = Adw.Dialog(title=title, content_width=width)
        body = box(0)
        header = Adw.HeaderBar()
        body.append(header)
        inner = margins(box(18), 24)
        body.append(inner)
        dialog.set_child(body)
        return dialog, inner

    def product_dialog(self, barcode='', product=None, add=False):
        dialog, inner = self.form_dialog('Editar produto' if product else 'Cadastrar produto')
        group = Adw.PreferencesGroup()
        code = Adw.EntryRow(title='Código de barras', text=product.barcode if product else barcode)
        name = Adw.EntryRow(title='Nome do produto', text=product.name if product else '')
        price = Adw.EntryRow(title='Preço de venda (R$)', text=f'{product.price / 100:.2f}'.replace('.', ',') if product else '')
        price.set_input_purpose(Gtk.InputPurpose.NUMBER)
        for entry in (code, name, price):
            group.add(entry)
        inner.append(group)
        error_label = label('', 'error', wrap=True)
        inner.append(error_label)
        def save():
            try:
                saved = self.store.save_product(code.get_text(), name.get_text(), parse_money(price.get_text()), product.id if product else None)
                self.refresh_products()
                if add:
                    self.add_product(saved)
                else:
                    self.notify('Produto salvo')
                dialog.close()
            except (ValueError, sqlite3.Error) as error:
                error_label.set_label(str(error) if isinstance(error, ValueError) else 'Não foi possível salvar. Verifique o espaço disponível e tente novamente.')
        inner.append(button('Salvar e adicionar' if add else 'Salvar', save, 'suggested-action'))
        code.connect('entry-activated', lambda *_: name.grab_focus())
        name.connect('entry-activated', lambda *_: price.grab_focus())
        price.connect('entry-activated', lambda *_: save())
        dialog.connect('closed', lambda *_: self.focus_scan())
        dialog.present(self)
        (name if barcode else code).grab_focus()

    def checkout(self):
        if self.checkout_open or not self.cart.items:
            return
        self.checkout_open = True
        dialog, inner = self.form_dialog('Finalizar venda')
        inner.append(label('Total: ' + money(self.cart.total), 'title-1'))
        group = Adw.PreferencesGroup()
        method = Adw.ComboRow(title='Pagamento', model=Gtk.StringList.new(['Dinheiro', 'PIX', 'Cartão']))
        received = Adw.EntryRow(title='Recebido (R$, opcional)')
        received.set_input_purpose(Gtk.InputPurpose.NUMBER)
        group.add(method)
        group.add(received)
        inner.append(group)
        change = label('Troco: ' + money(0), 'title-3')
        inner.append(change)
        warning = label('', 'error', wrap=True)
        inner.append(warning)
        done = button('Concluir e imprimir', lambda: complete(), 'suggested-action')
        done.set_size_request(-1, 48)
        inner.append(done)
        inner.append(label('A venda será salva antes da impressão.\nVocê também poderá salvar o comprovante em PDF.', 'dim-label', wrap=True))
        def update(*_):
            cash = method.get_selected() == 0
            received.set_visible(cash)
            change.set_visible(cash)
            try:
                value = parse_money(received.get_text()) if cash and received.get_text().strip() else None
                change.set_label('Troco: ' + money(change_due(self.cart.total, value)))
                warning.set_label('')
                done.set_sensitive(True)
            except ValueError as error:
                warning.set_label(str(error))
                done.set_sensitive(False)
        received.connect('changed', update)
        method.connect('notify::selected', update)
        committed = False
        def complete():
            nonlocal committed
            if committed:
                return
            done.set_sensitive(False)
            try:
                payment = ['Dinheiro', 'PIX', 'Cartão'][method.get_selected()]
                value = parse_money(received.get_text()) if payment == 'Dinheiro' and received.get_text().strip() else None
                sale_id = self.store.checkout(self.cart, payment, value)
            except (ValueError, sqlite3.Error) as error:
                warning.set_label(str(error) if isinstance(error, ValueError) else 'Não foi possível salvar a venda. Tente novamente; a compra continua aqui.')
                done.set_sensitive(True)
                return
            committed = True
            self.cart.clear()
            self.refresh_cart()
            dialog.close()
            self.refresh_closing()
            self.notify(f'Venda {sale_id:06d} salva')
            self.show_receipt(sale_id, print_now=True)
        def closed(*_):
            self.checkout_open = False
            self.focus_scan()
        dialog.connect('closed', closed)
        dialog.present(self)

    def receipt_path(self, sale):
        # Cache regenerável; o registro permanente é a venda no banco.
        path = Path(GLib.get_user_cache_dir()) / APP_ID / f"venda-{sale['id']:06d}.pdf"
        return render_pdf(sale, path, int(self.store.get('width', '80')))

    def show_receipt(self, sale_id, print_now=False):
        sale = self.store.sale(sale_id)
        dialog, inner = self.form_dialog(f'Venda {sale_id:06d}', 520)
        text = label('\n'.join(receipt_lines(sale)), selectable=True, wrap=True, xalign=0)
        pane = scroll(text)
        pane.set_min_content_height(240)
        pane.set_max_content_height(440)
        inner.append(pane)
        status = label('Venda salva. Você pode imprimir novamente a qualquer momento.', 'dim-label', wrap=True)
        inner.append(status)
        actions = box(horizontal=True)
        inner.append(actions)
        def print_receipt():
            printing.set_sensitive(False)
            status.set_label('Preparando impressão…')
            def printed(error):
                printing.set_sensitive(True)
                status.set_label('A venda está salva. A impressão não foi concluída; tente novamente ou salve o PDF.' if error else 'Comprovante enviado ao sistema de impressão.')
                if error:
                    if isinstance(error, (ValueError, OSError)):
                        status.set_label(f'A venda está salva. {error}')
                    logging.warning('Impressão não concluída: %s', error)
            try:
                self.printer.print_receipt(self, sale, lambda: self.receipt_path(sale), printed)
            except Exception as error:
                printed(error)
        printing = button('Imprimir novamente' if not print_now else 'Imprimir', print_receipt, 'suggested-action')
        actions.append(printing)
        actions.append(button('Salvar PDF', lambda: self.save_pdf(sale)))
        actions.append(button('Visualizar PDF', lambda: self.preview_pdf(sale)))
        inner.append(button('Nova venda', dialog.close, 'flat'))
        dialog.present(self)
        if print_now:
            print_receipt()

    def preview_pdf(self, sale):
        try:
            path = self.receipt_path(sale)
            launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(path)))
            def launched(obj, result):
                try:
                    obj.launch_finish(result)
                except GLib.Error as error:
                    self.error('Não foi possível abrir o PDF', error)
            launcher.launch(self, None, launched)
        except Exception as error:
            self.error('Não foi possível gerar o comprovante', error)

    def choose_file(self, title, save, suggested, callback):
        chooser = Gtk.FileDialog(title=title)
        if suggested:
            chooser.set_initial_name(suggested)
        def chosen(obj, result):
            try:
                file = obj.save_finish(result) if save else obj.open_finish(result)
                callback(file)
            except GLib.Error as error:
                if not error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self.error('Não foi possível acessar o arquivo', error)
            except Exception as error:
                self.error('Não foi possível concluir a operação', error)
        if save:
            chooser.save(self, None, chosen)
        else:
            chooser.open(self, None, chosen)

    def save_pdf(self, sale):
        def save(file):
            source = Gio.File.new_for_path(str(self.receipt_path(sale)))
            source.copy(file, Gio.FileCopyFlags.OVERWRITE, None, None, None)
            self.notify('Comprovante PDF salvo')
        self.choose_file('Salvar comprovante', True, f"venda-{sale['id']:06d}.pdf", save)

    def history(self):
        dialog, inner = self.form_dialog('Vendas recentes', 540)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class('boxed-list')
        offset = 0
        def load():
            nonlocal offset
            sales = self.store.recent(limit=50, offset=offset)
            for sale in sales:
                date = datetime.fromisoformat(sale['created']).strftime('%d/%m/%Y às %H:%M')
                row = Adw.ActionRow(title=f"Venda {sale['id']:06d} · {money(sale['total'])}", subtitle=date, activatable=True)
                row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
                row.connect('activated', lambda _, i=sale['id']: self.show_receipt(i))
                rows.append(row)
            offset += len(sales)
            more.set_visible(len(sales) == 50)
            if offset == 0:
                inner.prepend(Adw.StatusPage(icon_name='document-open-recent-symbolic', title='Nenhuma venda ainda', description='As vendas concluídas aparecerão aqui.'))
        pane = scroll(rows)
        pane.set_min_content_height(320)
        inner.append(pane)
        more = button('Carregar mais vendas', load)
        inner.append(more)
        load()
        dialog.present(self)

    def build_closing(self):
        content = margins(box(20), 24)
        title = box(horizontal=True)
        title.append(label('Fechamento de caixa', 'title-1', xalign=0, hexpand=True))
        self.closing_day = datetime.now().date()
        self.closing_follow_today = True
        self.closing_date_button = button('Hoje', self.choose_closing_day)
        self.closing_date_button.set_tooltip_text('Consultar outro dia')
        title.append(self.closing_date_button)
        content.append(title)
        content.append(label('Confira os produtos vendidos no dia.', 'dim-label', xalign=0, wrap=True))
        totals = Adw.PreferencesGroup()
        content.append(totals)
        self.closing_sales = Adw.ActionRow(title='Unidades vendidas')
        self.closing_sales_value = label('', 'title-2')
        self.closing_sales.add_suffix(self.closing_sales_value)
        totals.add(self.closing_sales)
        self.closing_products = Adw.PreferencesGroup(title='Produtos mais vendidos', description='Quantidade de unidades vendidas no dia.')
        self.closing_product_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.closing_product_list.add_css_class('boxed-list')
        self.closing_products.add(self.closing_product_list)
        content.append(self.closing_products)
        pane = scroll(Adw.Clamp(maximum_size=850, child=content))
        self.stack.add_titled_with_icon(pane, 'closing', 'Fechamento', 'document-open-recent-symbolic')
        self.refresh_closing()

    def closing_tick(self):
        if self.stack.get_visible_child_name() == 'closing':
            self.refresh_closing()
        return True

    def choose_closing_day(self):
        dialog, inner = self.form_dialog('Consultar outro dia', 360)
        calendar = Gtk.Calendar()
        day = self.closing_day
        calendar.select_day(GLib.DateTime.new_local(day.year, day.month, day.day, 12, 0, 0))
        inner.append(calendar)
        def apply(today=False):
            if today:
                self.closing_day = datetime.now().date()
            else:
                self.closing_day = datetime.fromisoformat(calendar.get_date().format('%Y-%m-%d')).date()
            self.closing_follow_today = self.closing_day == datetime.now().date()
            self.refresh_closing()
            dialog.close()
        inner.append(button('Ver este dia', apply, 'suggested-action'))
        inner.append(button('Voltar para hoje', lambda: apply(True), 'flat'))
        dialog.present(self)

    def refresh_closing(self):
        if not hasattr(self, 'closing_products'):
            return
        today = datetime.now().date()
        if self.closing_follow_today:
            self.closing_day = today
        day = self.closing_day
        self.closing_date_button.set_label('Hoje' if day == today else day.strftime('%d/%m/%Y'))
        summary = self.store.daily_summary(day.isoformat())
        self.closing_sales_value.set_label(str(summary['quantity']))
        kinds, sales = len(summary['products']), summary['sales_count']
        product_text = 'produto' if kinds == 1 else 'produtos diferentes'
        sale_text = 'venda' if sales == 1 else 'vendas'
        self.closing_sales.set_subtitle(f'{kinds} {product_text} · {sales} {sale_text}')
        clear_list(self.closing_product_list)
        if not summary['products']:
            empty = Adw.ActionRow(title='Nenhum produto vendido neste dia', subtitle='As vendas concluídas aparecerão aqui automaticamente.')
            self.closing_product_list.append(empty)
        for index, product in enumerate(summary['products'], 1):
            row = Adw.ActionRow(title=f"{index}. {product['name']}")
            row.set_use_markup(False)
            row.add_suffix(label(f"{product['quantity']} un."))
            self.closing_product_list.append(row)

    def preferences(self):
        dialog = Adw.PreferencesDialog(title='Preferências')
        page = Adw.PreferencesPage()
        dialog.add(page)
        group = Adw.PreferencesGroup(title='Estabelecimento')
        name = Adw.EntryRow(title='Nome da loja', text=self.store.get('store', 'Meu estabelecimento'))
        footer = Adw.EntryRow(title='Rodapé do comprovante (opcional)', text=self.store.get('footer', 'Obrigado pela preferência!'))
        group.add(name)
        group.add(footer)
        page.add(group)
        printer_group = Adw.PreferencesGroup(title='Impressora', description='O Bipe procura térmicas configuradas no Linux. A largura é detectada quando a fila informa ou identifica a bobina.')
        choices = ['auto', 'system']
        destination = Adw.ComboRow(title='Impressora dos comprovantes')
        printer_group.add(destination)
        detection = Adw.ActionRow(title='Impressoras locais')
        printer_group.add(detection)
        saved = self.store.get('local_printer', 'auto')

        def update_options(queues, preferred):
            labels = ['Detectar térmica automaticamente', 'Diálogo de impressão do sistema']
            choices[:] = ['auto', 'system']
            for queue in queues:
                choices.append(queue.name)
                labels.append(f'{queue.name} · {queue.width} mm' + ('' if queue.ready else ' · pausada'))
            if preferred not in choices:
                choices.append(preferred)
                labels.append(f'{preferred} · indisponível')
            destination.set_model(Gtk.StringList.new(labels))
            destination.set_selected(choices.index(preferred))

        def detect():
            detection.set_subtitle('Procurando…')
            refresh.set_sensitive(False)
            def detected(queues, error):
                refresh.set_sensitive(True)
                preferred = choices[destination.get_selected()]
                update_options(queues or [], preferred)
                if error:
                    detection.set_subtitle('Serviço de impressão local indisponível.')
                elif queues:
                    detection.set_subtitle(' · '.join(f'{q.name}: {q.width} mm, texto contínuo' for q in queues))
                else:
                    detection.set_subtitle('Nenhuma térmica de texto compatível encontrada. Confira as impressoras do Linux.')
            self.printer.detect(detected)

        update_options([], saved)
        refresh = button('Atualizar lista', detect)
        printer_group.add(refresh)
        cut = Adw.SwitchRow(title='Corte automático na POS-80', subtitle='Envia o comando de corte ao final do comprovante na POS-80 USB.', active=self.store.get('auto_cut', '1') == '1')
        printer_group.add(cut)
        width = Adw.ComboRow(title='Largura da bobina para PDF', model=Gtk.StringList.new(['58 mm', '80 mm']), selected=0 if self.store.get('width', '80') == '58' else 1)
        printer_group.add(width)
        printer_group.add(button('Configurar diálogo do sistema', lambda: self.printer.configure(self, lambda e: self.error('Impressora não configurada', e) if e else self.notify('Impressora selecionada'))))
        def test_print():
            sale = {'id': 0, 'created': datetime.now().astimezone().isoformat(), 'store': name.get_text() or 'Meu estabelecimento', 'footer': 'TESTE DE IMPRESSÃO — sem venda registrada', 'total': 750, 'payment': 'Dinheiro', 'received': 1000, 'change_value': 250, 'items': [{'name': 'Produto de teste', 'price': 750, 'quantity': 1}]}
            try:
                def test_pdf():
                    path = Path(GLib.get_user_cache_dir()) / APP_ID / 'teste.pdf'
                    return render_pdf(sale, path, 58 if width.get_selected() == 0 else 80)
                self.printer.print_receipt(self, sale, test_pdf, lambda e: self.error('Impressão não concluída', e) if e else self.notify('Teste enviado à fila de impressão'), choice=choices[destination.get_selected()], cut_enabled=cut.get_active())
            except Exception as error:
                self.error('Não foi possível imprimir o teste', error)
        printer_group.add(button('Testar impressão', test_print))
        page.add(printer_group)
        data = Adw.PreferencesGroup(title='Dados', description='Dados locais; cópias automáticas a cada 15 minutos e ao fechar. As dez cópias mais recentes são preservadas.')
        data.add(button('Exportar backup', self.export_backup))
        data.add(button('Restaurar backup', self.restore_backup))
        page.add(data)
        appearance = Adw.PreferencesGroup(title='Aparência', description='Segue o tema e as preferências de acessibilidade do GNOME.')
        page.add(appearance)
        def save():
            try:
                self.store.configure(store=name.get_text().strip()[:200] or 'Meu estabelecimento', footer=footer.get_text().strip()[:300], local_printer=choices[destination.get_selected()], auto_cut=int(cut.get_active()), width=58 if width.get_selected() == 0 else 80)
                self.printer.set_paper(58 if width.get_selected() == 0 else 80)
                self.notify('Preferências salvas')
                dialog.close()
            except sqlite3.Error as error:
                self.error('Não foi possível salvar as preferências', error)
        group.add(button('Salvar preferências', save, 'suggested-action'))
        dialog.present(self)
        detect()

    def export_backup(self):
        def export(file):
            path = file.get_path()
            if path is None:
                raise ValueError('Escolha uma pasta local para guardar o backup.')
            self.store.backup(path)
            self.notify('Backup exportado')
        self.choose_file('Exportar backup', True, 'bipe-' + datetime.now().strftime('%Y-%m-%d-%H%M%S') + '.sqlite3', export)

    def restore_backup(self):
        def selected(file):
            path = file.get_path()
            if not path:
                raise ValueError('Escolha um arquivo local de backup.')
            self.confirm('Restaurar este backup?', 'Os dados serão substituídos pelo backup. Uma cópia dos dados atuais será preservada. A venda em andamento será descartada.', 'Restaurar backup', lambda: restore(path))
        def restore(path):
            try:
                self.store.restore(path)
                self.printer = Printer(self.store)
                self.clear_cart()
                self.refresh_products()
                self.refresh_closing()
                self.notify('Backup restaurado')
            except Exception as error:
                self.error('Não foi possível restaurar o backup', error)
        self.choose_file('Restaurar backup', False, None, selected)

    def auto_backup(self):
        try:
            self.store.auto_backup()
        except (sqlite3.Error, OSError) as error:
            logging.error('Backup automático: %s', error)
            self.notify('Não foi possível criar o backup. Exporte uma cópia pelo menu.')
        return True

    def close_requested(self, *_):
        if self.allow_close:
            return False
        if self.cart.items:
            def discard():
                self.allow_close = True
                self.close()
            self.confirm('Fechar com uma venda em andamento?', 'Esta compra ainda não foi concluída. Os produtos desta venda serão descartados.', 'Descartar e fechar', discard)
            return True
        return False

    def about(self):
        Adw.AboutDialog(application_name='Bipe', application_icon=APP_ID, version=VERSION, developer_name='Colaboradores do Bipe', license_type=Gtk.License.GPL_3_0, comments='Um caixa simples, local e sem complicação.\nEmite comprovantes não fiscais.').present(self)


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.store = None

    def do_activate(self):
        if self.get_active_window():
            self.get_active_window().present()
            return
        path = Path(GLib.get_user_data_dir()) / APP_ID / 'caixa.sqlite3'
        try:
            if self.store:
                self.store.close()
                self.store = None
            self.store = Store(path)
        except Exception as error:
            logging.exception('Não foi possível abrir o banco')
            window = Adw.ApplicationWindow(application=self, title='Bipe', default_width=520, default_height=420)
            body = box()
            body.append(Adw.HeaderBar())
            page = Adw.StatusPage(title='Não foi possível abrir seus dados', icon_name='dialog-warning-symbolic', description='Os arquivos originais foram preservados. Você pode restaurar uma cópia de segurança ou tentar abrir novamente.')
            actions = box()
            def restore():
                chooser = Gtk.FileDialog(title='Selecionar backup para recuperação')
                def chosen(obj, result):
                    try:
                        source = obj.open_finish(result).get_path()
                        if not source:
                            raise ValueError('Escolha um arquivo local.')
                        with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as check:
                            Store.validate_backup(check)
                        confirm = Adw.AlertDialog(heading='Recuperar a partir deste backup?', body='O banco atual e seus arquivos auxiliares serão preservados antes da recuperação.')
                        confirm.add_response('cancel', 'Voltar')
                        confirm.add_response('restore', 'Recuperar dados')
                        confirm.set_close_response('cancel')
                        def confirmed(_, response):
                            if response != 'restore':
                                return
                            try:
                                import shutil
                                recovery = path.parent / ('dados-preservados-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                                recovery.mkdir(mode=0o700)
                                for suffix in ('', '-wal', '-shm'):
                                    original = Path(str(path) + suffix)
                                    if original.exists():
                                        shutil.move(str(original), recovery / original.name)
                                with closing(sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)) as source_db, closing(sqlite3.connect(path)) as target:
                                    source_db.backup(target)
                                window.destroy()
                                self.activate()
                            except Exception:
                                page.set_description('Não foi possível recuperar. Seus arquivos foram preservados. Verifique o espaço em disco e tente novamente.')
                        confirm.connect('response', confirmed)
                        confirm.present(window)
                    except Exception:
                        page.set_description('O arquivo selecionado não pôde ser aberto como backup válido. Seus dados continuam preservados.')
                chooser.open(window, None, chosen)
            actions.append(button('Restaurar backup', restore, 'suggested-action'))
            actions.append(button('Tentar novamente', lambda: (window.destroy(), self.activate())))
            page.set_child(actions)
            body.append(page)
            window.set_content(body)
            window.present()
            return
        Window(self, self.store).present()

    def do_shutdown(self):
        if self.store:
            try:
                self.store.auto_backup()
            except Exception:
                logging.exception('Backup ao encerrar')
            self.store.close()
        Adw.Application.do_shutdown(self)


def main():
    import sys
    logging.basicConfig(level=logging.WARNING)
    return Application().run(sys.argv)
