# SPDX-License-Identifier: GPL-3.0-or-later
"""Servicio de confusb: escucha los eventos udev de USB y, según la política de «conexion» y los ajustes,
abre una ventana con la información del dispositivo, ofrece abrirla con una notificación, abre la unidad de
almacenamiento con la aplicación predeterminada o no hace nada."""
from __future__ import annotations

import argparse
import os
import sys
import threading
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GUdev", "1.0")
from gi.repository import Adw, Gio, GLib, GUdev  # noqa: E402

from . import APP_ID, __version__, almacenamiento, conexion, usbinfo  # noqa: E402
from .ajustes import AJUSTES  # noqa: E402
from .i18n import _  # noqa: E402
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


@dataclass
class Aviso:
    """Una notificación de «dispositivo conectado» pendiente: se muestra también dentro de la ventana principal."""
    path: str          # ruta sysfs del dispositivo
    titulo: str
    usb_id: str
    hora: GLib.DateTime

    @property
    def notificacion(self) -> str:
        return f"usb-{self.usb_id}"


class ConfusbApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.windows: dict[str, DeviceWindow] = {}
        self.client: GUdev.Client | None = None
        self.held = False
        self.devices_win: DevicesWindow | None = None
        self.avisos: dict[str, Aviso] = {}       # por ruta sysfs, en orden de llegada
        accion = Gio.SimpleAction.new("detalle", GLib.VariantType.new("s"))   # la usan las notificaciones
        accion.connect("activate", lambda _a, v: self.al_detalle(v.get_string()))
        self.add_action(accion)
        self.add_main_option("devices", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Show the list of connected USB devices"), None)
        self.add_main_option("show", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             _("Show a device's window (1-5, VID:PID or sysfs path)"), "DEV")

    # --------------------------------------------------------- ciclo de vida
    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        if "devices" in opts:
            self.show_devices()
            return 0
        if "show" in opts:
            path = resolve_target(opts["show"])
            if not path:
                cmdline.printerr_literal(_("Device «{name}» not found").format(name=opts["show"]) + "\n")
                return 1
            self.open_device(path)
            return 0
        if not self.held:  # modo servicio
            self.hold()
            self.held = True
            self.client = GUdev.Client(subsystems=["usb"])
            self.client.connect("uevent", self.on_uevent)
            if not conexion.REGISTRO.existe:   # primer arranque: lo que ya está conectado cuenta como conocido
                conexion.REGISTRO.sembrar(usbinfo.list_usb_devices())
            print("confusb: watching USB connections…", flush=True)
        return 0

    def cambiar_idioma(self, codigo: str):
        """Cambia el idioma y reabre las ventanas para que se vean en él."""
        AJUSTES.cambiar(idioma=codigo)
        GLib.idle_add(self._reconstruir)

    def _reconstruir(self):
        abiertas = list(self.windows)                    # detalles abiertos (por ruta sysfs)
        con_principal = self.devices_win is not None
        self.hold()                                      # que la aplicación no termine entre medias
        for w in list(self.get_windows()):
            w.close()
        if con_principal:
            self.show_devices()
        for path in abiertas:
            self.open_device(path)
        GLib.timeout_add_seconds(5, lambda: self.release() or False)
        return False

    def show_devices(self):
        if self.devices_win is None:
            self.devices_win = DevicesWindow(self, self.open_device)
            self.devices_win.connect("close-request", lambda *_: setattr(self, "devices_win", None) or False)
        self.devices_win.present()
        self.marcar_leidos()

    # ----------------------------------------------------------------- avisos
    def marcar_leidos(self):
        """Los avisos ya se ven dentro de la aplicación: se retiran las notificaciones del sistema (y con ellas
        el contador del icono). Siguen en la tarjeta «Avisos» hasta que se descarten."""
        for a in self.avisos.values():
            self.withdraw_notification(a.notificacion)

    def descartar_aviso(self, path: str):
        a = self.avisos.pop(path, None)
        if a:
            self.withdraw_notification(a.notificacion)
        self._pintar_avisos()

    def descartar_avisos(self):
        for path in list(self.avisos):
            a = self.avisos.pop(path)
            self.withdraw_notification(a.notificacion)
        self._pintar_avisos()

    def _pintar_avisos(self):
        if self.devices_win:
            self.devices_win.pintar_avisos()

    def al_detalle(self, path: str):
        """El usuario ha aceptado la oferta (notificación o tarjeta): se abre el dispositivo y el aviso se da por atendido."""
        self.open_device(path)
        self.descartar_aviso(path)

    # ---------------------------------------------------------------- eventos
    def on_uevent(self, _client, action: str, device: GUdev.Device):
        if device.get_devtype() != "usb_device":
            return
        path = device.get_sysfs_path()
        if (device.get_property("ID_VENDOR_ID") or device.get_sysfs_attr("idVendor") or "") in IGNORED_VIDS:
            return
        if action == "add":
            GLib.timeout_add(SETTLE_MS, self.conectado, path)
        elif action == "remove":
            nombre = (device.get_property("ID_MODEL_FROM_DATABASE") or device.get_property("ID_MODEL")
                      or _("USB device")).replace("_", " ")
            if path in self.windows:
                self.windows[path].mark_disconnected()
            self.descartar_aviso(path)       # ya no está: la oferta caduca
            if self.devices_win:
                self.devices_win.refresh(aviso=_("Disconnected: {name}").format(name=nombre))

    def conectado(self, path: str):
        """Un dispositivo nuevo, con el kernel ya asentado: actualizar la lista y decidir qué hacer."""
        if not os.path.exists(path):
            return False

        def trabajo():
            try:
                res = (usbinfo.collect(path, with_lsusb=False), conexion.sesion_activa(), almacenamiento.automount_open())
            except Exception as e:  # noqa: BLE001
                res = e
            GLib.idle_add(hecho, res)

        def hecho(res):
            if isinstance(res, Exception):
                print(f"confusb: error reading {path}: {res}", flush=True)
                return False
            info, activa, gnome_abre = res
            if self.devices_win:
                self.devices_win.refresh(aviso=_("Connected: {name}").format(name=info.title))
            previo = conexion.REGISTRO.buscar(info)
            dec = conexion.decidir(info, activa=activa, previo=previo, modo=AJUSTES.al_conectar,
                                   solo_nuevos=AJUSTES.solo_nuevos, abrir_almacenamiento=AJUSTES.abrir_almacenamiento,
                                   automount_open=gnome_abre)
            print(f"confusb: {info.usb_id} {info.title}: {dec.accion} ({dec.motivo})", flush=True)
            if activa and not info.is_hub:
                conexion.REGISTRO.anotar(info)       # ya ha estado conectado: la próxima vez no es nuevo
            if dec.accion == "ventana":
                self.open_device(path)
            elif dec.accion == "notificar":
                self.notificar(info, path)
            elif dec.accion == "almacenamiento":
                self.abrir_almacenamiento(info, path, nuevo=previo is None)
            return False

        threading.Thread(target=trabajo, daemon=True).start()
        return False

    def notificar(self, info: usbinfo.DeviceInfo, path: str):
        """Ofrece abrir la información del dispositivo: botón «Ver información» (o pulsar la notificación)."""
        self.avisos[path] = Aviso(path, info.title, info.usb_id, GLib.DateTime.new_now_local())
        self._pintar_avisos()
        if self.devices_win and self.devices_win.is_active():
            return        # la ventana está delante: el aviso ya se ve dentro, sin notificación ni contador
        destino = GLib.Variant.new_string(path)
        n = Gio.Notification.new(_("USB device connected"))
        n.set_body(f"{info.title} · {info.usb_id}")
        n.set_default_action_and_target("app.detalle", destino)
        n.add_button_with_target(_("View information"), "app.detalle", destino)
        self.send_notification(f"usb-{info.usb_id}", n)

    def abrir_almacenamiento(self, info: usbinfo.DeviceInfo, path: str, nuevo: bool):
        """Espera a que se monte la unidad y la abre con la aplicación predeterminada. Si no se monta (sin
        formato, cifrada, montaje automático desactivado…) y es la primera vez, se ofrece ver su información."""
        def al_agotar():
            if nuevo:
                self.notificar(info, path)

        almacenamiento.EsperaMontaje(path, almacenamiento.abrir, al_agotar)

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
                print(f"confusb: error reading {path}: {info}", flush=True)
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
        p = resolve_target(args.dump)
        if not p:
            print(_("Device «{name}» not found").format(name=args.dump))
            return 1
        print(usbinfo.collect(p).as_text())
        return 0
    if args.devices:   # estas dos las trata GApplication (y las reenvía a la instancia que ya está en marcha)
        rest = ["--devices", *rest]
    if args.show:
        rest = ["--show", args.show, *rest]
    return ConfusbApp().run([argv[0], *rest])


def cli() -> None:
    """Punto de entrada del comando «confusb»."""
    sys.exit(main(sys.argv))
