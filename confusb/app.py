# SPDX-License-Identifier: GPL-3.0-or-later
"""La aplicación de confusb: las ventanas con la información de los dispositivos USB.

Se abre con «confusb --devices» o «confusb --show DEV» (o desde el menú de aplicaciones) y termina, saliendo de
la memoria, al cerrar la última ventana. La vigilancia de los USB y las notificaciones son del servicio
(«servicio.py»), otro proceso que sigue en marcha. Mientras la ventana está abierta se mantiene al día por su
cuenta (conexiones y desconexiones) y muestra los avisos que el servicio ha ido apuntando."""
from __future__ import annotations

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GUdev", "1.0")
from gi.repository import Adw, Gio, GLib, GUdev  # noqa: E402

from . import APP_ID, avisos, servicio, usbinfo  # noqa: E402
from .ajustes import AJUSTES  # noqa: E402
from .i18n import _  # noqa: E402
from .ui import DeviceWindow, DevicesWindow  # noqa: E402

SETTLE_MS = 1500          # esperar a que el kernel enlace drivers e interfaces
IGNORED_VIDS = {"1d6b"}   # root hubs de Linux Foundation


class ConfusbApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.windows: dict[str, DeviceWindow] = {}
        self.client: GUdev.Client | None = None
        self.devices_win: DevicesWindow | None = None
        self.almacen = avisos.Almacen()
        self._monitor: Gio.FileMonitor | None = None
        self._repintar = 0
        self.add_main_option("devices", ord("d"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             _("Show the list of connected USB devices"), None)
        self.add_main_option("show", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             _("Show a device's window (1-5, VID:PID or sysfs path)"), "DEV")

    # --------------------------------------------------------- ciclo de vida
    def do_startup(self):
        Adw.Application.do_startup(self)
        self.client = GUdev.Client(subsystems=["usb"])      # para mantener la lista al día mientras hay ventanas
        self.client.connect("uevent", self.on_uevent)
        self._vigilar_avisos()

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        if "show" in opts and "devices" not in opts:
            path = usbinfo.resolve_target(opts["show"])
            if not path:
                cmdline.printerr_literal(_("Device «{name}» not found").format(name=opts["show"]) + "\n")
                return 1
            self.open_device(path)
        else:
            self.show_devices()
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
    def lista_avisos(self) -> list[avisos.Aviso]:
        return self.almacen.leer()

    def _vigilar_avisos(self):
        """El servicio apunta los avisos en un fichero: al cambiar, la tarjeta «Avisos» se pone al día."""
        carpeta = os.path.dirname(self.almacen.ruta)
        try:
            os.makedirs(carpeta, exist_ok=True)
            self._monitor = Gio.File.new_for_path(carpeta).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except (OSError, GLib.Error):
            return
        self._monitor.connect("changed", self._cambio_en_carpeta)

    def _cambio_en_carpeta(self, _monitor, fichero, otro, _evento):
        mio = os.path.basename(self.almacen.ruta)
        if mio not in {f.get_basename() for f in (fichero, otro) if f is not None}:
            return
        if not self._repintar:      # el fichero se escribe en dos pasos (temporal y renombrado): se junta todo
            self._repintar = GLib.timeout_add(150, self._pintar_avisos_diferido)

    def _pintar_avisos_diferido(self):
        self._repintar = 0
        self._pintar_avisos()
        return False

    def _pintar_avisos(self):
        if self.devices_win:
            self.devices_win.pintar_avisos()
            if self.devices_win.is_active():     # delante: ya se ven aquí, que no quede el contador en el icono
                self.marcar_leidos()

    def _retirar_notificaciones(self, avisos_: list[avisos.Aviso]):
        ids = [a.notificacion for a in avisos_]
        if ids:
            servicio.llamar("retirar", GLib.Variant("as", ids))      # las notificaciones son del servicio

    def marcar_leidos(self):
        """Los avisos ya se ven dentro de la aplicación: se retiran las notificaciones del sistema (y con ellas
        el contador del icono). Siguen en la tarjeta «Avisos» hasta que se descarten."""
        self._retirar_notificaciones(self.almacen.leer())

    def descartar_aviso(self, path: str):
        quitado = self.almacen.quitar(path)
        self._retirar_notificaciones([quitado] if quitado else [])
        self._pintar_avisos()

    def descartar_avisos(self):
        self._retirar_notificaciones(self.almacen.vaciar())
        self._pintar_avisos()

    def al_detalle(self, path: str):
        """El usuario ha aceptado la oferta desde la tarjeta: se abre el dispositivo y el aviso se da por atendido."""
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
            if self.devices_win:
                self.devices_win.refresh(aviso=_("Disconnected: {name}").format(name=nombre))

    def conectado(self, path: str):
        """Un dispositivo nuevo: se actualiza la lista (la decisión de ofrecerlo es del servicio)."""
        if not os.path.exists(path) or not self.devices_win:
            return False

        def trabajo():
            try:
                res = usbinfo.collect(path, with_lsusb=False)
            except Exception as e:  # noqa: BLE001
                res = e
            GLib.idle_add(hecho, res)

        def hecho(info):
            if not isinstance(info, Exception) and self.devices_win:
                self.devices_win.refresh(aviso=_("Connected: {name}").format(name=info.title))
            return False

        threading.Thread(target=trabajo, daemon=True).start()
        return False

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

        def done(info):
            try:
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
            finally:
                self.release()      # ya hay ventana (o no ha podido abrirse): el proceso vive con ella o termina

        def runner():
            try:
                res = usbinfo.collect(path)
            except Exception as e:  # noqa: BLE001
                res = e
            GLib.idle_add(done, res)

        # Leer el dispositivo tarda (lsusb): hasta que haya ventana, el proceso no debe terminar.
        self.hold()
        threading.Thread(target=runner, daemon=True).start()
        return False
