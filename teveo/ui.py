"""Ventana de detalle del dispositivo: información completa + drivers/software."""
from __future__ import annotations

import shlex
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import resolver  # noqa: E402
from .usbinfo import ENV, DeviceInfo, class_name  # noqa: E402

ICONS = {0x01: "audio-card-symbolic", 0x03: "input-keyboard-symbolic", 0x06: "camera-photo-symbolic",
         0x07: "printer-symbolic", 0x08: "drive-removable-media-symbolic", 0x09: "network-wired-symbolic",
         0x0B: "auth-smartcard-symbolic", 0x0E: "camera-web-symbolic", 0xE0: "bluetooth-symbolic"}


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


def plain_row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle))
    row.set_subtitle_selectable(True)
    row.add_css_class("property")
    return row


class OutputWindow(Adw.Window):
    def __init__(self, parent, title: str, text: str):
        super().__init__(transient_for=parent, modal=False, default_width=640, default_height=420, title=title)
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=12, right_margin=12, top_margin=12, bottom_margin=12)
        view.get_buffer().set_text(text or "(sin salida)")
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        tv.set_content(Gtk.ScrolledWindow(child=view))
        self.set_content(tv)


class DeviceWindow(Adw.ApplicationWindow):
    def __init__(self, app, info: DeviceInfo):
        super().__init__(application=app, default_width=760, default_height=780,
                         title=f"USB conectado · {info.title}")
        self.info = info
        self.sw_groups: list[Adw.PreferencesGroup] = []

        self.toasts = Adw.ToastOverlay()
        self.banner = Adw.Banner(title="El dispositivo se ha desconectado", revealed=False)
        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self.build_info_page(), "info", "Información", "dialog-information-symbolic")
        self.stack.add_titled_with_icon(self.build_software_page(), "sw", "Drivers y software",
                                        "system-software-install-symbolic")

        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header = Adw.HeaderBar(title_widget=switcher)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copiar toda la información")
        copy.connect("clicked", self.on_copy)
        header.pack_end(copy)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.banner)
        self.stack.set_vexpand(True)
        body.append(self.stack)
        self.toasts.set_child(body)
        tv = Adw.ToolbarView()
        tv.add_top_bar(header)
        tv.set_content(self.toasts)
        self.set_content(tv)
        self.load_software()

    # ---------------------------------------------------------------- info
    def build_info_page(self) -> Gtk.Widget:
        info = self.info
        page = Adw.PreferencesPage()

        head = Adw.PreferencesGroup()
        icon = next((ICONS[c] for c in sorted(info.classes) if c in ICONS), "drive-harddisk-usb-symbolic")
        row = Adw.ActionRow(title=GLib.markup_escape_text(info.title),
                            subtitle=GLib.markup_escape_text(f"{info.vendor or 'Fabricante desconocido'} · USB ID {info.usb_id}"))
        row.add_prefix(Gtk.Image(icon_name=icon, pixel_size=48))
        head.add(row)
        page.add(head)

        for title, rows in info.sections:
            g = Adw.PreferencesGroup(title=title)
            for k, v in rows:
                g.add(plain_row(k, v))
            page.add(g)

        g = Adw.PreferencesGroup(title="Interfaces", description="Cada interfaz puede tener su propio driver")
        for i in info.interfaces:
            ex = Adw.ExpanderRow(title=GLib.markup_escape_text(f"Interfaz {i.number} · {i.label or class_name(i.cls)}"),
                                 subtitle=GLib.markup_escape_text(f"Driver: {i.driver or 'ninguno'}"))
            ex.add_row(plain_row("Clase", class_name(i.cls)))
            ex.add_row(plain_row("Subclase / protocolo", f"0x{(i.subcls or 0):02x} / 0x{(i.proto or 0):02x}"))
            ex.add_row(plain_row("Driver vinculado", i.driver or "ninguno"))
            ex.add_row(plain_row("Módulos del kernel", ", ".join(i.modules) or "ninguno encontrado"))
            ex.add_row(plain_row("Modalias", i.modalias or "—"))
            for e in i.endpoints:
                ex.add_row(plain_row("Endpoint", e.removeprefix("Endpoint ")))
            g.add(ex)
        if info.interfaces:
            page.add(g)

        if info.nodes:
            g = Adw.PreferencesGroup(title="Nodos creados en el sistema")
            for sub, node in info.nodes:
                g.add(plain_row(node, f"Subsistema: {sub}"))
            page.add(g)

        g = Adw.PreferencesGroup(title="Datos en bruto")
        ex = Adw.ExpanderRow(title="Propiedades udev", subtitle=f"{len(info.props)} propiedades")
        for k, v in sorted(info.props.items()):
            ex.add_row(plain_row(k, v))
        g.add(ex)
        if info.lsusb:
            ex2 = Adw.ExpanderRow(title="Salida de lsusb -v", subtitle="Descriptores USB completos")
            lbl = Gtk.Label(label=info.lsusb, selectable=True, xalign=0, wrap=False, margin_top=8,
                            margin_bottom=8, margin_start=12, margin_end=12)
            lbl.add_css_class("monospace")
            ex2.add_row(Gtk.ScrolledWindow(child=lbl, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                           vscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=200))
            g.add(ex2)
        page.add(g)
        return page

    def on_copy(self, _btn):
        self.get_clipboard().set(self.info.as_text())
        self.toasts.add_toast(Adw.Toast(title="Información copiada al portapapeles"))

    # ------------------------------------------------------------ software
    def build_software_page(self) -> Gtk.Widget:
        self.sw_page = Adw.PreferencesPage()
        self.spin_attached = False
        self.spin_group = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        self.spinner = Gtk.Spinner(spinning=True)
        self.spin_label = Gtk.Label(label="Buscando drivers y aplicaciones…")
        box.append(self.spinner)
        box.append(self.spin_label)
        self.spin_group.add(box)
        return self.sw_page

    def load_software(self):
        for g in self.sw_groups:
            self.sw_page.remove(g)
        self.sw_groups.clear()
        self.spin_group.set_visible(True)
        if not self.spin_attached:
            self.sw_page.add(self.spin_group)
            self.spin_attached = True
        self.spinner.set_spinning(True)
        self.spin_label.set_label("Buscando drivers y aplicaciones…")

        self.gen = getattr(self, "gen", 0) + 1
        gen = self.gen

        def worker():
            resolver.resolve(self.info, lambda g: GLib.idle_add(self.add_group, g, gen))
            return None

        in_thread(worker, lambda _r: self.finish_search(gen))

    def finish_search(self, gen: int):
        if gen != self.gen:
            return
        self.spinner.set_spinning(False)
        self.spin_group.set_visible(False)

    def add_group(self, group: resolver.Group, gen: int):
        if gen != self.gen:  # resultado de una búsqueda anterior
            return False
        pg = Adw.PreferencesGroup(title=GLib.markup_escape_text(group.title),
                                  description=GLib.markup_escape_text(group.subtitle))
        for item in group.items:
            pg.add(self.make_row(item))
        # el grupo de «buscando…» siempre queda al final
        self.sw_page.remove(self.spin_group)
        self.sw_page.add(pg)
        self.sw_page.add(self.spin_group)
        self.sw_groups.append(pg)
        return False

    def make_row(self, item: resolver.Item) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(item.title),
                            subtitle=GLib.markup_escape_text(item.desc))
        row.set_subtitle_lines(0)
        row.set_title_lines(0)
        row.set_subtitle_selectable(True)
        if item.status:
            lbl = Gtk.Label(label=item.status, valign=Gtk.Align.CENTER)
            lbl.add_css_class("dim-label")
            row.add_suffix(lbl)
        for act in item.actions:
            btn = Gtk.Button(label=act.label, valign=Gtk.Align.CENTER, sensitive=act.enabled)
            if act.tooltip:
                btn.set_tooltip_text(act.tooltip)
            if act.kind in ("apt", "flatpak"):
                btn.add_css_class("suggested-action")
            btn.connect("clicked", self.on_action, act)
            row.add_suffix(btn)
        return row

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
                cmd = ["pkexec", "apt-get", "install", "-y", *p]
                timeout = 900
            elif k == "flatpak":
                cmd = ["flatpak", "install", "-y", "--noninteractive", "flathub", p]
                timeout = 900
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
                if k == "capture":
                    OutputWindow(self, " ".join(cmd), f"$ {shlex.join(cmd)}\n(código de salida {rc})\n\n{out}").present()
                elif rc == 0:
                    self.toasts.add_toast(Adw.Toast(title="Instalación completada"))
                    self.load_software()
                else:
                    OutputWindow(self, "La instalación ha fallado", f"$ {shlex.join(cmd)}\n(código {rc})\n\n{out}").present()

            in_thread(run_capture(cmd, timeout), done)

    # ------------------------------------------------------------- estado
    def mark_disconnected(self):
        self.banner.set_revealed(True)
