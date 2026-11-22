# teveo

Servicio de usuario que vigila las conexiones USB (udev vía GUdev). Al conectar un dispositivo
abre una ventana con:

- **Información**: descriptores, VID/PID, velocidad, consumo, interfaces/endpoints, controlador y módulos del
  kernel, nodos `/dev`, energía, propiedades udev y `lsusb -v` (botón para copiarlo todo).
- **Controladores y aplicaciones**: estado del controlador en el kernel, paquetes recomendados por clase USB/fabricante
  (con botón de instalar vía `pkexec apt-get`), paquetes Debian y Flatpak que coinciden por nombre,
  soporte fwupd y enlaces a la web del fabricante / linux-hardware.org. Las aplicaciones instaladas se
  pueden lanzar o probar desde la propia ventana.

## Uso
    ./install.sh              # instala el servicio (systemd --user) y la entrada «teveo» del menú de aplicaciones
    ./install.sh --uninstall
    python3 -m teveo --devices         # ventana con los dispositivos conectados (lo que abre el menú)
    python3 -m teveo --list            # dispositivos conectados
    python3 -m teveo --show 058f:9540  # abrir la ventana de uno ya conectado (1-5, VID:PID o ruta sysfs)
    python3 -m teveo --dump 1-5        # volcado en texto

Dependencias (ya presentes en Debian con GNOME): python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1,
gir1.2-gudev-1.0, usbutils, polkit. Se amplía la base de conocimiento en `teveo/kb.py`.
