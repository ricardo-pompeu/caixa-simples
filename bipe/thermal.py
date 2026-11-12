# SPDX-License-Identifier: GPL-3.0-or-later
"""Impressão de texto em filas térmicas locais já configuradas no CUPS."""
from contextlib import contextmanager
import ctypes as c
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import tempfile
import textwrap
import unicodedata
from .core import money


@dataclass(frozen=True)
class Queue:
    name: str
    model: str
    width: int
    ready: bool
    cutter: bool = False


def text_queue(name, options):
    model = options.get('printer-make-and-model', '')
    if not re.search(r'text[\s-]*only', model, re.I):
        return None
    media = options.get('media', '')
    match = (re.search(r'(?<!\d)(58|80)(?:mm|x\d+(?:\.\d+)?mm)', media, re.I)
             or re.search(r'(?<![a-z0-9])(?:POS|XP|THERMAL)[ _-]*(58|80)(?!\d)', name, re.I)
             or re.search(r'(?<!\d)(58|80)\s*mm\b', name, re.I))
    if not match:
        return None
    ready = options.get('printer-state') != '5' and options.get('printer-is-accepting-jobs') != 'false'
    # Somente o perfil USB POS-80 conhecido usa comandos ESC/POS.
    cutter = int(match[1]) == 80 and bool(re.match(
        r'^usb://[^/]+/pos(?:-|%20)?80(?:[?]|$)', options.get('device-uri', ''), re.I))
    return Queue(name, model, int(match[1]), ready, cutter)


def select_queue(queues, choice):
    if choice == 'system':
        return None
    if choice != 'auto':
        match = next((q for q in queues if q.name == choice), None)
        if match is None:
            raise ValueError(f'A impressora {choice} não está disponível. Confira a conexão e a fila nas configurações do Linux.')
        return match
    if len(queues) > 1:
        raise ValueError('Há mais de uma térmica disponível. Escolha uma em Preferências → Impressora.')
    return queues[0] if queues else None


def ascii_text(line):
    line = line.replace('×', 'x').replace('—', '-')
    safe = ''.join(' ' if unicodedata.category(ch).startswith('C') else ch for ch in line)
    safe = unicodedata.normalize('NFKD', safe)
    return ''.join(ch for ch in safe if not unicodedata.combining(ch)).encode('ascii', 'replace').decode()


def thermal_lines(sale, columns):
    rule = '-' * columns
    lines = []

    def wrapped(text):
        return textwrap.wrap(ascii_text(text), columns) or ['']

    def center(text):
        lines.extend(line.center(columns).rstrip() for line in wrapped(text))

    def pair(left, right):
        left, right = ascii_text(left), ascii_text(right)
        gap = columns - len(left) - len(right)
        if gap >= 1:
            lines.append(left + ' ' * gap + right)
        else:
            lines.extend(wrapped(left))
            lines.append(right.rjust(columns))

    center(sale['store'])
    center('COMPROVANTE NÃO FISCAL')
    lines.append(datetime.fromisoformat(sale['created']).strftime('%d/%m/%Y %H:%M'))
    lines.append(f"Venda: {sale['id']:06d}" if sale['id'] else 'Teste de impressao - sem venda')
    lines.append(rule)
    for item in sale['items']:
        lines.extend(wrapped(f"{item['quantity']}x {item['name']}"))
        pair(f"{money(item['price'])} un.", money(item['price'] * item['quantity']))
    lines.append(rule)
    pair('TOTAL', money(sale['total']))
    pair('Pagamento', sale['payment'])
    if sale['received'] is not None:
        pair('Recebido', money(sale['received']))
        pair('Troco', money(sale['change_value']))
    if sale['footer']:
        lines.append(rule)
        center(sale['footer'])
    return lines


def thermal_payload(sale, queue, cut_enabled=True):
    columns = {58: 32, 80: 42}[queue.width]
    lines = thermal_lines(sale, columns)
    if queue.cutter and cut_enabled:
        # Reinicia o modo, espaça em 24 pontos e deixa margem à esquerda.
        # GS V 66 pede avanço até a lâmina mais 48 unidades, seguido de corte.
        # Validado na POS-80 USB: LF em branco seguido de corte imediato não bastava.
        body = '\n'.join('  ' + line for line in lines).encode('ascii')
        return b'\x1b@\x1b3\x18' + body + b'\n\x1dVB\x30', 'application/vnd.cups-raw'
    return ('\n'.join(lines) + '\n\n\n\n').encode('ascii'), 'text/plain'


class _Option(c.Structure):
    _fields_ = [('name', c.c_char_p), ('value', c.c_char_p)]


class _Dest(c.Structure):
    _fields_ = [('name', c.c_char_p), ('instance', c.c_char_p), ('is_default', c.c_int),
                ('num_options', c.c_int), ('options', c.POINTER(_Option))]


class Cups:
    def __init__(self):
        self.lib = c.CDLL('libcups.so.2')
        signatures = {
            'httpConnect2': (c.c_void_p, [c.c_char_p, c.c_int, c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int, c.c_void_p]),
            'httpSetTimeout': (None, [c.c_void_p, c.c_double, c.c_void_p, c.c_void_p]),
            'httpClose': (None, [c.c_void_p]),
            'cupsGetDests2': (c.c_int, [c.c_void_p, c.POINTER(c.POINTER(_Dest))]),
            'cupsFreeDests': (None, [c.c_int, c.POINTER(_Dest)]),
            'cupsPrintFile2': (c.c_int, [c.c_void_p, c.c_char_p, c.c_char_p, c.c_char_p, c.c_int, c.POINTER(_Option)]),
            'cupsLastErrorString': (c.c_char_p, []),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args

    @contextmanager
    def connection(self):
        # Só o soquete local (CUPS_SERVER aponta para o soquete montado no Flatpak).
        socket = os.environ.get('CUPS_SERVER', '')
        if not socket.startswith('/'):
            socket = '/run/cups/cups.sock'
        http = self.lib.httpConnect2(os.fsencode(socket), 631, None, 0, 0, 1, 1500, None)
        if not http:
            raise OSError('O serviço local de impressão não está acessível.')
        try:
            self.lib.httpSetTimeout(http, 4.0, None, None)
            yield http
        finally:
            self.lib.httpClose(http)

    def queues(self):
        with self.connection() as http:
            dests = c.POINTER(_Dest)()
            count = self.lib.cupsGetDests2(http, c.byref(dests))
            try:
                queues = []
                for dest in dests[:count]:
                    if dest.instance:
                        continue
                    options = {o.name.decode(): o.value.decode(errors='replace') for o in dest.options[:dest.num_options]}
                    queue = text_queue(dest.name.decode(errors='replace'), options)
                    if queue is not None:
                        queues.append(queue)
                return sorted(queues, key=lambda q: q.name)
            finally:
                self.lib.cupsFreeDests(count, dests)

    def submit(self, queue, sale, title, cut_enabled=True):
        if not queue.ready:
            raise ValueError(f'A impressora {queue.name} está pausada ou não aceita trabalhos. Verifique a fila no Linux.')
        # Opções por trabalho: nenhum ajuste permanente na fila do sistema.
        payload, format = thermal_payload(sale, queue, cut_enabled)
        options = {
            'document-format': format, 'Pagination': 'False', 'SendFF': 'False',
            'page-left': '0', 'page-right': '0', 'page-top': '0', 'page-bottom': '0',
            'job-sheets': 'none',
        }
        if format == 'application/vnd.cups-raw':
            options = {'raw': 'true', 'job-sheets': 'none'}
        args = (_Option * len(options))(*(_Option(k.encode(), v.encode()) for k, v in options.items()))
        with tempfile.TemporaryDirectory(prefix='caixa-impressao-') as folder:
            path = Path(folder) / 'comprovante'
            path.write_bytes(payload)
            with self.connection() as http:
                job = self.lib.cupsPrintFile2(http, queue.name.encode(), os.fsencode(path), title.encode(), len(args), args)
                if job <= 0:
                    detail = self.lib.cupsLastErrorString()
                    raise ValueError(f'Não foi possível enviar para {queue.name}: {(detail or b"CUPS").decode(errors="replace")}')
                return job
