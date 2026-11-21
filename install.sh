#!/usr/bin/env bash
# Instala teveo como servicio de usuario (systemd --user). Desinstalar: ./install.sh --uninstall
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT="$HOME/.config/systemd/user/teveo.service"
DESKTOP="$HOME/.local/share/applications/es.teveo.Monitor.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now teveo.service 2>/dev/null || true
  rm -f "$UNIT" "$DESKTOP"
  systemctl --user daemon-reload
  echo "teveo desinstalado."; exit 0
fi

mkdir -p "$(dirname "$UNIT")" "$(dirname "$DESKTOP")"
sed "s|@PROJECT_DIR@|$DIR|" "$DIR/systemd/teveo.service.in" > "$UNIT"
cp "$DIR/data/es.teveo.Monitor.desktop.in" "$DESKTOP"
systemctl --user daemon-reload
systemctl --user enable --now teveo.service
echo "teveo instalado y en marcha. Estado: systemctl --user status teveo"
