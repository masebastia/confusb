# SPDX-License-Identifier: GPL-3.0-or-later
"""Componentes de interfaz compartidos, con la estética de Contabilizando: cabecera con emblema y marca,
navegación en píldoras, tarjetas, barra inferior con etiqueta y subventanas de cristal difuminado."""
from __future__ import annotations

import subprocess
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene, Gtk, Pango  # noqa: E402

from . import __version__, fondo  # noqa: E402
from .ajustes import AJUSTES, AL_CONECTAR, COLORES, DEFECTOS, MARCOS  # noqa: E402
from .usbinfo import ENV  # noqa: E402

HUECO = 8
REPO_URL = "https://github.com/masebastia/confusb"

STATUS_CLASS = {
    "ok": {"Instalado", "Instalada", "Controlador activo", "Espacio de usuario", "OK", "Soportado", "Con controlador"},
    "aviso": {"Falta instalar", "Sin vincular"},
    "error": {"Sin controlador", "No está en los repositorios"},
}


# ------------------------------------------------------------------ hilos

def in_thread(fn, done):
    """Ejecuta fn() en un hilo y llama a done(resultado) en el hilo principal."""
    def work():
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001
            res = e
        GLib.idle_add(done, res)
    threading.Thread(target=work, daemon=True).start()


def run_capture(cmd: list[str], timeout: float = 40):
    def go():
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.returncode, (r.stdout + r.stderr).strip()
    return go


# ------------------------------------------------------------ elementos básicos

def label(text: str, *classes: str, selectable=False, xalign=0.0, wrap=True) -> Gtk.Label:
    lb = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if wrap:
        # sin esto GTK pide el ancho mínimo (1 carácter) y el texto se parte letra a letra
        lb.set_hexpand(True)
        lb.set_width_chars(12)
        lb.set_max_width_chars(80)
    for c in classes:
        lb.add_css_class(c)
    return lb


def pila(spacing: int = HUECO) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def tarjeta(titulo: str = "", subtitulo: str = "", clase: str = "card") -> Gtk.Box:
    box = pila()
    box.add_css_class(clase)
    if titulo:
        box.append(label(titulo, "section"))
    if subtitulo:
        box.append(label(subtitulo, "dim"))
    return box


def rubrica(texto: str) -> Gtk.Label:
    lb = label(texto.upper(), "card-title", "rubrica")
    lb.set_margin_top(10)
    return lb


def datos(rows: list[tuple[str, str]]) -> Gtk.Grid:
    """Lista etiqueta (izquierda) / valor (derecha)."""
    g = Gtk.Grid(column_spacing=12, row_spacing=HUECO)
    for n, (k, v) in enumerate(rows):
        kl = label(k, "datos-etiqueta")
        kl.set_valign(Gtk.Align.START)
        kl.set_hexpand(False)
        kl.set_max_width_chars(28)
        vl = label(v, "datos-valor", selectable=True, xalign=1.0)
        vl.set_hexpand(True)
        vl.set_halign(Gtk.Align.END)
        vl.set_justify(Gtk.Justification.RIGHT)
        g.attach(kl, 0, n, 1, 1)
        g.attach(vl, 1, n, 1, 1)
    return g


def estado(texto: str) -> Gtk.Label:
    lb = label(texto, "estado", wrap=False, xalign=0.5)
    lb.set_valign(Gtk.Align.CENTER)
    for cls, names in STATUS_CLASS.items():
        if texto in names:
            lb.add_css_class(cls)
    return lb


def boton(texto: str, enabled=True, tip="") -> Gtk.Button:
    b = Gtk.Button(label=texto, sensitive=enabled)
    b.add_css_class("suggested-action")  # color de acento del sistema para todo lo pulsable
    if tip:
        b.set_tooltip_text(tip)
    return b


def bruto(texto: str, alto: int = 220) -> Gtk.Widget:
    lb = Gtk.Label(label=texto, selectable=True, xalign=0, yalign=0, margin_top=6, margin_bottom=6)
    lb.add_css_class("bruto")
    return Gtk.ScrolledWindow(child=lb, min_content_height=alto, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)


def desplazable(content: Gtk.Widget) -> Gtk.ScrolledWindow:
    """Desplazamiento vertical que usa todo el ancho disponible."""
    return Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True, vexpand=True)


# ---------------------------------------------------------- reparto en columnas

class Masonry(Gtk.Box):
    """Reparte las tarjetas en N columnas según el ancho disponible (N = ancho // min_col),
    colocando cada una en la columna más baja para aprovechar toda la pantalla."""

    def __init__(self, min_col: int = 460, max_cols: int = 4, spacing: int = 12):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, homogeneous=True, valign=Gtk.Align.START)
        self.min_col, self.max_cols, self.gap = min_col, max_cols, spacing
        self.items: list[Gtk.Widget] = []
        self.cols: list[Gtk.Box] = []
        self._n = 0
        self._width = 0
        self._dirty = True
        self.add_tick_callback(self._tick)

    def do_measure(self, orientation, for_size):
        # El ancho de las columnas no depende de la altura: evita avisos de GTK al redimensionar.
        if orientation == Gtk.Orientation.HORIZONTAL:
            for_size = -1
        return Gtk.Box.do_measure(self, orientation, for_size)

    def add(self, w: Gtk.Widget, before_last: bool = False):
        self.items.insert(len(self.items) - 1 if before_last and self.items else len(self.items), w)
        self._dirty = True

    def remove_item(self, w: Gtk.Widget):
        if w in self.items:
            self.items.remove(w)
            if w.get_parent() is not None:
                w.get_parent().remove(w)
            self._dirty = True

    def clear(self):
        for w in list(self.items):
            self.remove_item(w)

    def _tick(self, _w, _clock):
        width = self.get_width()
        if width <= 0:
            return GLib.SOURCE_CONTINUE
        n = max(1, min(self.max_cols, width // self.min_col))
        if self._dirty or n != self._n or abs(width - self._width) > 40:
            self._relayout(n, width)
        return GLib.SOURCE_CONTINUE

    def _relayout(self, n: int, width: int):
        self._dirty = False
        self._n, self._width = n, width
        for col in self.cols:
            child = col.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                col.remove(child)
                child = nxt
            super().remove(col)
        self.cols = []
        for _ in range(n):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.gap, valign=Gtk.Align.START)
            self.cols.append(col)
            self.append(col)
        colw = max(1, (width - self.gap * (n - 1)) // n)
        heights = [0] * n
        for w in self.items:
            i = heights.index(min(heights))
            self.cols[i].append(w)
            heights[i] += w.measure(Gtk.Orientation.VERTICAL, colw)[1] + self.gap


# ------------------------------------------------- cabecera, píldoras, barra inferior

class Cabecera(Gtk.Box):
    """Fila superior: [botones a la izquierda] emblema + marca + subtítulo ........ [botones]."""

    def __init__(self, subtitulo: str):
        super().__init__(spacing=12, margin_start=20, margin_end=20, margin_top=14, margin_bottom=4)
        self.izquierda = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.append(self.izquierda)
        self.emblema = Gtk.Image(pixel_size=46)
        self.append(self.emblema)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        txt.append(label("CONFUSB", "marca", wrap=False))
        self.sub = label(subtitulo, "marca-sub", wrap=False)
        txt.append(self.sub)
        self.append(txt)
        self.append(Gtk.Box(hexpand=True))
        self.derecha = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.append(self.derecha)
        self.refrescar()

    def refrescar(self):
        tex = fondo.textura_svg("icono.svg", 184, AJUSTES.oscuro)
        if tex:
            self.emblema.set_from_paintable(tex)

    def boton(self, texto: str, al_pulsar: Callable[[], None], tip: str = "", izquierda: bool = False) -> Gtk.Button:
        b = boton(texto, tip=tip)
        b.set_cursor_from_name("pointer")
        b.connect("clicked", lambda *_: al_pulsar())
        (self.izquierda if izquierda else self.derecha).append(b)
        return b


def pastillas(opciones: list[tuple[str, str]], al_elegir: Callable[[str], None]) -> Gtk.Box:
    """Navegación en píldoras (la selecciona se rellena de acento)."""
    box = Gtk.Box(spacing=0)
    box.add_css_class("pastillas")
    botones, primero = [], None
    for oid, nombre in opciones:
        b = Gtk.ToggleButton(label=nombre)
        b.add_css_class("pastilla")
        b.set_cursor_from_name("pointer")
        if primero is None:
            primero = b
        else:
            b.set_group(primero)
        botones.append((oid, b))
        box.append(b)
    botones[0][1].set_active(True)
    for oid, b in botones:
        b.connect("toggled", lambda btn, i=oid: btn.get_active() and al_elegir(i))
    return box


class BarraEstado(Gtk.Box):
    """Barra inferior (como la de noticias de Contabilizando): etiqueta de color, texto y avisos."""

    def __init__(self, etiqueta: str = "USB"):
        super().__init__(spacing=12)
        self.add_css_class("barra-estado")
        self.append(Gtk.Label(label=etiqueta, css_classes=["barra-etiqueta"]))
        self.izq = label("", wrap=False)
        self.append(self.izq)
        self.append(Gtk.Box(hexpand=True))
        self.avisos = Gtk.Box(spacing=6, visible=False)
        self.icono_aviso = Gtk.Image(icon_name="dialog-information-symbolic", pixel_size=14)
        self.texto_aviso = label("", wrap=False)
        cerrar = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Cerrar el aviso")
        cerrar.add_css_class("cerrar")
        cerrar.connect("clicked", lambda *_: self.avisos.set_visible(False))
        for w in (self.icono_aviso, self.texto_aviso, cerrar):
            self.avisos.append(w)
        self.append(self.avisos)
        self.derecha = Gtk.Box(spacing=6, margin_end=12, valign=Gtk.Align.CENTER)
        self.append(self.derecha)
        self._n = 0

    def poner(self, texto: str):
        self.izq.set_label(texto)

    def aviso(self, texto: str, grave: bool = False):
        self._n += 1
        n = self._n
        self.texto_aviso.set_label(texto)
        self.icono_aviso.set_from_icon_name("dialog-warning-symbolic" if grave else "dialog-information-symbolic")
        (self.avisos.add_css_class if grave else self.avisos.remove_css_class)("aviso-grave")
        self.avisos.set_visible(True)
        GLib.timeout_add_seconds(10, lambda: (self.avisos.set_visible(False) if n == self._n else None) and False)


# ------------------------------------------------------- cristal difuminado

class CapaDifuminada(Gtk.Widget):
    """Dibuja, recortada al panel y alineada con la ventana, la captura desenfocada de esta: GNOME no
    difumina lo que hay detrás de una ventana, así que se imita (como en Contabilizando)."""

    def __init__(self, anfitrion: Gtk.Widget):
        super().__init__(hexpand=True, vexpand=True)
        self.anfitrion = anfitrion
        self.tex = None
        self.tw = self.th = 0
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_measure(self, orientation, for_size):
        return (0, 0, -1, -1)

    def capturar(self, radio: float = 18):
        w, h = self.anfitrion.get_width(), self.anfitrion.get_height()
        native = self.anfitrion.get_native()
        if w <= 0 or h <= 0 or native is None:
            return
        try:
            paintable = Gtk.WidgetPaintable.new(self.anfitrion)
            snap = Gtk.Snapshot()
            snap.push_blur(radio)
            paintable.snapshot(snap, w, h)
            snap.pop()
            self.tex = native.get_renderer().render_texture(snap.to_node(), Graphene.Rect().init(0, 0, w, h))
            self.tw, self.th = w, h
        except Exception:  # noqa: BLE001  (sin difuminado: solo queda el cristal translúcido)
            self.tex = None
        self.queue_draw()

    def do_snapshot(self, snapshot):
        if self.tex is None:
            return
        ok, p = self.compute_point(self.anfitrion, Graphene.Point().init(0, 0))
        if not ok:
            return
        snapshot.save()
        snapshot.translate(Graphene.Point().init(-p.x, -p.y))
        snapshot.append_texture(self.tex, Graphene.Rect().init(0, 0, self.tw, self.th))
        snapshot.restore()


class CristalDialogo(Gtk.Box):
    """Subventana de cristal difuminado, dibujada sobre la ventana principal. Con `derecha` flota a la
    derecha (para ver cambiar lo de al lado); si es `modal`, un clic fuera la cierra."""

    def __init__(self, anfitrion: Gtk.Widget, titulo: str, al_cerrar: Callable[[], None],
                 derecha: bool = False, modal: bool = False):
        super().__init__(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL, hexpand=True, vexpand=True)
        self.al_cerrar = al_cerrar
        self.set_can_target(modal)
        if modal:
            clic = Gtk.GestureClick()
            clic.connect("pressed", lambda *_: al_cerrar())
            self.add_controller(clic)

        self.capa = CapaDifuminada(anfitrion)
        self.cuerpo = pila()
        self.cuerpo.add_css_class("cristal")
        self.cuerpo.append(label(titulo, "section"))
        panel = Gtk.Overlay(child=self.capa, hexpand=True, halign=Gtk.Align.END if derecha else Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, margin_end=24 if derecha else 0)
        panel.add_overlay(self.cuerpo)
        panel.set_measure_overlay(self.cuerpo, True)
        panel.set_overflow(Gtk.Overflow.HIDDEN)
        panel.add_css_class("panel-cristal")
        self.append(panel)
        # que un clic dentro del panel no llegue a la capa que cierra
        if modal:
            dentro = Gtk.GestureClick()
            dentro.connect("pressed", lambda g, *_: g.set_state(Gtk.EventSequenceState.CLAIMED))
            panel.add_controller(dentro)
        panel.set_can_target(True)
        self.panel = panel

    def anadir_botones(self, botones: list[tuple[str, Callable[[], None]]]):
        fila = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=10)
        for texto, fn in botones:
            b = boton(texto)
            b.connect("clicked", lambda *_, f=fn: f())
            fila.append(b)
        self.cuerpo.append(fila)

    def refrescar_fondo(self):
        self.capa.capturar()


def _con_valor(titulo: str, minimo: int, maximo: int, actual: int, sufijo: str,
               al_cambiar: Callable[[int], None]) -> Gtk.Box:
    caja = pila(4)
    fila = Gtk.Box()
    fila.append(label(titulo, wrap=False))
    fila.append(Gtk.Box(hexpand=True))
    salida = label(f"{actual}{sufijo}", "dim", wrap=False, xalign=1.0)
    fila.append(salida)
    caja.append(fila)
    esc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimo, maximo, 1)
    esc.set_draw_value(False)
    esc.set_value(actual)

    def cambia(s):
        v = int(round(s.get_value()))
        salida.set_label(f"{v}{sufijo}")
        al_cambiar(v)
    esc.connect("value-changed", cambia)
    caja.append(esc)
    return caja


class InterfazDialogo(CristalDialogo):
    """«🎨 Interfaz»: los ajustes de aspecto de Contabilizando y qué hacer al conectar un dispositivo.
    Los cambios se ven al momento."""

    def __init__(self, anfitrion, al_cerrar):
        super().__init__(anfitrion, "🎨  Interfaz", al_cerrar, derecha=True)
        self.cuerpo.set_size_request(380, -1)
        self._ignorar = False
        c = self.cuerpo
        c.append(rubrica("Tarjetas"))
        c.append(_con_valor("Opacidad de las tarjetas", 20, 100, AJUSTES.opacidad, " %",
                            lambda v: AJUSTES.cambiar(opacidad=v)))
        c.append(_con_valor("Esquinas", 0, 24, AJUSTES.esquinas, " px", lambda v: AJUSTES.cambiar(esquinas=v)))

        fila = Gtk.Box(spacing=12)
        fila.append(label("Color de los títulos", wrap=False))
        fila.append(Gtk.Box(hexpand=True))
        claves = list(COLORES)
        self.colores = Gtk.DropDown.new_from_strings([COLORES[k][0] for k in claves])
        self.colores.set_selected(claves.index(AJUSTES.titulo))
        self.colores.connect("notify::selected", lambda d, *_: not self._ignorar and
                             AJUSTES.cambiar(titulo=claves[d.get_selected()]))
        fila.append(self.colores)
        c.append(fila)

        c.append(label("Marco", wrap=False))
        self.marcos = self._radios(MARCOS, AJUSTES.marco, lambda k: AJUSTES.cambiar(marco=k), c)
        self.sombra = Gtk.CheckButton(label="Sombra bajo las tarjetas", active=AJUSTES.sombra)
        self.sombra.connect("toggled", lambda w: not self._ignorar and AJUSTES.cambiar(sombra=w.get_active()))
        c.append(self.sombra)
        self.pie = Gtk.CheckButton(label="Mostrar «Ver información →» en las tarjetas", active=AJUSTES.pie)
        self.pie.connect("toggled", lambda w: not self._ignorar and AJUSTES.cambiar(pie=w.get_active()))
        c.append(self.pie)

        c.append(rubrica("Al conectar un dispositivo"))
        self.al_conectar = self._radios(AL_CONECTAR, AJUSTES.al_conectar, lambda k: AJUSTES.cambiar(al_conectar=k), c)

        self.anadir_botones([("Restablecer", self._restablecer), ("Cerrar", al_cerrar)])

    @staticmethod
    def _radios(opciones: dict, actual: str, al_elegir, destino: Gtk.Box) -> dict[str, Gtk.CheckButton]:
        radios, primero = {}, None
        for k, nombre in opciones.items():
            r = Gtk.CheckButton(label=nombre)
            if primero is None:
                primero = r
            else:
                r.set_group(primero)
            radios[k] = r
            destino.append(r)
        radios[actual].set_active(True)
        for k, r in radios.items():
            r.connect("toggled", lambda w, i=k: w.get_active() and al_elegir(i))
        return radios

    def _restablecer(self):
        AJUSTES.restablecer()
        self._ignorar = True
        self.colores.set_selected(list(COLORES).index(DEFECTOS["titulo"]))
        self.sombra.set_active(DEFECTOS["sombra"])
        self.pie.set_active(DEFECTOS["pie"])
        self.marcos[DEFECTOS["marco"]].set_active(True)
        self.al_conectar[DEFECTOS["al_conectar"]].set_active(True)
        self._ignorar = False


class AcercaDeDialogo(CristalDialogo):
    def __init__(self, anfitrion, al_cerrar):
        super().__init__(anfitrion, "Acerca de confusb", al_cerrar, modal=True)
        tex = fondo.textura_svg("logo.svg", 480, AJUSTES.oscuro)
        if tex:
            img = Gtk.Image(pixel_size=240, halign=Gtk.Align.CENTER)
            img.set_from_paintable(tex)
            self.cuerpo.append(img)
        self.cuerpo.set_size_request(400, -1)
        self.cuerpo.append(label(f"Versión {__version__}", "dim", xalign=0.5))
        desc = label("Avisa al conectar un dispositivo USB, muestra su información y busca su "
                     "controlador y las aplicaciones para usarlo.", xalign=0.5)
        desc.set_justify(Gtk.Justification.CENTER)
        self.cuerpo.append(desc)
        self.cuerpo.append(label("Licencia GPL-3.0-or-later", "dim", xalign=0.5))
        enlace = Gtk.LinkButton.new_with_label(REPO_URL, "Código fuente en GitHub")
        enlace.set_halign(Gtk.Align.CENTER)
        self.cuerpo.append(enlace)
        self.anadir_botones([("Cerrar", al_cerrar)])
