# SPDX-License-Identifier: GPL-3.0-or-later
"""Ajustes de confusb. Son los mismos tipos de ajustes que tiene Rambleando:
apariencia (sistema/claro/oscuro), transparencia de las tarjetas y color de la letra.
Se guardan en ~/.config/confusb/ajustes.json y se aplican en caliente a todas las ventanas."""
from __future__ import annotations

import json
import os
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

RES = os.path.join(os.path.dirname(__file__), "recursos")

TEMAS = [("sistema", "Sistema"), ("claro", "Claro"), ("oscuro", "Oscuro")]
TRANSPARENCIA = {"minimo": 0, "maximo": 90, "paso": 5, "defecto": 75}   # % de transparencia de las tarjetas
AL_CONECTAR = [
    ("ventana", "Abrir una ventana con la información"),
    ("notificar", "Mostrar una notificación"),
    ("nada", "No hacer nada"),
]

_HALO_CLARO, _HALO_OSCURO = "#ffffff", "#0d1117"
# id, nombre, {modo: (texto, halo)}  — mismos colores que Rambleando
COLORES_TEXTO = [
    ("defecto", "Por defecto", {"claro": ("#1f2328", _HALO_CLARO), "oscuro": ("#e6edf3", _HALO_OSCURO)}),
    ("blanco", "Blanco", {"claro": ("#ffffff", _HALO_OSCURO), "oscuro": ("#ffffff", _HALO_OSCURO)}),
    ("negro", "Negro", {"claro": ("#000000", _HALO_CLARO), "oscuro": ("#000000", _HALO_CLARO)}),
    ("azul", "Azul marino", {"claro": ("#0b3d91", _HALO_CLARO), "oscuro": ("#8ab4f8", _HALO_OSCURO)}),
    ("verde", "Verde bosque", {"claro": ("#1e5631", _HALO_CLARO), "oscuro": ("#7ee2a8", _HALO_OSCURO)}),
    ("granate", "Granate", {"claro": ("#7a1f2b", _HALO_CLARO), "oscuro": ("#ff9aa2", _HALO_OSCURO)}),
]

DEFECTOS = {"tema": "sistema", "transparencia": TRANSPARENCIA["defecto"],
            "color_texto": "defecto", "al_conectar": "ventana"}


class Ajustes:
    def __init__(self):
        self.ruta = os.path.join(GLib.get_user_config_dir(), "confusb", "ajustes.json")
        self.valores = dict(DEFECTOS)
        self._cargar()
        self._oyentes: list[Callable[[], None]] = []
        self._proveedor = Gtk.CssProvider()
        self._instalado = False

    # ---------------------------------------------------------- persistencia
    def _cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(datos, dict):
            return
        if datos.get("tema") in {t for t, _ in TEMAS}:
            self.valores["tema"] = datos["tema"]
        t = datos.get("transparencia")
        if isinstance(t, int) and TRANSPARENCIA["minimo"] <= t <= TRANSPARENCIA["maximo"]:
            self.valores["transparencia"] = t
        if datos.get("color_texto") in {c for c, _, _ in COLORES_TEXTO}:
            self.valores["color_texto"] = datos["color_texto"]
        if datos.get("al_conectar") in {a for a, _ in AL_CONECTAR}:
            self.valores["al_conectar"] = datos["al_conectar"]

    def _guardar(self):
        try:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            with open(self.ruta, "w", encoding="utf-8") as f:
                json.dump(self.valores, f, indent=2)
        except OSError:
            pass  # los ajustes valen para esta sesión aunque no se puedan guardar

    # --------------------------------------------------------------- lectura
    def __getattr__(self, nombre):
        valores = self.__dict__.get("valores", {})
        if nombre in valores:
            return valores[nombre]
        raise AttributeError(nombre)

    @property
    def oscuro(self) -> bool:
        return Adw.StyleManager.get_default().get_dark()

    @property
    def modo(self) -> str:
        return "oscuro" if self.oscuro else "claro"

    def tono_texto(self) -> tuple[str, str]:
        for cid, _, tonos in COLORES_TEXTO:
            if cid == self.valores["color_texto"]:
                return tonos[self.modo]
        return COLORES_TEXTO[0][2][self.modo]

    # ----------------------------------------------------------------- cambio
    def cambiar(self, **kw):
        self.valores.update(kw)
        self._guardar()
        if "tema" in kw:
            self._esquema()
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
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._regenerar())
        self._esquema()
        self._regenerar()

    def _esquema(self):
        esquema = {"sistema": Adw.ColorScheme.DEFAULT, "claro": Adw.ColorScheme.FORCE_LIGHT,
                   "oscuro": Adw.ColorScheme.FORCE_DARK}[self.valores["tema"]]
        Adw.StyleManager.get_default().set_color_scheme(esquema)

    def _regenerar(self):
        oscuro = self.oscuro
        modo = self.modo
        texto, halo = self.tono_texto()
        opacidad = 1 - self.valores["transparencia"] / 100
        rgb = "22, 27, 34" if oscuro else "255, 255, 255"
        defs = f"""
@define-color panel_bg rgba({rgb}, {opacidad:.2f});
@define-color panel_borde {"rgba(255, 255, 255, 0.14)" if oscuro else "rgba(255, 255, 255, 0.7)"};
@define-color realce {"rgba(255, 255, 255, 0.14)" if oscuro else "rgba(255, 255, 255, 0.6)"};
@define-color texto {texto};
@define-color halo {halo};
@define-color fondo_ventana {"#0d1117" if oscuro else "#dfe3e8"};
@define-color ok_fg {"#6fdc8c" if oscuro else "#2b8a3e"};
@define-color aviso_fg {"#ffc14d" if oscuro else "#b87400"};
@define-color error_fg {"#ffa198" if oscuro else "#c62828"};
@define-color error_bg {"rgba(73, 2, 2, 0.85)" if oscuro else "rgba(255, 235, 233, 0.9)"};
"""
        muestras = "\n".join(
            f"button.muestra.muestra-{cid} {{ background-color: {tonos[modo][0]}; background-image: none; }}"
            for cid, _, tonos in COLORES_TEXTO)
        with open(os.path.join(RES, "estilo.css"), encoding="utf-8") as f:
            css = f.read()
        self._proveedor.load_from_string(defs + css + "\n" + muestras)
        for fn in list(self._oyentes):
            fn()


AJUSTES = Ajustes()
