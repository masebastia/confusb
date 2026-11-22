# SPDX-License-Identifier: GPL-3.0-or-later
"""El servicio de confusb: vigila las conexiones USB y decide qué hacer (ver «conexion.py»).

Es un proceso aparte de la ventana y no carga GTK, así que ocupa poco: la ventana («app.py») se abre cuando
hace falta, con «confusb --devices» o «--show», y se va de la memoria al cerrarla; el servicio sigue en marcha.
Se arranca con la sesión gráfica (unidad de usuario de systemd) con «confusb» sin argumentos.

El servicio ofrece dos acciones por D-Bus (las usan las notificaciones y la ventana):
  detalle(ruta)    abre la ventana con el dispositivo (la acepta la notificación)
  retirar([ids])   retira notificaciones del sistema (la ventana lo pide al abrirse o al descartar avisos)
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import gi

gi.require_version("GUdev", "1.0")
from gi.repository import Gio, GLib, GUdev  # noqa: E402

from . import APP_ID, almacenamiento, avisos, conexion, usbinfo  # noqa: E402
from .i18n import _  # noqa: E402
from .preferencias import Preferencias  # noqa: E402

SERVICE_ID = APP_ID + ".servicio"
RUTA_OBJETO = "/" + SERVICE_ID.replace(".", "/")
SETTLE_MS = 1500          # esperar a que el kernel enlace drivers e interfaces
IGNORED_VIDS = {"1d6b"}   # root hubs de Linux Foundation


def llamar(accion: str, *argumentos: GLib.Variant) -> bool:
    """Pide al servicio, si está en marcha, que ejecute una de sus acciones. False si no está."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        dueno = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", (SERVICE_ID,)), GLib.VariantType("(b)"),
                              Gio.DBusCallFlags.NONE, 1000, None)
        if not dueno.unpack()[0]:
            return False
        bus.call_sync(SERVICE_ID, RUTA_OBJETO, "org.gtk.Actions", "Activate",
                      GLib.Variant("(sava{sv})", (accion, list(argumentos), {})), None,
                      Gio.DBusCallFlags.NONE, 1000, None)
        return True
    except GLib.Error:
        return False


class ServicioApp(Gio.Application):
    def __init__(self, prefs: Preferencias | None = None, registro: conexion.Registro | None = None,
                 almacen: avisos.Almacen | None = None):
        super().__init__(application_id=SERVICE_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.prefs = prefs or Preferencias()
        self.registro = registro or conexion.REGISTRO
        self.avisos = almacen or avisos.Almacen()
        self.client: GUdev.Client | None = None
        self._token: str | None = None       # permiso para que la ventana que se abra tome el foco
        for nombre, tipo, fn in (("detalle", "s", self._al_detalle), ("retirar", "as", self._al_retirar)):
            accion = Gio.SimpleAction.new(nombre, GLib.VariantType.new(tipo))
            accion.connect("activate", fn)
            self.add_action(accion)

    # --------------------------------------------------------- ciclo de vida
    def do_startup(self):
        Gio.Application.do_startup(self)
        self.hold()                          # sigue en marcha sin ventanas
        self.client = GUdev.Client(subsystems=["usb"])
        self.client.connect("uevent", self.on_uevent)
        if not self.registro.existe:         # primer arranque: lo que ya está conectado cuenta como conocido
            self.registro.sembrar(usbinfo.list_usb_devices())
        self.avisos.podar()                  # fuera los avisos de dispositivos que ya no están
        print("confusb: watching USB connections…", flush=True)

    def do_activate(self):
        pass                                 # ya está en marcha; no hay ventana que abrir

    def do_before_emit(self, plataforma):
        """El sistema entrega con cada acción (clic en una notificación) un permiso para tomar el foco."""
        try:
            datos = plataforma.unpack() if plataforma is not None else {}
            self._token = datos.get("activation-token") or datos.get("desktop-startup-id")
        except Exception:  # noqa: BLE001
            self._token = None

    # ---------------------------------------------------------------- eventos
    def on_uevent(self, _client, action: str, device: GUdev.Device):
        if device.get_devtype() != "usb_device":
            return
        if (device.get_property("ID_VENDOR_ID") or device.get_sysfs_attr("idVendor") or "") in IGNORED_VIDS:
            return
        path = device.get_sysfs_path()
        if action == "add":
            GLib.timeout_add(SETTLE_MS, self.conectado, path)
        elif action == "remove":
            self.desconectado(path)

    def desconectado(self, path: str):
        """Ya no está: su oferta caduca."""
        aviso = self.avisos.quitar(path)
        if aviso:
            self.withdraw_notification(aviso.notificacion)

    def conectado(self, path: str):
        """Un dispositivo nuevo, con el kernel ya asentado: decidir qué hacer."""
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
            self.prefs.recargar()            # la ventana (otro proceso) puede haberlos cambiado
            self.registro.recargar()
            previo = self.registro.buscar(info)
            dec = conexion.decidir(info, activa=activa, previo=previo, modo=self.prefs.al_conectar,
                                   solo_nuevos=self.prefs.solo_nuevos,
                                   abrir_almacenamiento=self.prefs.abrir_almacenamiento, automount_open=gnome_abre)
            print(f"confusb: {info.usb_id} {info.title}: {dec.accion} ({dec.motivo})", flush=True)
            if activa and not info.is_hub:
                self.registro.anotar(info)   # ya ha estado conectado: la próxima vez no es nuevo
            if dec.accion == "ventana":
                self.abrir_ventana("--show", path)
            elif dec.accion == "notificar":
                self.notificar(info, path)
            elif dec.accion == "almacenamiento":
                self.abrir_almacenamiento(info, path, nuevo=previo is None)
            return False

        threading.Thread(target=trabajo, daemon=True).start()
        return False

    # ------------------------------------------------------------ reacciones
    def notificar(self, info: usbinfo.DeviceInfo, path: str):
        """Ofrece abrir la información del dispositivo: botón «Ver información» (o pulsar la notificación).
        La oferta queda además apuntada para que la ventana la muestre en su tarjeta «Avisos»."""
        aviso = self.avisos.anadir(path, info.title, info.usb_id)
        destino = GLib.Variant.new_string(path)
        n = Gio.Notification.new(_("USB device connected"))
        n.set_body(f"{info.title} · {info.usb_id}")
        n.set_icon(Gio.ThemedIcon.new(APP_ID))
        n.set_default_action_and_target("app.detalle", destino)
        n.add_button_with_target(_("View information"), "app.detalle", destino)
        self.send_notification(aviso.notificacion, n)

    def abrir_almacenamiento(self, info: usbinfo.DeviceInfo, path: str, nuevo: bool):
        """Espera a que se monte la unidad y la abre con la aplicación predeterminada. Si no se monta (sin
        formato, cifrada, montaje automático desactivado…) y es la primera vez, se ofrece ver su información."""
        def al_agotar():
            if nuevo:
                self.notificar(info, path)

        almacenamiento.EsperaMontaje(path, almacenamiento.abrir, al_agotar)

    def abrir_ventana(self, *args: str):
        """Lanza la ventana como proceso aparte («confusb --show RUTA»): al cerrarla se va de la memoria."""
        entorno = dict(os.environ)
        if self._token:
            entorno["XDG_ACTIVATION_TOKEN"] = entorno["DESKTOP_STARTUP_ID"] = self._token
            self._token = None
        try:
            hijo = subprocess.Popen([sys.executable, "-m", "confusb", *args], env=entorno, start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"confusb: could not open the window: {e}", flush=True)
            return
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, hijo.pid, lambda *_: None)   # recoge su estado al terminar

    # ------------------------------------------------------ acciones de D-Bus
    def _al_detalle(self, _accion, valor):
        path = valor.get_string()
        self.desconectado(path)              # se acepta la oferta: aviso atendido
        self.abrir_ventana("--show", path)

    def _al_retirar(self, _accion, valor):
        for notificacion in valor.get_strv():
            self.withdraw_notification(notificacion)
