#!/usr/bin/env bash
# Instala teveo como servicio de usuario (systemd --user) y como entrada del menú de aplicaciones.
# Desinstalar: ./install.sh --uninstall
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT="$HOME/.config/systemd/user/teveo.service"
APPS="$HOME/.local/share/applications"
DESKTOP="$APPS/es.teveo.Monitor.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/es.teveo.Monitor.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now teveo.service 2>/dev/null || true
  rm -f "$UNIT" "$DESKTOP" "$ICON"
  systemctl --user daemon-reload
  update-desktop-database "$APPS" 2>/dev/null || true
  gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
  echo "teveo desinstalado."; exit 0
fi

mkdir -p "$(dirname "$UNIT")" "$APPS" "$(dirname "$ICON")"
sed "s|@PROJECT_DIR@|$DIR|" "$DIR/systemd/teveo.service.in" > "$UNIT"
sed "s|@PROJECT_DIR@|$DIR|" "$DIR/data/es.teveo.Monitor.desktop.in" > "$DESKTOP"
cp "$DIR/teveo/recursos/icono.svg" "$ICON"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable teveo.service
systemctl --user restart teveo.service
echo "teveo instalado: servicio en marcha y entrada «teveo» en el menú de aplicaciones."
echo "Estado: systemctl --user status teveo"
