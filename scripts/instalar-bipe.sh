#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Executar como o usuário que vai operar o caixa; sudo só para tarefas do sistema.
set -eu
export LC_ALL=C

fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }
mode=${1:-}
case "$mode" in
    '') ;;
    --so-impressora|--verificar) ;;
    --help) printf '%s\n' 'Uso: sh instalar-bipe.sh [--so-impressora | --verificar]' 'Sem opção: configura a POS-80 e instala o Flatpak ao lado do script.'; exit 0 ;;
    *) fail 'Use --help para ver as opções.' ;;
esac
[ "$#" -le 1 ] || fail 'Use apenas uma opção.'
[ "$(uname -s)" = Linux ] || fail 'O instalador é para Linux.'
if [ "$mode" = '' ]; then
    [ "$(uname -m)" = x86_64 ] || fail 'Este pacote Flatpak é para Linux x86_64. Use --so-impressora para configurar somente a fila.'
    [ "$(id -u)" != 0 ] || fail 'Execute sem sudo. O instalador pedirá autorização apenas quando necessário.'
    folder=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    bundle="$folder/Bipe.flatpak"
    [ -r "$bundle" ] || fail 'Coloque Bipe.flatpak na mesma pasta do instalador.'
    if [ -f "$folder/SHA256SUMS" ]; then
        (cd "$folder" && sha256sum -c SHA256SUMS)
    fi
fi

model='drv:///cupsfilters.drv/textonly.ppd'
server='/run/cups/cups.sock'
queue='POS-80'
models() { lpinfo -h "$server" -m | awk -v model="$model" '$1 == model {print $1}'; }
admin() {
    if [ "$(id -u)" = 0 ]; then "$@"
    else
        command -v sudo >/dev/null 2>&1 || fail 'A configuração precisa de um administrador com sudo.'
        sudo -- "$@"
    fi
}
install_packages() {
    [ "$mode" != --verificar ] || fail 'CUPS, o driver de texto ou o Flatpak não está disponível.'
    if command -v dnf >/dev/null 2>&1; then
        admin dnf install cups cups-filters "$@"
    elif command -v apt-get >/dev/null 2>&1; then
        admin apt-get install cups cups-client cups-filters "$@"
    else
        fail 'Instale CUPS, cups-filters e, para o aplicativo, Flatpak pelo gerenciador da sua distribuição. Depois execute novamente.'
    fi
}

missing=''
if [ "$mode" = '' ] && ! command -v flatpak >/dev/null 2>&1; then missing=flatpak; fi
if ! command -v lpinfo >/dev/null 2>&1 || ! command -v lpstat >/dev/null 2>&1 || ! command -v lpadmin >/dev/null 2>&1 || ! command -v lpoptions >/dev/null 2>&1 || [ -n "$missing" ]; then
    if [ -n "$missing" ]; then install_packages "$missing"; else install_packages; fi
fi
if ! lpstat -h "$server" -r >/dev/null 2>&1; then
    [ "$mode" != --verificar ] || fail 'O CUPS local não está respondendo.'
    command -v systemctl >/dev/null 2>&1 || fail 'Inicie o CUPS da sua distribuição e execute novamente.'
    admin systemctl enable --now cups.socket
fi

devices=$(lpinfo -h "$server" --include-schemes usb --timeout 8 -v) || fail 'Não foi possível consultar os dispositivos USB do CUPS.'
uri=$(printf '%s\n' "$devices" | awk '$1 == "direct" && tolower($2) ~ /^usb:\/\/[^/]+\/pos(-|%20)?80([?]|$)/ {print $2}' | sort -u)
[ -n "$uri" ] || fail 'A POS-80 não foi encontrada. Ligue a impressora, conecte o cabo USB e execute novamente.'
case "$uri" in
    *'
'*) fail 'Mais de uma POS-80 conectada. Deixe ligada apenas a que vai ser usada neste caixa.' ;;
esac

queues=$(lpstat -h "$server" -v) || fail 'Não foi possível consultar as filas do CUPS.'
existing=$(printf '%s\n' "$queues" | awk '$1 == "device" && $2 == "for" && $3 == "POS-80:" {print $4}')
if [ -n "$existing" ]; then
    [ "$existing" = "$uri" ] || fail 'Já existe uma fila POS-80 para outro dispositivo. Ela foi preservada.'
    options=$(lpoptions -h "$server" -p "$queue") || fail 'Não foi possível consultar a fila POS-80 existente.'
    case "$options" in
        *"printer-make-and-model='Generic Text-Only Printer'"*) printf '%s\n' 'POS-80: fila de texto já configurada. Nenhuma alteração na fila.' ;;
        *) fail 'A fila POS-80 existente usa outro driver e foi preservada. Revise-a nas configurações de impressoras antes de executar novamente.' ;;
    esac
    case "$options" in
        *printer-state=5*|*printer-is-accepting-jobs=false*) fail 'A fila POS-80 está pausada ou rejeitando trabalhos. Reative-a nas configurações do Linux.' ;;
    esac
else
    other=$(printf '%s\n' "$queues" | awk -v uri="$uri" '$1 == "device" && $2 == "for" && $4 == uri {print $3}')
    [ -z "$other" ] || fail "Esta impressora já está cadastrada na fila ${other%:}. A fila foi preservada."
    [ "$mode" != --verificar ] || fail 'POS-80 encontrada via USB, mas ainda não há uma fila para ela.'
    if [ -z "$(models)" ]; then install_packages; fi
    [ "$(models)" = "$model" ] || fail 'O driver Generic Text-Only Printer não está disponível neste CUPS.'
    printf '%s\n' 'Configurando a fila local POS-80 (80 mm, texto contínuo)…'
    admin lpadmin -h "$server" -p "$queue" -v "$uri" -m "$model" -E \
        -o printer-is-shared=false -o job-sheets-default=none,none \
        -o Pagination=False -o SendFF=False -o PrinterEncoding=ASCII \
        -o page-left=0 -o page-right=0 -o page-top=0 -o page-bottom=0
    lpstat -h "$server" -p "$queue"
fi

if [ "$mode" = '' ]; then
    runtime='org.gnome.Platform/x86_64/50'
    if ! flatpak info --user "$runtime" >/dev/null 2>&1; then
        flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
        flatpak install --user --noninteractive flathub "$runtime"
    fi
    flatpak install --user --noninteractive "$bundle"
    if [ -f "$HOME/.var/app/io.github.caixasimples.CaixaSimples/data/io.github.caixasimples.CaixaSimples/caixa.sqlite3" ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            if command -v dnf >/dev/null 2>&1; then admin dnf install python3
            elif command -v apt-get >/dev/null 2>&1; then admin apt-get install python3
            else fail 'Instale Python 3 para migrar os dados da versão anterior.'
            fi
        fi
        python3 "$folder/migrar-bipe.py"
    fi
    printf '%s\n' 'Pronto. Abra Bipe pelo menu de aplicativos. Em Preferências → Impressora, deixe Detectar térmica automaticamente.'
fi
