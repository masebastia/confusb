# confusb

Servicio de escritorio para Linux (GNOME) que **vigila las conexiones USB**. Al conectar un dispositivo
muestra toda su información y busca su **controlador** y las **aplicaciones** con las que usarlo.

Nació al comprobar que un lector de DNIe se veía en USB pero no hacía nada: faltaba `pcscd`. confusb lo
detecta y ofrece instalarlo.

## Qué hace

- **Ventana principal** (se abre maximizada): los dispositivos USB conectados, que se actualiza sola al
  conectar o desconectar. Pulsa uno para ver su detalle.
- **Detalle del dispositivo** (ventana sin maximizar, con botón *Volver*):
  - *Información*: descriptores, VID/PID, velocidad, consumo, interfaces y endpoints, controlador y módulos
    del kernel, nodos `/dev`, energía, propiedades udev y `lsusb -v`. Se puede copiar todo.
  - *Controladores y aplicaciones*: estado del controlador en el kernel, paquetes recomendados por clase
    USB y fabricante (con botón de instalar vía `pkexec apt-get`), paquetes Debian y Flatpak que coinciden
    por nombre, soporte de fwupd y enlaces a la web del fabricante. Las aplicaciones instaladas se pueden
    lanzar o probar desde la propia ventana (p. ej. listar lectores y certificados de un lector de DNIe).
- **Interfaz** (botón «🎨 Interfaz»): opacidad y esquinas de las tarjetas, color de los títulos, marco
  (resaltado, atenuado o sin marco), sombra, pie «Ver información →» y qué hacer al conectar un dispositivo
  (abrir ventana, notificación o nada). Los cambios se ven al momento y se guardan en
  `~/.config/confusb/ajustes.json`.

La estética es la de Contabilizando (otra aplicación del mismo autor): azul azabache con
degradado y el logotipo de la marca (un hexágono con el símbolo USB y un pulso) como marca de agua sobre
motivos de hardware (pistas de circuito impreso, chips y conectores), cabecera con emblema, navegación en
píldoras, tarjetas, barra inferior con etiqueta y subventanas de cristal difuminado. Sigue el tema claro u
oscuro del sistema, y los botones usan el color de acento del sistema.

## Idiomas

confusb habla los idiomas oficiales de los países de Europa: alemán, albanés, bielorruso, bosnio, búlgaro,
checo, croata, danés, eslovaco, esloveno, español, estonio, finés, francés, griego, húngaro, inglés, irlandés,
islandés, italiano, letón, lituano, luxemburgués, macedonio, maltés, montenegrino, neerlandés, noruego (bokmål),
polaco, portugués, rumano, ruso, serbio, sueco, turco y ucraniano. Se cambia con el desplegable de la esquina
superior derecha (bandera y abreviatura, «🇪🇸 ES»); la ventana se reabre en el idioma elegido y se recuerda.
Por defecto usa el idioma del sistema, o inglés si no lo tiene.

Los textos del código están en inglés y las traducciones son los `po/<código>.po` (gettext). El español es el
original del autor; **las demás traducciones las ha generado una IA y están pendientes de revisión por
hablantes nativos**: las correcciones son bienvenidas (basta editar el `.po` y abrir un *pull request*).
La ayuda de la línea de comandos solo está traducida al español.

    tools/i18n.py extract   # regenera po/confusb.pot a partir del código
    tools/i18n.py merge     # actualiza los .po con los textos nuevos
    tools/i18n.py check     # valida los .po (sintaxis y {marcadores})
    tools/i18n.py compile   # compila a locale/<idioma>/LC_MESSAGES/confusb.mo (necesita gettext)

Al ejecutar desde el código fuente se leen los `.po` directamente, sin compilar.

## Instalación

Desde el código fuente:

    ./install.sh              # servicio (systemd --user) + entrada «confusb» en el menú de aplicaciones
    ./install.sh --uninstall

Dependencias (ya presentes en Debian con GNOME): `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`,
`gir1.2-gudev-1.0`, `usbutils`, `pkexec`.

## Uso desde la terminal

    python3 -m confusb --devices         # ventana con los dispositivos conectados
    python3 -m confusb --show 058f:9540  # detalle de uno (1-5, VID:PID o ruta sysfs)
    python3 -m confusb --list            # listar dispositivos
    python3 -m confusb --dump 1-5        # volcado completo en texto

La base de conocimiento (qué paquetes y aplicaciones corresponden a cada clase USB o fabricante) está en
`confusb/kb.py`; añadir un dispositivo es añadir una entrada.

## Licencia

GPL-3.0-or-later. Ver [LICENSE](LICENSE).
