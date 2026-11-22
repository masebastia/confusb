# confusb en Debian

Estado del empaquetado y pasos para llevarlo al archivo oficial de Debian.

## Construir el paquete

Herramientas (una vez): `sudo apt install debhelper dh-python pybuild-plugin-pyproject devscripts lintian python3-all python3-setuptools gettext`

    git archive --prefix=confusb-0.2.0/ -o ../confusb_0.2.0.orig.tar.gz v0.2.0   # el tarball «orig» sin debian/
    dpkg-buildpackage -us -uc -b                                                  # genera ../confusb_0.2.0-1_all.deb
    lintian -I --pedantic ../confusb_0.2.0-1_all.deb

`debian/` está en el mismo repositorio; `.gitattributes` lo excluye del tarball (`export-ignore`).

## Antes de subirlo

- [x] `Maintainer:` en `debian/control` y firma de `debian/changelog` (revisar el nombre si se quiere uno real).
- [ ] Abrir el ITP (abajo) y poner su número en el changelog: `* Initial release. (Closes: #NNNNNN)`.
- [ ] Cambiar `UNRELEASED` por `unstable` en la primera línea del changelog.
- [ ] Que `lintian -I --pedantic` no dé errores (solo avisos informativos).
- [ ] Compilar en un entorno limpio (`sbuild` o `pbuilder`) para comprobar las dependencias de compilación.

## 1. ITP (Intent To Package)

Con `reportbug` configurado (necesita un correo real):

    reportbug --email TU_CORREO wnpp        # elegir «ITP»

Borrador:

    Subject: ITP: confusb -- USB device information and driver finder for the desktop
    Package: wnpp
    Severity: wishlist

    * Package name    : confusb
      Version         : 0.2.0
      Upstream Contact: masebastia
    * URL             : https://github.com/masebastia/confusb
    * License         : GPL-3+
      Programming Lang: Python
      Description     : USB device information and driver finder for the desktop

    confusb watches the USB connections. When a device is plugged in it opens a window
    with everything the system knows about it (descriptors, interfaces, kernel driver and
    modules, device nodes, udev properties) and looks for its driver and the applications
    needed to use it, showing what is already installed. For instance, with a smart card
    reader it detects that pcscd is missing and offers to install it. The interface is
    available in the official languages of the European countries.

    I plan to maintain it myself and I am looking for a sponsor.

## 2. Subir a mentors.debian.net

1. Crear una cuenta en <https://mentors.debian.net> y tener una clave GPG (publicada en un servidor de claves).
2. Construir el paquete fuente firmado: `dpkg-buildpackage -S` (con la clave) y subirlo: `dput mentors ../confusb_0.2.0-1_source.changes`.
3. Abrir un *RFS* (Request For Sponsorship) contra el pseudopaquete `sponsorship-requests` (`reportbug sponsorship-requests`),
   con el enlace del paquete en mentors y el del ITP.

## 3. Revisión y migración

Un desarrollador de Debian revisa y sube el paquete → cola NEW de ftp-masters (días o semanas) → `unstable`
→ `testing` a los 5-10 días sin errores críticos. Debian 13 («trixie») ya es estable, así que el paquete
llegaría a Debian 14; para trixie quedaría `trixie-backports` cuando esté en `testing`.

## Notas de empaquetado

- Dependencias en tiempo de ejecución: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gir1.2-gudev-1.0`,
  `gir1.2-graphene-1.0`, `usbutils`, `udev` y `kmod`. Recomienda `pkexec` (instalar paquetes desde la ventana).
- El servicio es una unidad de usuario de systemd (`/usr/lib/systemd/user/confusb.service`), activada por defecto
  con la sesión gráfica (`dh_installsystemduser`). El ajuste «Al conectar un dispositivo» permite abrir una
  ventana, mostrar una notificación o no hacer nada.
- Las traducciones (`po/*.po`) se compilan a `.mo` en `/usr/share/locale`. Las que no son españolas están
  generadas con IA y pendientes de revisión: conviene decirlo al presentar el paquete.
- Los textos de la ayuda de línea de comandos solo están traducidos al español.
