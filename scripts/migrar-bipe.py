#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migração local entre os dois identificadores Flatpak do Bipe."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

OLD_ID = 'io.github.caixasimples.CaixaSimples'
NEW_ID = 'io.github.ricardo_pompeu.Bipe'


def migrate(root):
    source = root / OLD_ID / 'data' / OLD_ID / 'caixa.sqlite3'
    target = root / NEW_ID / 'data' / NEW_ID / 'caixa.sqlite3'
    if not source.is_file():
        return 'Nenhum banco da versão anterior encontrado.'
    if target.exists():
        return 'O Bipe já tem um banco próprio. Ele foi preservado; use Exportar e Restaurar backup se precisar trocar de banco.'
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as work:
        temp = Path(work) / 'migração.sqlite3'
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as old:
            with closing(sqlite3.connect(temp)) as new:
                old.backup(new)
                if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('A cópia do banco não passou na verificação.')
                counts = [new.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                          for table in ('products', 'sales', 'settings')]
        temp.chmod(0o600)
        os.link(temp, target)  # Publica a cópia apenas se o destino ainda não existe.
    return f'Dados migrados: {counts[0]} produtos, {counts[1]} vendas e {counts[2]} preferências. O original foi preservado.'


def main():
    root = Path.home() / '.var' / 'app'
    source = root / OLD_ID / 'data' / OLD_ID / 'caixa.sqlite3'
    if source.is_file():
        running = subprocess.check_output(['flatpak', 'ps', '--columns=application'], text=True).split()
        if OLD_ID in running or NEW_ID in running:
            raise SystemExit('Feche as duas versões do Bipe antes de migrar os dados.')
    try:
        print(migrate(root))
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f'Migração não concluída: {exc}') from exc


if __name__ == '__main__':
    main()
