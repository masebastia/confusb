# SPDX-License-Identifier: GPL-3.0-or-later
"""Ventanas de confusb, con la estructura de Contabilizando: fondo azul azabache con el logotipo de marca de
agua, cabecera con emblema y botones, navegación en píldoras, tarjetas y barra inferior.

  DevicesWindow  ventana principal (se abre maximizada): los dispositivos USB conectados.
  DeviceWindow   detalle de un dispositivo (sin maximizar), con botón para volver a la principal.
"""
from __future__ import annotations

import os
import shlex
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import almacenamiento, fondo, resolver, usbinfo  # noqa: E402
from .ajustes import AJUSTES  # noqa: E402
from .i18n import _  # noqa: E402
from .componentes import (HUECO, AcercaDeDialogo, BarraEstado, Cabecera, InterfazDialogo, Masonry, SelectorIdioma,  # noqa: E402
                          boton, bruto, datos, desplazable, estado, in_thread, label, pastillas, pila, rubrica,
                          run_capture, tarjeta)
from .usbinfo import CLASS_NAMES, DeviceInfo, class_name  # noqa: E402


def emoji_de(info: DeviceInfo) -> str:
    n = f"{info.product} {info.vendor}".lower()
    c = info.classes
    if "mouse" in n or "ratón" in n:
        return "🖱️"
    if "keyboard" in n or "teclado" in n:
        return "⌨️"
    for clase, e in ((0x0B, "💳"), (0x0E, "📷"), (0x08, "💾"), (0x07, "🖨️"), (0xE0, "📶"), (0x01, "🔊"),
                     (0x09, "🔀"), (0x03, "🕹️")):
        if clase in c:
            return e
    return "🔌"


# ------------------------------------------------------------------ base

class VentanaBase(Gtk.ApplicationWindow):
    """Estructura común: barra de título del sistema y, encima del fondo, cabecera + contenido + barra
    inferior. Los diálogos de cristal («Interfaz», «Acerca de») flotan encima de todo."""

    def __init__(self, app, titulo: str, subtitulo: str, ancho: int, alto: int):
        AJUSTES.instalar()
        super().__init__(application=app, title=titulo, default_width=ancho, default_height=alto)
        self.add_css_class("confusb")
        self.dialogo = None
        self._recaptura = 0

        # Barra de título del sistema, sin opciones; el doble clic maximiza/restaura.
        titulo_barra = Gtk.HeaderBar()
        titulo_barra.set_title_widget(Gtk.Label(label=titulo, css_classes=["title"]))
        self.set_titlebar(titulo_barra)
        dbl = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        dbl.connect("pressed", self._doble_clic, titulo_barra)
        titulo_barra.add_controller(dbl)

        self.fondo = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True)
        self.cabecera = Cabecera(subtitulo)
        self.cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)   # entre cabecera y barra
        self.barra = BarraEstado()
        columna = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for w in (self.cabecera, self.cuerpo, self.barra):
            columna.append(w)
        self.pagina = Gtk.Overlay(child=self.fondo)            # lo que se captura para el cristal difuminado
        self.pagina.add_overlay(columna)
        self.exterior = Gtk.Overlay(child=self.pagina)
        self.toasts = Adw.ToastOverlay(child=self.exterior)
        self.set_child(self.toasts)

        AJUSTES.suscribir(self._al_ajustes)
        self.connect("close-request", self._al_cerrar)
        self._actualizar_fondo()

    # ---- botones comunes de la cabecera (a la derecha)
    def botones_comunes(self):
        self.cabecera.boton("🎨  " + _("Interface"), lambda: self.alternar_dialogo(InterfazDialogo),
                            _("Look of the application and what to do when a device is connected"))
        self.cabecera.boton(_("About"), lambda: self.alternar_dialogo(AcercaDeDialogo))
        self.cabecera.derecha.append(SelectorIdioma(lambda codigo: self.get_application().cambiar_idioma(codigo)))

    def _al_cerrar(self, *_):
        AJUSTES.olvidar(self._al_ajustes)
        return False

    def _doble_clic(self, gesture, n_press, x, y, barra):
        if n_press != 2:
            return
        w = barra.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not barra:  # no actuar si cae sobre un botón
            if isinstance(w, Gtk.Button):
                return
            w = w.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.unmaximize() if self.is_maximized() else self.maximize()

    # ---- ajustes en caliente
    def _actualizar_fondo(self):
        self.fondo.set_paintable(fondo.textura(AJUSTES.oscuro))

    def _al_ajustes(self):
        self._actualizar_fondo()
        self.cabecera.refrescar()
        self.al_cambiar_ajustes()
        if self.dialogo is not None and not self._recaptura:   # el cristal vuelve a desenfocar lo de detrás
            self._recaptura = GLib.timeout_add(150, self._recapturar)

    def al_cambiar_ajustes(self):
        """Las ventanas lo redefinen (p. ej. mostrar u ocultar el pie de las tarjetas)."""

    def _recapturar(self):
        self._recaptura = 0
        if self.dialogo is not None:
            self.dialogo.refrescar_fondo()
        return False

    # ---- diálogos de cristal
    def alternar_dialogo(self, clase):
        abierto = self.dialogo
        self.cerrar_dialogo()
        if abierto is not None and isinstance(abierto, clase):
            return
        self.dialogo = clase(self.pagina, self.cerrar_dialogo)
        self.exterior.add_overlay(self.dialogo)
        GLib.timeout_add(60, lambda: (self.dialogo.refrescar_fondo() if self.dialogo else None) and False)

    def cerrar_dialogo(self):
        if self.dialogo is not None:
            self.exterior.remove_overlay(self.dialogo)
            self.dialogo = None


class OutputWindow(Gtk.Window):
    def __init__(self, parent, titulo: str, texto: str):
        AJUSTES.instalar()
        super().__init__(transient_for=parent, default_width=640, default_height=440, title=titulo)
        self.add_css_class("confusb")
        card = tarjeta(titulo)
        card.append(bruto(texto or _("(no output)"), 300))
        card.set_margin_top(12)
        card.set_margin_bottom(12)
        card.set_margin_start(12)
        card.set_margin_end(12)
        self.set_child(card)


# ------------------------------------------------------- ventana principal

class DevicesWindow(VentanaBase):
    """Lista de los dispositivos USB conectados (se abre maximizada). Se actualiza sola al conectar o
    desconectar; al pulsar un dispositivo se abre su detalle en otra ventana."""

    def __init__(self, app, al_abrir):
        super().__init__(app, "confusb · " + _("Connected USB devices"), _("USB devices"), 1280, 800)
        self.maximize()
        self.al_abrir = al_abrir
        self.gen = 0
        self.pies: list[Gtk.Widget] = []

        self.cabecera.boton("🔄  " + _("Refresh"), self.refresh, _("Read the connected devices again"))
        self.botones_comunes()

        self.grid = Masonry(min_col=340)
        self.grid.set_margin_start(20)
        self.grid.set_margin_end(20)
        self.grid.set_margin_bottom(16)
        self.grid.set_margin_top(8)
        self.cuerpo.append(desplazable(self.grid))
        self.refresh()

    def al_cambiar_ajustes(self):
        for p in self.pies:
            p.set_visible(AJUSTES.pie)

    def refresh(self, aviso: str | None = None):
        self.gen += 1
        gen = self.gen
        if not self.grid.items:
            espera = tarjeta()
            fila = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            fila.append(Gtk.Spinner(spinning=True))
            fila.append(label(_("Reading devices…"), "dim", wrap=False))
            espera.append(fila)
            self.grid.add(espera)

        def trabajo():
            return [usbinfo.collect(p, with_lsusb=False) for p in usbinfo.list_usb_devices()]

        def hecho(res):
            if gen != self.gen:
                return
            self.grid.clear()
            self.pies = []
            if isinstance(res, Exception):
                self.grid.add(tarjeta(_("Could not read the devices"), str(res)))
                self.barra.poner(_("Error reading the devices"))
                return
            lista = [i for i in res if i.vid != "1d6b"]  # sin los root hubs del kernel
            for info in lista:
                self.grid.add(self.tarjeta_dispositivo(info))
            if not lista:
                self.grid.add(tarjeta(_("No USB devices connected"),
                                      _("Connect one and it will appear here automatically.")))
            n = len(lista)
            self.barra.poner(_("Connected USB devices: {n}").format(n=n))
            if aviso:
                self.barra.aviso(aviso)

        in_thread(trabajo, hecho)

    def tarjeta_dispositivo(self, info: DeviceInfo) -> Gtk.Widget:
        """Tarjeta de módulo: icono, nombre, VID:PID grande y «Ver información →». Toda ella es pulsable."""
        c = tarjeta(clase="modcard")
        cab = Gtk.Box(spacing=10)
        cab.append(Gtk.Label(label=emoji_de(info), css_classes=["mod-icon"]))
        nombre = label(info.title, "mod-name")
        nombre.set_hexpand(True)
        cab.append(nombre)
        if info.drivers and info.drivers != ["usbfs"]:
            cab.append(estado("Has driver"))
        c.append(cab)
        c.append(label(info.vendor or _("Unknown manufacturer"), "dim"))
        c.append(label(info.usb_id, "mod-big", wrap=False))
        tipos = ", ".join(_(CLASS_NAMES[k]) if k in CLASS_NAMES else f"0x{k:02x}" for k in sorted(info.classes) if k != 0) or "—"
        filas = [(_("Type"), tipos)]
        if info.capacidad:
            filas.append((_("Capacity"), almacenamiento.formatear(info.capacidad)))
        filas += [(_("Port"), os.path.basename(info.syspath)),
                  (_("Driver"), ", ".join(info.drivers) or _("none"))]
        c.append(datos(filas))
        pie = label(_("View information →"), "mod-pie", wrap=False)
        pie.set_margin_top(4)
        pie.set_visible(AJUSTES.pie)
        self.pies.append(pie)
        c.append(pie)

        clic = Gtk.GestureClick()
        clic.connect("released", lambda *_: self.al_abrir(info.syspath))
        c.add_controller(clic)
        c.set_cursor_from_name("pointer")
        return c


# ------------------------------------------------------- ventana de detalle

class DeviceWindow(VentanaBase):
    """Información completa del dispositivo y búsqueda de controladores y aplicaciones.
    Se abre sin maximizar; el botón «Volver» regresa a la ventana principal."""

    def __init__(self, app, info: DeviceInfo):
        super().__init__(app, f"confusb · {info.title}", f"{info.title} · {info.usb_id}", 1100, 780)
        self.info = info
        self.disconnected = False
        self.gen = 0

        # ---- cabecera: volver a la izquierda; copiar, interfaz y acerca de a la derecha
        self.cabecera.boton("←  " + _("Back"), self.volver, _("Back to the list of devices"), izquierda=True)
        self.cabecera.boton("📋  " + _("Copy"), self.copiar, _("Copy all the information to the clipboard"))
        self.botones_comunes()

        # ---- páginas, con navegación en píldoras
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._con_margenes(desplazable(self.pagina_info())), "info")
        self.sw_box = Masonry()
        self.stack.add_named(self._con_margenes(desplazable(self.sw_box)), "sw")
        self.cuerpo.append(pastillas([("info", _("Information")), ("sw", _("Drivers and applications"))],
                                     self.stack.set_visible_child_name))
        self.cuerpo.append(self.stack)

        # ---- barra inferior
        self.barra.poner(f"{info.usb_id} · {info.vendor or _('Unknown manufacturer')}")
        self.punto = Gtk.Box(valign=Gtk.Align.CENTER)
        self.punto.add_css_class("punto")
        self.punto.add_css_class("conectado")
        self.estado_texto = label(_("Connected"), wrap=False)
        self.barra.derecha.append(self.punto)
        self.barra.derecha.append(self.estado_texto)

        self.cargar_software()

    @staticmethod
    def _con_margenes(w: Gtk.Widget) -> Gtk.Widget:
        w.set_margin_start(20)
        w.set_margin_end(20)
        w.set_margin_bottom(12)
        return w

    def volver(self):
        app = self.get_application()
        app.show_devices()
        self.close()

    def copiar(self):
        self.get_clipboard().set(self.info.as_text())
        self.toasts.add_toast(Adw.Toast(title=_("Information copied to the clipboard")))

    # ---------------------------------------------------------------- info
    def pagina_info(self) -> Gtk.Widget:
        info = self.info
        pagina = pila(12)
        cols = Masonry()

        cab = tarjeta()
        fila = Gtk.Box(spacing=12)
        fila.append(Gtk.Label(label=emoji_de(info), css_classes=["mod-icon"]))
        txt = pila(2)
        txt.set_hexpand(True)
        txt.append(label(info.title, "mod-name"))
        txt.append(label(f"{info.vendor or _('Unknown manufacturer')} · USB ID {info.usb_id}", "dim"))
        if info.capacidad:
            txt.append(label(f"{_('Capacity')}: {almacenamiento.formatear(info.capacidad)}", "dim"))
        fila.append(txt)
        cab.append(fila)
        pagina.append(cab)
        pagina.append(cols)

        for titulo, filas in info.sections:
            c = tarjeta(titulo)
            c.append(datos(filas))
            cols.add(c)

        if info.interfaces:
            c = tarjeta(_("Interfaces"), _("Each interface can have its own driver"))
            for i in info.interfaces:
                c.append(rubrica(_("Interface {number} · {label}").format(number=i.number, label=i.label or class_name(i.cls))))
                c.append(datos([
                    (_("Class"), class_name(i.cls)),
                    (_("Subclass / protocol"), f"0x{(i.subcls or 0):02x} / 0x{(i.proto or 0):02x}"),
                    (_("Bound driver"), i.driver or _("none")),
                    (_("Kernel modules"), ", ".join(i.modules) or _("none found")),
                    ("Modalias", i.modalias or "—"),
                    *[("Endpoint", e) for e in i.endpoints],
                ]))
            cols.add(c)

        if info.nodes:
            c = tarjeta(_("Nodes created in the system"))
            c.append(datos([(nodo, sub) for sub, nodo in info.nodes]))
            cols.add(c)

        c = tarjeta(_("Raw data"))
        ex = Gtk.Expander(label=_("udev properties ({n})").format(n=len(info.props)))
        ex.set_child(bruto("\n".join(f"{k}={v}" for k, v in sorted(info.props.items()))))
        c.append(ex)
        if info.lsusb:
            ex2 = Gtk.Expander(label=_("lsusb -v output (full USB descriptors)"))
            ex2.set_child(bruto(info.lsusb, 300))
            c.append(ex2)
        cols.add(c)
        return pagina

    # ------------------------------------------------------------ software
    def cargar_software(self):
        self.sw_box.clear()
        self.gen += 1
        gen = self.gen

        self.buscando = tarjeta()
        fila = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        fila.append(Gtk.Spinner(spinning=True))
        fila.append(label(_("Looking for drivers and applications…"), "dim", wrap=False))
        self.buscando.append(fila)
        self.sw_box.add(self.buscando)

        def trabajo():
            resolver.resolve(self.info, lambda g: GLib.idle_add(self.anadir_grupo, g, gen))

        in_thread(trabajo, lambda _r: self.fin_busqueda(gen))

    def fin_busqueda(self, gen: int):
        if gen == self.gen:
            self.sw_box.remove_item(self.buscando)

    def anadir_grupo(self, grupo: resolver.Group, gen: int):
        if gen != self.gen:  # resultado de una búsqueda anterior
            return False
        c = tarjeta(grupo.title, grupo.subtitle)
        for item in grupo.items:
            c.append(self.fila_item(item))
        self.sw_box.add(c, before_last=True)  # «buscando…» siempre queda al final
        return False

    def fila_item(self, item: resolver.Item) -> Gtk.Widget:
        caja = pila(HUECO)
        caja.add_css_class("caja")
        arriba = Gtk.Box(spacing=8)
        t = label(item.title, "mod-name")
        t.set_hexpand(True)
        arriba.append(t)
        if item.status:
            arriba.append(estado(item.status))
        caja.append(arriba)
        if item.desc:
            caja.append(label(item.desc, "dim", selectable=True))
        if item.actions:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                               column_spacing=8, row_spacing=8, homogeneous=False)
            for act in item.actions:
                b = boton(act.label, enabled=act.enabled, tip=act.tooltip)
                b.connect("clicked", self.al_accionar, act)
                flow.append(b)
            caja.append(flow)
        return caja

    def al_accionar(self, btn: Gtk.Button, act: resolver.Action):
        k, p = act.kind, act.payload
        if k == "url":
            Gio.AppInfo.launch_default_for_uri(p, None)
        elif k == "launch":
            subprocess.Popen(p, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif k == "terminal":
            term = resolver.terminal_cmd()
            if not term:
                self.toasts.add_toast(Adw.Toast(title=_("No terminal emulator found")))
                return
            script = f'{shlex.join(p)}; echo; read -rp {shlex.quote(_("Press Enter to close…"))}'
            subprocess.Popen([*term, "bash", "-c", script], start_new_session=True)
        elif k in ("capture", "apt", "flatpak"):
            if k == "apt":
                cmd, timeout = ["pkexec", "apt-get", "install", "-y", *p], 900
            elif k == "flatpak":
                cmd, timeout = ["flatpak", "install", "-y", "--noninteractive", "flathub", p], 900
            else:
                cmd, timeout = p, 40
            antes = btn.get_label()
            btn.set_sensitive(False)
            btn.set_label(_("Working…"))

            def hecho(res):
                btn.set_label(antes)
                btn.set_sensitive(True)
                if isinstance(res, Exception):
                    self.toasts.add_toast(Adw.Toast(title=_("Error: {error}").format(error=res)))
                    return
                rc, out = res
                cuerpo = f"$ {shlex.join(cmd)}\n" + _("(exit code {code})").format(code=rc) + f"\n\n{out}"
                if k == "capture":
                    OutputWindow(self, " ".join(cmd), cuerpo).present()
                elif rc == 0:
                    self.toasts.add_toast(Adw.Toast(title=_("Installation completed")))
                    self.cargar_software()
                else:
                    OutputWindow(self, _("The installation failed"), cuerpo).present()

            in_thread(run_capture(cmd, timeout), hecho)

    # ------------------------------------------------------------- estado
    def mark_disconnected(self):
        self.disconnected = True
        self.punto.remove_css_class("conectado")
        self.punto.add_css_class("desconectado")
        self.estado_texto.set_label(_("Disconnected"))
        self.barra.aviso(_("The device has been disconnected"), grave=True)
