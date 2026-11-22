# SPDX-License-Identifier: GPL-3.0-or-later
"""Punto de entrada del comando «confusb».

  confusb                    el servicio que vigila los USB (sin GTK; lo arranca systemd con la sesión)
  confusb --devices          la ventana con los dispositivos conectados
  confusb --show DEV         la ventana de un dispositivo
  confusb --list / --dump    listados por la terminal (sin ventana)

La ventana y el servicio son procesos distintos: GTK solo se carga cuando se pide una ventana.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, usbinfo
from .i18n import _
from .preferencias import Preferencias


def main(argv: list[str]) -> int:
    Preferencias()      # fija el idioma (el elegido o el del sistema) antes de generar la ayuda
    ap = argparse.ArgumentParser(
        prog="confusb",
        description=_("Shows the information of a USB device when it is connected and looks for its driver "
                      "and the applications to use it."),
        epilog=_("Without arguments it runs as a service that watches the USB connections according to the settings."))
    ap.add_argument("--devices", action="store_true", help=_("show the window with the connected devices"))
    ap.add_argument("--show", metavar="DEV", help=_("open the details of a device (1-5, VID:PID or sysfs path)"))
    ap.add_argument("--list", action="store_true", help=_("list the USB devices and exit"))
    ap.add_argument("--dump", metavar="DEV",
                    help=_("print all the information of a device and exit (1-5, VID:PID or sysfs path)"))
    ap.add_argument("--version", action="store_true", help=_("show the version and exit"))
    args, rest = ap.parse_known_args(argv[1:])
    if args.version:
        print(f"confusb {__version__}")
        return 0
    if args.list:
        for p in usbinfo.list_usb_devices():
            i = usbinfo.collect(p, with_lsusb=False)
            print(f"{os.path.basename(p):8} {i.usb_id}  {i.vendor} — {i.product}")
        return 0
    if args.dump:
        p = usbinfo.resolve_target(args.dump)
        if not p:
            print(_("Device «{name}» not found").format(name=args.dump))
            return 1
        print(usbinfo.collect(p).as_text())
        return 0
    if args.devices or args.show:   # la ventana: estas dos las trata GApplication (y las reenvía si ya hay una abierta)
        from .app import ConfusbApp
        if args.devices:
            rest = ["--devices", *rest]
        if args.show:
            rest = ["--show", args.show, *rest]
        return ConfusbApp().run([argv[0], *rest])
    from .servicio import ServicioApp
    return ServicioApp().run([argv[0], *rest])


def cli() -> None:
    sys.exit(main(sys.argv))
