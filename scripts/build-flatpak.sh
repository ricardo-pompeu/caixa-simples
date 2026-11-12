#!/bin/sh
# Constrói o mesmo módulo do manifesto usando o SDK instalado, sem downloads.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work=${1:-/tmp/caixa-simples-flatpak-build}
repo=${2:-/tmp/caixa-simples-flatpak-repo}
flatpak build-init "$work" io.github.caixasimples.CaixaSimples org.gnome.Sdk org.gnome.Platform 50
flatpak build --filesystem="$root":ro "$work" sh -ec 'meson setup /tmp/caixa-meson "$1" --prefix=/app; meson test -C /tmp/caixa-meson --print-errorlogs; meson install -C /tmp/caixa-meson' sh "$root"
flatpak build-finish --socket=cups --share=ipc --socket=wayland --socket=fallback-x11 --device=dri --command=caixa-simples "$work"
flatpak build-export "$repo" "$work"
flatpak build-bundle "$repo" "$root/Bipe.flatpak" io.github.caixasimples.CaixaSimples
