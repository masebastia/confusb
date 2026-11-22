# SPDX-License-Identifier: GPL-3.0-or-later
"""Componentes de interfaz compartidos: tarjetas, datos, reparto en columnas, dock, barra de estado
y panel de ajustes. Reproducen los de Rambleando (tarjetas «cristal», dock a la izquierda, barra de
estado abajo y panel de Ajustes)."""
from __future__ import annotations

import subprocess
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .ajustes import AJUSTES, AL_CONECTAR, COLORES_TEXTO, TEMAS, TRANSPARENCIA  # noqa: E402
from .usbinfo import ENV  # noqa: E402

HUECO, HUECO_SECCION = 8, 20          # mismas separaciones que Rambleando (--hueco, --hueco-seccion)
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


def tarjeta(titulo: str = "", subtitulo: str = "") -> Gtk.Box:
    box = pila()
    box.add_css_class("cristal")
    box.add_css_class("tarjeta")
    if titulo:
        box.append(label(titulo, "titulo"))
    if subtitulo:
        box.append(label(subtitulo, "secundario"))
    return box


def rubrica(texto: str) -> Gtk.Label:
    lb = label(texto.upper(), "rubrica")
    lb.set_margin_top(HUECO_SECCION - HUECO)
    return lb


def datos(rows: list[tuple[str, str]]) -> Gtk.Grid:
    """Lista etiqueta (izquierda) / valor (derecha), como el .datos de Rambleando."""
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


def segmentado(opciones: list[tuple[str, str]], actual: str, al_elegir: Callable[[str], None]) -> Gtk.Box:
    box = Gtk.Box()
    box.add_css_class("segmentado")
    botones, primero = [], None
    for oid, nombre in opciones:
        b = Gtk.ToggleButton(label=nombre, hexpand=True)
        if primero is None:
            primero = b
        else:
            b.set_group(primero)
        botones.append((oid, b))
        box.append(b)
    for oid, b in botones:
        b.set_active(oid == actual)
    for oid, b in botones:
        b.connect("toggled", lambda btn, i=oid: btn.get_active() and al_elegir(i))
    return box


# ---------------------------------------------------------- reparto en columnas

class Masonry(Gtk.Box):
    """Reparte las tarjetas en N columnas según el ancho disponible (N = ancho // min_col),
    colocando cada una en la columna más baja para aprovechar toda la pantalla."""

    def __init__(self, min_col: int = 460, max_cols: int = 4, spacing: int = HUECO + 4):
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


# ------------------------------------------------------------------------ dock

class Dock(Gtk.Box):
    """Columna de iconos flotante a la izquierda (el .dock de Rambleando)."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.START, halign=Gtk.Align.START)
        self.add_css_class("cristal")
        self.add_css_class("dock")
        self._grupo: Gtk.ToggleButton | None = None

    def boton(self, icono: str, tip: str, al_pulsar: Callable[[], None] | None = None, texto: str | None = None,
              alternar: bool = False, grupo: bool = False) -> Gtk.Button:
        """Icono de 42 px. `alternar`: botón de dos estados; `grupo`: uno solo activo entre los de grupo."""
        b: Gtk.Button = Gtk.ToggleButton() if (alternar or grupo) else Gtk.Button()
        if grupo:
            if self._grupo is None:
                self._grupo = b
            else:
                b.set_group(self._grupo)
        b.add_css_class("icono")
        b.set_tooltip_text(tip)
        img = Gtk.Image(icon_name=icono, pixel_size=22)
        if texto:
            b.add_css_class("con-texto")
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER)
            caja.append(img)
            caja.append(Gtk.Label(label=texto))
            b.set_child(caja)
        else:
            b.set_child(img)
        if al_pulsar:
            if alternar:
                b.connect("toggled", lambda w: al_pulsar())
            elif grupo:
                b.connect("toggled", lambda w: al_pulsar() if w.get_active() else None)
            else:
                b.connect("clicked", lambda w: al_pulsar())
        self.append(b)
        return b

    def separador(self):
        self.append(Gtk.Separator())


# ------------------------------------------------------------- barra de estado

class BarraEstado(Gtk.Box):
    """Barra inferior (como la de Rambleando): datos a la izquierda y avisos a la derecha."""

    def __init__(self):
        super().__init__(spacing=16)
        self.add_css_class("barra-estado")
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
        self.derecha = Gtk.Box(spacing=6)
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


# ------------------------------------------------------------ panel de ajustes

class PanelAjustes(Gtk.Box):
    """Tarjeta de Ajustes: apariencia, transparencia, color de la letra y qué hacer al conectar."""

    def __init__(self, al_cerrar: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=HUECO, valign=Gtk.Align.START, halign=Gtk.Align.START)
        self.add_css_class("cristal")
        self.add_css_class("tarjeta")
        self.set_size_request(300, -1)

        cab = Gtk.Box(spacing=8)
        cab.append(label("Ajustes", "titulo"))
        x = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Cerrar")
        x.add_css_class("cerrar")
        x.connect("clicked", lambda *_: al_cerrar())
        cab.append(x)
        self.append(cab)

        cuerpo = pila()
        cuerpo.append(rubrica("Apariencia"))
        cuerpo.append(segmentado(TEMAS, AJUSTES.tema, lambda v: AJUSTES.cambiar(tema=v)))

        fila = Gtk.Box()
        fila.append(rubrica("Transparencia"))
        self.salida = label(f"{AJUSTES.transparencia} %", wrap=False, xalign=1.0)
        self.salida.set_halign(Gtk.Align.END)
        self.salida.set_valign(Gtk.Align.END)
        fila.append(self.salida)
        cuerpo.append(fila)
        esc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, TRANSPARENCIA["minimo"], TRANSPARENCIA["maximo"],
                                       TRANSPARENCIA["paso"])
        esc.set_draw_value(False)
        esc.set_value(AJUSTES.transparencia)
        esc.connect("value-changed", self._transparencia)
        cuerpo.append(esc)

        cuerpo.append(rubrica("Color de la letra"))
        muestras = Gtk.Box(spacing=10)
        self._muestras: dict[str, Gtk.Button] = {}
        for cid, nombre, _t in COLORES_TEXTO:
            b = Gtk.Button(tooltip_text=nombre, valign=Gtk.Align.CENTER)
            b.add_css_class("muestra")
            b.add_css_class(f"muestra-{cid}")
            b.connect("clicked", lambda _b, i=cid: self._color(i))
            self._muestras[cid] = b
            muestras.append(b)
        cuerpo.append(muestras)
        self._color_marcado()

        cuerpo.append(rubrica("Al conectar un dispositivo"))
        primero = None
        for oid, nombre in AL_CONECTAR:
            r = Gtk.CheckButton(label=nombre)
            if primero is None:
                primero = r
            else:
                r.set_group(primero)
            r.set_active(oid == AJUSTES.al_conectar)
            r.connect("toggled", lambda w, i=oid: w.get_active() and AJUSTES.cambiar(al_conectar=i))
            cuerpo.append(r)

        cuerpo.append(rubrica("Acerca de"))
        cuerpo.append(label(f"confusb {__version__} · Licencia GPL-3.0-or-later", "secundario"))
        enlace = Gtk.LinkButton.new_with_label(REPO_URL, "Código fuente en GitHub")
        enlace.set_halign(Gtk.Align.START)
        cuerpo.append(enlace)

        self.append(Gtk.ScrolledWindow(child=cuerpo, propagate_natural_height=True, vexpand=False,
                                       hscrollbar_policy=Gtk.PolicyType.NEVER))

    def _transparencia(self, esc: Gtk.Scale):
        v = int(round(esc.get_value()))
        self.salida.set_label(f"{v} %")
        if v != AJUSTES.transparencia:
            AJUSTES.cambiar(transparencia=v)

    def _color(self, cid: str):
        AJUSTES.cambiar(color_texto=cid)
        self._color_marcado()

    def _color_marcado(self):
        for cid, b in self._muestras.items():
            (b.add_css_class if cid == AJUSTES.color_texto else b.remove_css_class)("elegida")
