"""Servicio: escucha eventos udev de USB y abre la ventana de detalle."""
from __future__ import annotations

import argparse
import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GUdev", "1.0")
from gi.repository import Adw, Gio, GLib, GUdev  # noqa: E402

from . import APP_ID, usbinfo  # noqa: E402
from .ui import DeviceWindow, DevicesWindow  # noqa: E402

SETTLE_MS = 1500          # esperar a que el kernel enlace drivers e interfaces
IGNORED_VIDS = {"1d6b"}   # root hubs de Linux Foundation


def resolve_target(target: str) -> str | None:
    """Acepta '1-5', 'VID:PID' o una ruta sysfs."""
    if os.path.isabs(target):
        return target
    cand = f"/sys/bus/usb/devices/{target}"
    if os.path.exists(cand):
        return os.path.realpath(cand)
    for p in usbinfo.list_usb_devices():
        if usbinfo.read(p + "/idVendor") and f"{usbinfo.read(p + '/idVendor')}:{usbinfo.read(p + '/idProduct')}" == target.lower():
            return p
    return None


class TeveoApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.windows: dict[str, DeviceWindow] = {}
        self.client: GUdev.Client | None = None
        self.held = False
        self.devices_win: DevicesWindow | None = None
        self.add_main_option("devices", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Mostrar la lista de dispositivos USB conectados", None)
        self.add_main_option("show", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Mostrar la ventana de un dispositivo (1-5, VID:PID o ruta sysfs)", "DISP")

    # --------------------------------------------------------- ciclo de vida
    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        if "devices" in opts:
            self.show_devices()
            return 0
        if "show" in opts:
            path = resolve_target(opts["show"])
            if not path:
                cmdline.printerr_literal(f"No se encuentra el dispositivo «{opts['show']}»\n")
                return 1
            self.open_device(path)
            return 0
        if not self.held:  # modo servicio
            self.hold()
            self.held = True
            self.client = GUdev.Client(subsystems=["usb"])
            self.client.connect("uevent", self.on_uevent)
            print("teveo: vigilando conexiones USB…", flush=True)
        return 0

    def show_devices(self):
        if self.devices_win is None:
            self.devices_win = DevicesWindow(self, self.open_device)
            self.devices_win.connect("close-request", lambda *_: setattr(self, "devices_win", None) or False)
        self.devices_win.present()

    # ---------------------------------------------------------------- eventos
    def on_uevent(self, _client, action: str, device: GUdev.Device):
        if device.get_devtype() != "usb_device":
            return
        path = device.get_sysfs_path()
        if action == "add":
            if (device.get_sysfs_attr("idVendor") or "") in IGNORED_VIDS:
                return
            GLib.timeout_add(SETTLE_MS, self.open_device, path)
        elif action == "remove" and path in self.windows:
            self.windows[path].mark_disconnected()

    def open_device(self, path: str):
        win = self.windows.get(path)
        if win:
            if not win.disconnected:
                win.present()
                return False
            # El dispositivo se desconectó y vuelve a estar en el mismo puerto (puede ser otro distinto):
            # se descarta la ventana antigua y se abre una nueva con los datos actuales.
            self.windows.pop(path, None)
            win.close()
        if not os.path.exists(path):  # ya se ha desconectado
            return False

        def work():
            return usbinfo.collect(path)

        def done(info):
            if isinstance(info, Exception):
                print(f"teveo: error leyendo {path}: {info}", flush=True)
                return False
            w = DeviceWindow(self, info)
            self.windows[path] = w
            def on_close(win, path=path):
                if self.windows.get(path) is win:  # no borrar la ventana nueva del mismo puerto
                    del self.windows[path]
                return False

            w.connect("close-request", on_close)
            w.present()
            return False

        def runner():
            try:
                res = work()
            except Exception as e:  # noqa: BLE001
                res = e
            GLib.idle_add(done, res)

        threading.Thread(target=runner, daemon=True).start()
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="teveo", add_help=False)
    ap.add_argument("--list", action="store_true", help="Listar dispositivos USB y salir")
    ap.add_argument("--dump", metavar="DISP", help="Imprimir toda la información de un dispositivo y salir")
    ap.add_argument("-h", "--help", action="store_true")
    args, rest = ap.parse_known_args(argv[1:])
    if args.help:
        print("uso: teveo            servicio (vigila conexiones USB y abre una ventana)\n"
              "     teveo --show X   abrir ventana de un dispositivo conectado (1-5, 058f:9540, ruta sysfs)\n"
              "     teveo --devices  ventana con los dispositivos conectados\n"
              "     teveo --list     listar dispositivos\n"
              "     teveo --dump X   volcar toda la información en texto")
        return 0
    if args.list:
        for p in usbinfo.list_usb_devices():
            i = usbinfo.collect(p, with_lsusb=False)
            print(f"{os.path.basename(p):8} {i.usb_id}  {i.vendor} — {i.product}")
        return 0
    if args.dump:
        p = resolve_target(args.dump)
        if not p:
            print("dispositivo no encontrado")
            return 1
        print(usbinfo.collect(p).as_text())
        return 0
    return TeveoApp().run([argv[0], *rest])
