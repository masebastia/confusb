# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferencias de confusb (~/.config/confusb/ajustes.json), sin nada de GTK.

Las usan los dos procesos: la ventana (que las cambia y les añade el tema, en «ajustes.py») y el servicio que
vigila los USB (que solo las lee y no debe cargar la interfaz gráfica)."""
from __future__ import annotations

import json
import os

from gi.repository import GLib

from . import color, i18n
from .i18n import N_

COLORES = {
    "normal": (N_("Like the theme"), None),
    "azul": (N_("Blue"), "#4fa3ff"),
    "verde": (N_("Green"), "#3fb950"),
    "cian": (N_("Cyan"), "#39c5cf"),
    "violeta": (N_("Violet"), "#a78bfa"),
    "rosa": (N_("Pink"), "#f472b6"),
    "ambar": (N_("Amber"), "#e3b341"),
    "gris": (N_("Light gray"), "#a9b4bf"),
}
MARCOS = {
    "resaltado": N_("Highlighted (border and glow on hover)"),
    "suave": N_("Subtle (discreet border, no glow)"),
    "sin": N_("No frame"),
}
FONDOS = {
    "imagen": N_("Image (circuit board and logo)"),
    "color": N_("Solid color"),
}
AL_CONECTAR = {
    "ventana": N_("Open a window with the information"),
    "notificar": N_("Show a notification"),
    "nada": N_("Do nothing"),
}
ESQUEMA = 2   # 2: «al_conectar» pasa a «notificar» por defecto y se añaden «solo_nuevos» y «abrir_almacenamiento»
DEFECTOS = {"opacidad": 80, "titulo": "normal", "marco": "resaltado", "sombra": False, "esquinas": 12,
            "pie": True, "al_conectar": "notificar", "solo_nuevos": True, "abrir_almacenamiento": True,
            "fondo": "imagen", "color_fondo": "#0a1120",   # color del fondo cuando «fondo» es «color»
            "idioma": "", "esquema": ESQUEMA}   # idioma "" = el del sistema



class Preferencias:
    def __init__(self):
        self.ruta = os.path.join(GLib.get_user_config_dir(), "confusb", "ajustes.json")
        self.valores = dict(DEFECTOS)
        self._cargar()
        i18n.activar(self.idioma_efectivo)

    def recargar(self):
        """Vuelve a leer el fichero: lo puede haber cambiado la ventana, que es otro proceso."""
        self.valores = dict(DEFECTOS)
        self._cargar()
        i18n.activar(self.idioma_efectivo)

    # ---------------------------------------------------------- persistencia
    def _cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        v = self.valores
        if isinstance(d.get("opacidad"), int):
            v["opacidad"] = max(20, min(100, d["opacidad"]))
        if isinstance(d.get("esquinas"), int):
            v["esquinas"] = max(0, min(24, d["esquinas"]))
        if d.get("titulo") in COLORES:
            v["titulo"] = d["titulo"]
        if d.get("marco") in MARCOS:
            v["marco"] = d["marco"]
        # Con el esquema 1 «ventana» era el valor por defecto y no se puede saber si se eligió: se pasa al nuevo.
        if d.get("al_conectar") in AL_CONECTAR and d.get("esquema", 1) >= ESQUEMA:
            v["al_conectar"] = d["al_conectar"]
        if d.get("fondo") in FONDOS:
            v["fondo"] = d["fondo"]
        if color.valido(d.get("color_fondo")):
            v["color_fondo"] = d["color_fondo"].lower()
        if d.get("idioma") in i18n.IDIOMAS:
            v["idioma"] = d["idioma"]
        for k in ("sombra", "pie", "solo_nuevos", "abrir_almacenamiento"):
            if isinstance(d.get(k), bool):
                v[k] = d[k]

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
    def idioma_efectivo(self) -> str:
        """El idioma elegido o, si no se ha elegido ninguno, el del sistema."""
        return self.valores["idioma"] or i18n.idioma_del_sistema()

    # ----------------------------------------------------------------- cambio
    def cambiar(self, **kw):
        self.valores.update(kw)
        self._guardar()
        if "idioma" in kw:
            i18n.activar(self.idioma_efectivo)

    def restablecer(self):
        self.valores = {**DEFECTOS, "idioma": self.valores["idioma"]}   # el idioma elegido se conserva
        self._guardar()
