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
- **Más datos del propio aparato** («sondas»): lo que no está en sysfs ni en udev se le pregunta al dispositivo.
  En un **teléfono Android** con la depuración USB activada y autorizada para este equipo se leen por `adb` el
  nombre comercial, el modelo, la versión de Android y el parche de seguridad, el procesador, la RAM, la pantalla,
  la batería (nivel, estado, salud, temperatura, tensión) y el almacenamiento interno; hace falta `adb`
  (`sudo apt install adb`). Si el teléfono ya está montado por MTP, también su almacenamiento. Para **cualquier**
  dispositivo se añade el árbol completo de atributos de udev. Cuando no se puede, un consejo dice qué hacer
  («Instala adb…», «Acepta la depuración USB en el teléfono…»). confusb no monta nada, y si arranca el servidor
  de `adb` para consultar lo vuelve a parar. `confusb --dump DEV` lo imprime todo por la terminal.
- **Interfaz** (botón «🎨 Interfaz»): opacidad y esquinas de las tarjetas, color de los títulos, marco
  (resaltado, atenuado o sin marco), sombra, pie «Ver información →» y qué hacer al conectar un dispositivo
  (notificación, abrir ventana o nada; solo los nuevos; abrir las unidades de almacenamiento). Los cambios se ven al momento y se guardan en
  `~/.config/confusb/ajustes.json`.

## Cuándo aparece confusb al conectar un dispositivo

confusb no salta con cada conexión. Al enchufar un dispositivo comprueba, por este orden:

1. **Que tu sesión sea la que está delante.** Con varios usuarios conectados a la vez («cambiar de usuario»)
   todas las sesiones reciben el mismo aviso del sistema; solo reacciona la activa.
2. **Si el dispositivo ya se conocía y funcionaba**: entonces no aparece. Los dispositivos conocidos se apuntan
   en `~/.local/share/confusb/dispositivos.json` (al arrancar por primera vez se apuntan los que ya están
   conectados). Si uno conocido deja de tener controlador, sí avisa.
3. **Si es la primera vez**: ofrece abrir la información con una notificación (botón *Ver información*), o abre
   la ventana directamente si así se ha elegido en «Interfaz».
4. **Si es una unidad de almacenamiento**: espera a que el sistema la monte y la abre con la aplicación
   predeterminada para unidades (el gestor de archivos, o la de su tipo de contenido si se ha configurado en
   GNOME). Si GNOME ya la abre por sí mismo (*Configuración › Medios extraíbles*), confusb no la abre otra vez.

Lo que se ha ofrecido y sigue pendiente también aparece dentro de la aplicación, en la tarjeta **Avisos** de la
ventana principal (con *Ver información* y *Descartar*). Al abrir la ventana se retiran las notificaciones del
sistema y con ellas el contador del icono; el aviso caduca solo si el dispositivo se desconecta.

Las dos últimas reglas se pueden cambiar en «Interfaz», que además tiene un botón para olvidar los
dispositivos conocidos. De las unidades de almacenamiento se muestra la **capacidad**, el modelo, la tabla de
particiones y, por partición, el sistema de ficheros, la etiqueta, el espacio libre y dónde está montada.

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

**Con apt (Debian 13 y derivadas; recomendado)**, desde el [repositorio APT](https://github.com/masebastia/apt) de
masebastia, que se actualiza con `apt upgrade`:

    sudo install -d -m 0755 /usr/share/keyrings
    sudo curl -fsSL -o /usr/share/keyrings/masebastia-archive-keyring.gpg \
        https://masebastia.github.io/apt/masebastia-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/masebastia-archive-keyring.gpg] https://masebastia.github.io/apt stable main" \
        | sudo tee /etc/apt/sources.list.d/masebastia.list
    sudo apt update && sudo apt install confusb

También se puede descargar el `.deb` suelto de la [última publicación](https://github.com/masebastia/confusb/releases/latest)
e instalarlo con `sudo apt install ./confusb_*_all.deb`.

**Desde el código fuente:**

    ./install.sh              # servicio (systemd --user) + entrada «confusb» en el menú de aplicaciones
    ./install.sh --uninstall

Dependencias (ya presentes en Debian con GNOME): `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`,
`gir1.2-gudev-1.0`, `usbutils`, `pkexec`.

## Dos procesos: servicio y ventana

- El **servicio** (`confusb` sin argumentos, lo arranca systemd con la sesión gráfica) vigila los USB y decide
  qué hacer. No carga GTK, así que ocupa poco (unos 30 MB) y sigue en marcha todo el rato.
- La **ventana** (`confusb --devices` o `--show`, o la entrada del menú) es otro proceso: al cerrar la última
  ventana termina y se va de la memoria. Cuando el servicio tiene que abrirla (al pulsar una notificación o con
  el ajuste «abrir ventana») la lanza como proceso aparte. Los avisos pendientes se pasan de uno a otro en
  `~/.local/share/confusb/avisos.json`, y la ventana le pide al servicio que retire las notificaciones.

Justo después de instalar el paquete el servicio está activado pero no arranca hasta el siguiente inicio de
sesión: por eso, al abrir la ventana, si el servicio está activado y parado la propia ventana lo arranca (si lo
has desactivado con `systemctl --user disable`, no lo toca).

Tras actualizar el paquete, reinicia el servicio para que use la versión nueva:
`systemctl --user restart confusb.service` (o cierra la sesión y vuelve a abrirla).

## Uso desde la terminal

    python3 -m confusb --devices         # ventana con los dispositivos conectados
    python3 -m confusb --show 058f:9540  # detalle de uno (1-5, VID:PID o ruta sysfs)
    python3 -m confusb --list            # listar dispositivos
    python3 -m confusb --dump 1-5        # volcado completo en texto

La base de conocimiento (qué paquetes y aplicaciones corresponden a cada clase USB o fabricante) está en
`confusb/kb.py`; añadir un dispositivo es añadir una entrada.

## Licencia

GPL-3.0-or-later. Ver [LICENSE](LICENSE).
