# SPDX-License-Identifier: GPL-3.0-or-later
"""Ventanas de confusb, con la estructura de Rambleando: fondo a pantalla completa, dock de iconos a
la izquierda, tarjetas «cristal» y barra de estado abajo.

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

from . import fondo, resolver, usbinfo  # noqa: E402
from .ajustes import AJUSTES  # noqa: E402
from .componentes import (HUECO, BarraEstado, Dock, Masonry, PanelAjustes, boton, bruto, datos,  # noqa: E402
                          desplazable, estado, in_thread, label, pila, rubrica, run_capture, tarjeta)
from .usbinfo import CLASS_NAMES, DeviceInfo, class_name  # noqa: E402

RES = os.path.join(os.path.dirname(__file__), "recursos")

ICONOS = {0x01: "audio-card-symbolic", 0x03: "input-keyboard-symbolic", 0x06: "camera-photo-symbolic",
          0x07: "printer-symbolic", 0x08: "drive-removable-media-symbolic", 0x09: "network-wired-symbolic",
          0x0B: "auth-smartcard-symbolic", 0x0E: "camera-web-symbolic", 0xE0: "bluetooth-symbolic"}


# ------------------------------------------------------------------ base

class VentanaBase(Gtk.ApplicationWindow):
    """Estructura común: barra de título del sistema, fondo, [dock | panel de ajustes | contenido]
    y barra de estado. Los ajustes (tema, transparencia, color de letra) se aplican en caliente."""

    def __init__(self, app, titulo: str, ancho: int, alto: int):
        AJUSTES.instalar()
        super().__init__(application=app, title=titulo, default_width=ancho, default_height=alto)
        self.add_css_class("confusb")
        self.panel: PanelAjustes | None = None

        # Barra de título sin opciones, como la del sistema; el doble clic maximiza/restaura.
        cabecera = Gtk.HeaderBar()
        cabecera.set_title_widget(Gtk.Label(label=titulo, css_classes=["title"]))
        self.set_titlebar(cabecera)
        dbl = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        dbl.connect("pressed", self._doble_clic, cabecera)
        cabecera.add_controller(dbl)

        self.fondo = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True)
        self.area = Gtk.Box(spacing=12, vexpand=True, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.barra = BarraEstado()
        columna = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        columna.append(self.area)
        columna.append(self.barra)
        capas = Gtk.Overlay(child=self.fondo)
        capas.add_overlay(columna)
        self.toasts = Adw.ToastOverlay(child=capas)
        self.set_child(self.toasts)

        self.dock = Dock()
        self.area.append(self.dock)

        AJUSTES.suscribir(self._actualizar_fondo)
        self.connect("close-request", self._al_cerrar)
        self._actualizar_fondo()

    def _al_cerrar(self, *_):
        AJUSTES.olvidar(self._actualizar_fondo)
        return False

    def _actualizar_fondo(self):
        self.fondo.set_paintable(fondo.textura(AJUSTES.oscuro))

    def _doble_clic(self, gesture, n_press, x, y, cabecera):
        if n_press != 2:
            return
        w = cabecera.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not cabecera:  # no actuar si cae sobre un botón
            if isinstance(w, Gtk.Button):
                return
            w = w.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.unmaximize() if self.is_maximized() else self.maximize()

    def boton_ajustes(self) -> Gtk.Button:
        """Icono de Ajustes del dock: abre/cierra el panel a la derecha del dock."""
        self._btn_ajustes = self.dock.boton("preferences-system-symbolic", "Ajustes",
                                            lambda: self._mostrar_ajustes(self._btn_ajustes.get_active()), alternar=True)
        return self._btn_ajustes

    def _mostrar_ajustes(self, mostrar: bool):
        if mostrar and self.panel is None:
            self.panel = PanelAjustes(lambda: self._btn_ajustes.set_active(False))
            self.area.insert_child_after(self.panel, self.dock)
        elif not mostrar and self.panel is not None:
            self.area.remove(self.panel)
            self.panel = None


class OutputWindow(Gtk.Window):
    def __init__(self, parent, titulo: str, texto: str):
        AJUSTES.instalar()
        super().__init__(transient_for=parent, default_width=640, default_height=440, title=titulo)
        self.add_css_class("confusb")
        card = tarjeta(titulo)
        card.append(bruto(texto or "(sin salida)", 300))
        card.set_margin_top(12)
        card.set_margin_bottom(12)
        card.set_margin_start(12)
        card.set_margin_end(12)
        self.set_child(card)


# ------------------------------------------------------- ventana principal

class DevicesWindow(VentanaBase):
    """Lista de los dispositivos USB conectados (se abre maximizada). Se actualiza sola al
    conectar o desconectar; desde aquí se abre el detalle de cada uno."""

    def __init__(self, app, al_abrir):
        super().__init__(app, "confusb · Dispositivos USB conectados", 1280, 800)
        self.maximize()
        self.al_abrir = al_abrir
        self.gen = 0

        self.dock.boton("view-refresh-symbolic", "Actualizar la lista", self.refresh)
        self.dock.separador()
        self.boton_ajustes()

        self.grid = Masonry(min_col=340)
        self.area.append(desplazable(self.grid))
        self.refresh()

    def refresh(self, aviso: str | None = None):
        self.gen += 1
        gen = self.gen
        if not self.grid.items:
            espera = tarjeta()
            fila = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            fila.append(Gtk.Spinner(spinning=True))
            fila.append(label("Leyendo dispositivos…", "secundario", wrap=False))
            espera.append(fila)
            self.grid.add(espera)

        def trabajo():
            return [usbinfo.collect(p, with_lsusb=False) for p in usbinfo.list_usb_devices()]

        def hecho(res):
            if gen != self.gen:
                return
            self.grid.clear()
            if isinstance(res, Exception):
                self.grid.add(tarjeta("No se han podido leer los dispositivos", str(res)))
                self.barra.poner("Error al leer los dispositivos")
                return
            lista = [i for i in res if i.vid != "1d6b"]  # sin los root hubs del kernel
            for info in lista:
                self.grid.add(self.tarjeta_dispositivo(info))
            if not lista:
                self.grid.add(tarjeta("No hay dispositivos USB conectados",
                                      "Conecta uno y aparecerá aquí automáticamente."))
            n = len(lista)
            self.barra.poner(f"{n} dispositivo{'s' if n != 1 else ''} USB conectado{'s' if n != 1 else ''}")
            if aviso:
                self.barra.aviso(aviso)

        in_thread(trabajo, hecho)

    def tarjeta_dispositivo(self, info: DeviceInfo) -> Gtk.Widget:
        c = tarjeta()
        cab = Gtk.Box(spacing=8)
        t = label(info.title, "titulo")
        t.set_hexpand(True)
        cab.append(t)
        if info.drivers and info.drivers != ["usbfs"]:
            cab.append(estado("Con controlador"))
        c.append(cab)
        c.append(label(f"{info.vendor or 'Fabricante desconocido'} · {info.usb_id}", "secundario"))
        tipos = ", ".join(CLASS_NAMES.get(k, f"0x{k:02x}") for k in sorted(info.classes) if k != 0) or "—"
        c.append(datos([
            ("Tipo", tipos),
            ("Puerto", os.path.basename(info.syspath)),
            ("Controlador", ", ".join(info.drivers) or "ninguno"),
        ]))
        b = boton("Ver información y software")
        b.set_margin_top(HUECO)
        b.connect("clicked", lambda *_: self.al_abrir(info.syspath))
        c.append(b)
        return c


# ------------------------------------------------------- ventana de detalle

class DeviceWindow(VentanaBase):
    """Información completa del dispositivo y búsqueda de controladores y aplicaciones.
    Se abre sin maximizar; el botón «Volver» del dock regresa a la ventana principal."""

    def __init__(self, app, info: DeviceInfo):
        super().__init__(app, f"confusb · {info.title}", 1100, 780)
        self.info = info
        self.disconnected = False
        self.gen = 0

        # ---- dock: volver | páginas | copiar, ajustes
        self.dock.boton("go-previous-symbolic", "Volver a la lista de dispositivos", self.volver, texto="Volver")
        self.dock.separador()
        self.b_info = self.dock.boton("dialog-information-symbolic", "Información del dispositivo",
                                      lambda: self.stack.set_visible_child_name("info"), grupo=True)
        self.b_sw = self.dock.boton("system-software-install-symbolic", "Controladores y aplicaciones",
                                    lambda: self.stack.set_visible_child_name("sw"), grupo=True)
        self.dock.separador()
        self.dock.boton("edit-copy-symbolic", "Copiar toda la información", self.copiar)
        self.boton_ajustes()

        # ---- páginas
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(desplazable(self.pagina_info()), "info")
        self.sw_box = Masonry()
        self.stack.add_named(desplazable(self.sw_box), "sw")
        self.area.append(self.stack)
        self.b_info.set_active(True)

        # ---- barra de estado
        self.barra.poner(f"{info.usb_id} · {info.vendor or 'Fabricante desconocido'}")
        self.punto = Gtk.Box(valign=Gtk.Align.CENTER)
        self.punto.add_css_class("punto")
        self.punto.add_css_class("conectado")
        self.estado_texto = label("Conectado", wrap=False)
        self.barra.derecha.append(self.punto)
        self.barra.derecha.append(self.estado_texto)

        self.cargar_software()

    def volver(self):
        app = self.get_application()
        app.show_devices()
        self.close()

    def copiar(self):
        self.get_clipboard().set(self.info.as_text())
        self.toasts.add_toast(Adw.Toast(title="Información copiada al portapapeles"))

    # ---------------------------------------------------------------- info
    def pagina_info(self) -> Gtk.Widget:
        info = self.info
        pagina = pila(HUECO + 4)
        cols = Masonry()

        cab = tarjeta()
        fila = Gtk.Box(spacing=12)
        logo = Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(os.path.join(RES, "icono.svg"))))
        logo.set_pixel_size(52)
        logo.set_valign(Gtk.Align.CENTER)
        logo.add_css_class("logo")
        txt = pila(2)
        txt.set_hexpand(True)
        txt.set_valign(Gtk.Align.CENTER)
        txt.append(label(info.title, "titulo-grande"))
        txt.append(label(f"{info.vendor or 'Fabricante desconocido'} · USB ID {info.usb_id}", "secundario"))
        fila.append(logo)
        fila.append(txt)
        cab.append(fila)
        pagina.append(cab)
        pagina.append(cols)

        for titulo, filas in info.sections:
            c = tarjeta(titulo)
            c.append(datos(filas))
            cols.add(c)

        if info.interfaces:
            c = tarjeta("Interfaces", "Cada interfaz puede tener su propio controlador")
            for i in info.interfaces:
                c.append(rubrica(f"Interfaz {i.number} · {i.label or class_name(i.cls)}"))
                c.append(datos([
                    ("Clase", class_name(i.cls)),
                    ("Subclase / protocolo", f"0x{(i.subcls or 0):02x} / 0x{(i.proto or 0):02x}"),
                    ("Controlador vinculado", i.driver or "ninguno"),
                    ("Módulos del kernel", ", ".join(i.modules) or "ninguno encontrado"),
                    ("Modalias", i.modalias or "—"),
                    *[("Endpoint", e.removeprefix("Endpoint ")) for e in i.endpoints],
                ]))
            cols.add(c)

        if info.nodes:
            c = tarjeta("Nodos creados en el sistema")
            c.append(datos([(nodo, sub) for sub, nodo in info.nodes]))
            cols.add(c)

        c = tarjeta("Datos en bruto")
        ex = Gtk.Expander(label=f"Propiedades udev ({len(info.props)})")
        ex.set_child(bruto("\n".join(f"{k}={v}" for k, v in sorted(info.props.items()))))
        c.append(ex)
        if info.lsusb:
            ex2 = Gtk.Expander(label="Salida de lsusb -v (descriptores USB completos)")
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
        fila.append(label("Buscando controladores y aplicaciones…", "secundario", wrap=False))
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
        t = label(item.title)
        t.add_css_class("titulo")
        t.set_hexpand(True)
        arriba.append(t)
        if item.status:
            arriba.append(estado(item.status))
        caja.append(arriba)
        if item.desc:
            caja.append(label(item.desc, "secundario", selectable=True))
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
                self.toasts.add_toast(Adw.Toast(title="No se ha encontrado ningún emulador de terminal"))
                return
            script = f'{shlex.join(p)}; echo; read -rp "Pulsa Intro para cerrar…"'
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
            btn.set_label("Trabajando…")

            def hecho(res):
                btn.set_label(antes)
                btn.set_sensitive(True)
                if isinstance(res, Exception):
                    self.toasts.add_toast(Adw.Toast(title=f"Error: {res}"))
                    return
                rc, out = res
                cuerpo = f"$ {shlex.join(cmd)}\n(código de salida {rc})\n\n{out}"
                if k == "capture":
                    OutputWindow(self, " ".join(cmd), cuerpo).present()
                elif rc == 0:
                    self.toasts.add_toast(Adw.Toast(title="Instalación completada"))
                    self.cargar_software()
                else:
                    OutputWindow(self, "La instalación ha fallado", cuerpo).present()

            in_thread(run_capture(cmd, timeout), hecho)

    # ------------------------------------------------------------- estado
    def mark_disconnected(self):
        self.disconnected = True
        self.punto.remove_css_class("conectado")
        self.punto.add_css_class("desconectado")
        self.estado_texto.set_label("Desconectado")
        self.barra.aviso("El dispositivo se ha desconectado", grave=True)
