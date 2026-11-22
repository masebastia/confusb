#!/usr/bin/env bash
# Instala confusb como servicio de usuario (systemd --user) y como entrada del menú de aplicaciones.
# Desinstalar: ./install.sh --uninstall
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ID="es.masebastia.confusb"
UNIT="$HOME/.config/systemd/user/confusb.service"
APPS="$HOME/.local/share/applications"
DESKTOP="$APPS/$ID.desktop"
ICONS="$HOME/.local/share/icons/hicolor"
ICON="$ICONS/scalable/apps/$ID.svg"

refrescar() {
  update-desktop-database "$APPS" 2>/dev/null || true
  gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now confusb.service 2>/dev/null || true
  rm -f "$UNIT" "$DESKTOP" "$ICON"
  systemctl --user daemon-reload
  refrescar
  echo "confusb desinstalado."; exit 0
fi

# Migración: la aplicación se llamó «teveo» mientras estaba en pruebas.
if [[ -f "$HOME/.config/systemd/user/teveo.service" ]]; then
  systemctl --user disable --now teveo.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/teveo.service" "$APPS/es.teveo.Monitor.desktop" \
        "$ICONS/scalable/apps/es.teveo.Monitor.svg"
  echo "Retirada la instalación antigua de «teveo»."
fi

mkdir -p "$(dirname "$UNIT")" "$APPS" "$(dirname "$ICON")"
sed "s|@PROJECT_DIR@|$DIR|" "$DIR/systemd/confusb.service.in" > "$UNIT"
sed "s|@PROJECT_DIR@|$DIR|" "$DIR/data/$ID.desktop.in" > "$DESKTOP"
cp "$DIR/confusb/recursos/icono.svg" "$ICON"
refrescar
systemctl --user daemon-reload
systemctl --user enable confusb.service
systemctl --user restart confusb.service
echo "confusb instalado: servicio en marcha y entrada «confusb» en el menú de aplicaciones."
echo "Estado: systemctl --user status confusb"
