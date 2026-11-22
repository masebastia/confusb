# SPDX-License-Identifier: GPL-3.0-or-later
"""Tema y ajustes de «Interfaz» de confusb, con la estética de Contabilizando: azul azabache con
degradado, tarjetas translúcidas y cristal difuminado. Claro u oscuro según el sistema.

Los ajustes (los mismos de la «Interfaz» de Contabilizando, menos el rastro del ratón y el orden de
tarjetas, más qué hacer al conectar un dispositivo) están en «preferencias.py», sin GTK, porque también los
lee el servicio. Aquí se les añade el tema y se aplican en caliente a todas las ventanas."""
from __future__ import annotations

import os
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .preferencias import (AL_CONECTAR, COLORES, DEFECTOS, ESQUEMA, MARCOS, Preferencias)  # noqa: E402,F401

RES = os.path.join(os.path.dirname(__file__), "recursos")

# Paleta de Contabilizando (theme.py). Oscuro: azul azabache con un leve degradado.
OSCURO = {
    "bg": "#0a1120", "bg2": "#10203a", "panel": "#111c2e", "panel_hover": "#16243a", "border": "#1f3049",
    "text": "#e6edf3", "dim": "#8b9bb0", "ok": "#3fb950", "warn": "#e3b341", "danger": "#f85149",
    "brand": "#3fb950", "card": (17, 28, 46), "card_hover": (22, 36, 58), "glass": (20, 34, 56),
    "glass_alpha": 0.47, "glass_border": "rgba(255, 255, 255, 0.18)", "glass_input": "rgba(8, 16, 30, 0.59)",
}
CLARO = {
    "bg": "#f6f8fa", "bg2": "#e8f0fb", "panel": "#ffffff", "panel_hover": "#f3f8ff", "border": "#d0d7de",
    "text": "#1f2328", "dim": "#656d76", "ok": "#1a7f37", "warn": "#9a6700", "danger": "#cf222e",
    "brand": "#1a7f37", "card": (255, 255, 255), "card_hover": (243, 248, 255), "glass": (255, 255, 255),
    "glass_alpha": 0.45, "glass_border": "rgba(255, 255, 255, 0.86)", "glass_input": "rgba(255, 255, 255, 0.67)",
}


class Ajustes(Preferencias):
    """Las preferencias más el tema de la ventana: claro u oscuro, y el CSS que se regenera al cambiarlas."""

    def __init__(self):
        super().__init__()
        self._oyentes: list[Callable[[], None]] = []
        self._proveedor = Gtk.CssProvider()
        self._instalado = False

    @property
    def oscuro(self) -> bool:
        return Adw.StyleManager.get_default().get_dark()

    @property
    def paleta(self) -> dict:
        return OSCURO if self.oscuro else CLARO

    # ----------------------------------------------------------------- cambio
    def cambiar(self, **kw):
        super().cambiar(**kw)
        self._regenerar()

    def restablecer(self):
        super().restablecer()
        self._regenerar()

    def suscribir(self, fn: Callable[[], None]):
        self._oyentes.append(fn)

    def olvidar(self, fn: Callable[[], None]):
        if fn in self._oyentes:
            self._oyentes.remove(fn)

    # ------------------------------------------------------------------ estilo
    def instalar(self):
        """Carga la hoja de estilos en la pantalla (una sola vez, con GTK ya iniciado)."""
        if self._instalado:
            return
        self._instalado = True
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)   # claro/oscuro del sistema
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._regenerar())
        self._regenerar()

    @staticmethod
    def _rgba(rgb: tuple[int, int, int], alfa: float) -> str:
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alfa:.2f})"

    def _regenerar(self):
        p, v = self.paleta, self.valores
        op = v["opacidad"] / 100
        defs = f"""
@define-color cx_bg {p["bg"]};
@define-color cx_bg2 {p["bg2"]};
@define-color cx_panel {p["panel"]};
@define-color cx_panel_hover {p["panel_hover"]};
@define-color cx_border {p["border"]};
@define-color cx_text {p["text"]};
@define-color cx_dim {p["dim"]};
@define-color cx_ok {p["ok"]};
@define-color cx_warn {p["warn"]};
@define-color cx_danger {p["danger"]};
@define-color cx_brand {p["brand"]};
@define-color cx_card_bg {self._rgba(p["card"], op)};
@define-color cx_card_hover {self._rgba(p["card_hover"], min(1.0, op + 0.08))};
@define-color cx_glass {self._rgba(p["glass"], p["glass_alpha"])};
@define-color cx_glass_border {p["glass_border"]};
@define-color cx_glass_input {p["glass_input"]};
"""
        # Reglas que se añaden al final, según «Interfaz» (como en Contabilizando)
        extra = [f".card, .modcard {{ border-radius: {v['esquinas']}px; }}"]
        if v["marco"] == "resaltado":
            extra.append(".modcard:hover { border-color: @accent_bg_color; "
                         "box-shadow: 0 0 14px alpha(@accent_bg_color, 0.35); }")
        elif v["marco"] == "sin":
            extra.append(".card, .modcard, .modcard:hover { border-color: transparent; }")
        if v["sombra"]:
            extra.append(".card, .modcard { box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35); }")
        color = COLORES[v["titulo"]][1]
        if color:
            extra.append(f".mod-name, .card-title, .section {{ color: {color}; }}")
        with open(os.path.join(RES, "estilo.css"), encoding="utf-8") as f:
            css = f.read()
        self._proveedor.load_from_string(defs + css + "\n" + "\n".join(extra))
        for fn in list(self._oyentes):
            fn()


AJUSTES = Ajustes()
