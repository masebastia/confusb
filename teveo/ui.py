"""Ventana de detalle del dispositivo, con el estilo visual de Rambleando:
tarjetas redondeadas, rúbricas en mayúsculas, datos etiqueta/valor y acento azul."""
from __future__ import annotations

import os
import shlex
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import resolver  # noqa: E402
from .usbinfo import ENV, DeviceInfo, class_name  # noqa: E402

RES = os.path.join(os.path.dirname(__file__), "recursos")
HUECO, HUECO_SECCION = 8, 20          # mismas separaciones que Rambleando (--hueco, --hueco-seccion)

STATUS_CLASS = {
    "ok": {"Instalado", "Instalada", "Driver activo", "Espacio de usuario", "OK", "Soportado"},
    "aviso": {"Falta instalar", "Sin vincular"},
    "error": {"Sin driver", "No está en los repositorios"},
}

_css_ready = False


def load_css():
    global _css_ready
    if _css_ready:
        return
    prov = Gtk.CssProvider()
    prov.load_from_path(os.path.join(RES, "estilo.css"))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_ready = True


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


# ------------------------------------------------------------- componentes

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


def boton(texto: str, principal=False, enabled=True, tip="") -> Gtk.Button:
    b = Gtk.Button(label=texto, sensitive=enabled)
    b.add_css_class("suggested-action")  # color de acento del sistema para todo lo pulsable
    if tip:
        b.set_tooltip_text(tip)
    return b


def bruto(texto: str, alto: int = 220) -> Gtk.Widget:
    lb = Gtk.Label(label=texto, selectable=True, xalign=0, yalign=0, margin_top=6, margin_bottom=6)
    lb.add_css_class("bruto")
    return Gtk.ScrolledWindow(child=lb, min_content_height=alto, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)


def centrado(content: Gtk.Widget) -> Gtk.Widget:
    clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480, child=content,
                      margin_top=4, margin_bottom=16, margin_start=12, margin_end=12)
    return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)


def desplazable(content: Gtk.Widget) -> Gtk.Widget:
    """Desplazamiento vertical que usa todo el ancho de la ventana."""
    content.set_margin_top(4)
    content.set_margin_bottom(16)
    content.set_margin_start(12)
    content.set_margin_end(12)
    return Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)


class Masonry(Gtk.Box):
    """Reparte las tarjetas en N columnas según el ancho disponible (N = ancho // min_col),
    colocando cada una en la columna más baja para que toda la pantalla quede aprovechada."""

    def __init__(self, min_col: int = 460, max_cols: int = 4, spacing: int = HUECO + 4):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing, homogeneous=True)
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


class OutputWindow(Adw.Window):
    def __init__(self, parent, title: str, text: str):
        super().__init__(transient_for=parent, default_width=620, default_height=420, title=title)
        self.add_css_class("teveo")
        self.add_css_class("oscuro" if Adw.StyleManager.get_default().get_dark() else "claro")
        card = tarjeta(title)
        card.append(bruto(text or "(sin salida)", 280))
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        tv.set_content(centrado(card))
        self.set_content(tv)


# ------------------------------------------------------------------ ventana

class DeviceWindow(Adw.ApplicationWindow):
    def __init__(self, app, info: DeviceInfo):
        load_css()
        super().__init__(application=app, default_width=1280, default_height=800,
                         title=f"USB conectado · {info.title}")
        self.maximize()
        self.add_css_class("teveo")
        self.info = info
        self.gen = 0

        sm = Adw.StyleManager.get_default()
        sm.connect("notify::dark", lambda *_: self.apply_scheme())
        self.apply_scheme()

        # ---- cabecera: control segmentado + copiar
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(desplazable(self.build_info_page()), "info")
        self.sw_box = Masonry()
        self.stack.add_named(desplazable(self.sw_box), "sw")

        seg = Gtk.Box(spacing=0)
        seg.add_css_class("segmentado")
        b_info = Gtk.ToggleButton(label="Información", active=True)
        b_sw = Gtk.ToggleButton(label="Drivers y software", group=b_info)
        for b, page in ((b_info, "info"), (b_sw, "sw")):
            b.connect("toggled", lambda btn, p=page: btn.get_active() and self.stack.set_visible_child_name(p))
            seg.append(b)

        header = Adw.HeaderBar(title_widget=seg)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copiar toda la información")
        copy.add_css_class("suggested-action")
        copy.connect("clicked", self.on_copy)
        header.pack_end(copy)
        self.max_btn = Gtk.Button(tooltip_text="Maximizar / restaurar")
        self.max_btn.add_css_class("suggested-action")
        self.max_btn.connect("clicked", lambda *_: self.toggle_maximize())
        header.pack_end(self.max_btn)
        self.connect("notify::maximized", lambda *_: self.update_max_icon())
        self.update_max_icon()

        # Doble clic en la cabecera = maximizar/restaurar (se gestiona aquí para que funcione siempre)
        dbl = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        dbl.connect("pressed", self.on_header_press, header)
        header.add_controller(dbl)

        self.toasts = Adw.ToastOverlay(child=self.stack)
        tv = Adw.ToolbarView(content=self.toasts)
        tv.set_top_bar_style(Adw.ToolbarStyle.FLAT)
        tv.add_top_bar(header)
        self.set_content(tv)
        self.load_software()

    def apply_scheme(self):
        dark = Adw.StyleManager.get_default().get_dark()
        self.add_css_class("oscuro" if dark else "claro")
        self.remove_css_class("claro" if dark else "oscuro")

    # ---------------------------------------------------------------- info
    def build_info_page(self) -> Gtk.Widget:
        info = self.info
        page = pila(HUECO + 4)
        grid = Masonry()

        # tarjeta de cabecera
        head = Gtk.Box(spacing=12)
        head.add_css_class("tarjeta")
        logo = Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(os.path.join(RES, "icono.svg"))))
        logo.set_pixel_size(52)
        logo.set_valign(Gtk.Align.CENTER)
        logo.add_css_class("logo")
        txt = pila(2)
        txt.set_hexpand(True)
        txt.set_valign(Gtk.Align.CENTER)
        txt.append(label(info.title, "titulo-grande"))
        txt.append(label(f"{info.vendor or 'Fabricante desconocido'} · USB ID {info.usb_id}", "secundario"))
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.dot.add_css_class("punto")
        self.dot.add_css_class("conectado")
        self.dot.set_tooltip_text("Conectado")
        self.dot_label = label("Conectado", "secundario", wrap=False)
        head.append(logo)
        head.append(txt)
        stat = Gtk.Box(spacing=6, valign=Gtk.Align.START, margin_top=4)
        stat.append(self.dot)
        stat.append(self.dot_label)
        head.append(stat)
        page.append(head)

        page.append(grid)

        for title, rows in info.sections:
            c = tarjeta(title)
            c.append(datos(rows))
            grid.add(c)

        if info.interfaces:
            c = tarjeta("Interfaces", "Cada interfaz puede tener su propio driver")
            for i in info.interfaces:
                c.append(rubrica(f"Interfaz {i.number} · {i.label or class_name(i.cls)}"))
                c.append(datos([
                    ("Clase", class_name(i.cls)),
                    ("Subclase / protocolo", f"0x{(i.subcls or 0):02x} / 0x{(i.proto or 0):02x}"),
                    ("Driver vinculado", i.driver or "ninguno"),
                    ("Módulos del kernel", ", ".join(i.modules) or "ninguno encontrado"),
                    ("Modalias", i.modalias or "—"),
                    *[("Endpoint", e.removeprefix("Endpoint ")) for e in i.endpoints],
                ]))
            grid.add(c)

        if info.nodes:
            c = tarjeta("Nodos creados en el sistema")
            c.append(datos([(node, sub) for sub, node in info.nodes]))
            grid.add(c)

        c = tarjeta("Datos en bruto")
        ex = Gtk.Expander(label=f"Propiedades udev ({len(info.props)})")
        ex.set_child(bruto("\n".join(f"{k}={v}" for k, v in sorted(info.props.items()))))
        c.append(ex)
        if info.lsusb:
            ex2 = Gtk.Expander(label="Salida de lsusb -v (descriptores USB completos)")
            ex2.set_child(bruto(info.lsusb, 300))
            c.append(ex2)
        grid.add(c)
        return page

    def toggle_maximize(self):
        self.unmaximize() if self.is_maximized() else self.maximize()

    def update_max_icon(self):
        self.max_btn.set_icon_name("window-restore-symbolic" if self.is_maximized() else "window-maximize-symbolic")

    def on_header_press(self, gesture, n_press, x, y, header):
        if n_press != 2:
            return
        w = header.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not header:  # no actuar si el doble clic cae sobre un botón
            if isinstance(w, Gtk.Button):
                return
            w = w.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.toggle_maximize()

    def on_copy(self, _btn):
        self.get_clipboard().set(self.info.as_text())
        self.toasts.add_toast(Adw.Toast(title="Información copiada al portapapeles"))

    # ------------------------------------------------------------ software
    def load_software(self):
        self.sw_box.clear()
        self.gen += 1
        gen = self.gen

        self.search = tarjeta()
        row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner(spinning=True)
        row.append(self.spinner)
        row.append(label("Buscando drivers y aplicaciones…", "secundario", wrap=False))
        self.search.append(row)
        self.sw_box.add(self.search)

        def worker():
            resolver.resolve(self.info, lambda g: GLib.idle_add(self.add_group, g, gen))

        in_thread(worker, lambda _r: self.finish_search(gen))

    def finish_search(self, gen: int):
        if gen != self.gen:
            return
        self.sw_box.remove_item(self.search)

    def add_group(self, group: resolver.Group, gen: int):
        if gen != self.gen:  # resultado de una búsqueda anterior
            return False
        c = tarjeta(group.title, group.subtitle)
        for item in group.items:
            c.append(self.make_item(item))
        self.sw_box.add(c, before_last=True)  # «buscando…» siempre queda al final
        return False

    def make_item(self, item: resolver.Item) -> Gtk.Widget:
        box = pila(HUECO)
        box.add_css_class("caja")
        top = Gtk.Box(spacing=8)
        t = label(item.title)
        t.add_css_class("titulo")
        t.set_hexpand(True)
        top.append(t)
        if item.status:
            top.append(estado(item.status))
        box.append(top)
        if item.desc:
            box.append(label(item.desc, "secundario", selectable=True))
        if item.actions:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                               column_spacing=8, row_spacing=8, homogeneous=False)
            for act in item.actions:
                b = boton(act.label, principal=act.kind in ("apt", "flatpak"), enabled=act.enabled, tip=act.tooltip)
                b.connect("clicked", self.on_action, act)
                flow.append(b)
            box.append(flow)
        return box

    def on_action(self, btn: Gtk.Button, act: resolver.Action):
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
            old = btn.get_label()
            btn.set_sensitive(False)
            btn.set_label("Trabajando…")

            def done(res):
                btn.set_label(old)
                btn.set_sensitive(True)
                if isinstance(res, Exception):
                    self.toasts.add_toast(Adw.Toast(title=f"Error: {res}"))
                    return
                rc, out = res
                body = f"$ {shlex.join(cmd)}\n(código de salida {rc})\n\n{out}"
                if k == "capture":
                    OutputWindow(self, " ".join(cmd), body).present()
                elif rc == 0:
                    self.toasts.add_toast(Adw.Toast(title="Instalación completada"))
                    self.load_software()
                else:
                    OutputWindow(self, "La instalación ha fallado", body).present()

            in_thread(run_capture(cmd, timeout), done)

    # ------------------------------------------------------------- estado
    def mark_disconnected(self):
        self.dot.remove_css_class("conectado")
        self.dot.add_css_class("desconectado")
        self.dot.set_tooltip_text("Desconectado")
        self.dot_label.set_label("Desconectado")
