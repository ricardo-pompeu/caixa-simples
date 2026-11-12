#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Nome antigo, mantido para compatibilidade com instruções anteriores.
set -eu
folder=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$folder/instalar-bipe.sh" "$@"
