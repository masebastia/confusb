# SPDX-License-Identifier: GPL-3.0-or-later
"""Colores del fondo elegido por el usuario: de un color liso se deduce el resto de la paleta (paneles, tarjetas,
bordes, textos) para que todo se siga leyendo, sea el fondo claro u oscuro. Sin GTK."""
from __future__ import annotations

import re

RGB = tuple[int, int, int]
PATRON = re.compile(r"^#[0-9a-fA-F]{6}$")
TEXTO_CLARO: RGB = (240, 245, 250)     # texto sobre fondos oscuros
TEXTO_OSCURO: RGB = (22, 26, 31)       # texto sobre fondos claros


def valido(texto) -> bool:
    return isinstance(texto, str) and bool(PATRON.match(texto))


def analizar(texto: str) -> RGB:
    """«#0a1120» → (10, 17, 32)."""
    return int(texto[1:3], 16), int(texto[3:5], 16), int(texto[5:7], 16)


def a_hex(c: RGB) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mezclar(a: RGB, b: RGB, t: float) -> RGB:
    """Mezcla de a (t=0) a b (t=1)."""
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))   # type: ignore[return-value]


def luminancia(c: RGB) -> float:
    """Luminancia relativa (WCAG), de 0 (negro) a 1 (blanco)."""
    def lineal(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lineal(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def es_oscuro(texto: str) -> bool:
    """¿Hace falta tema oscuro (texto claro) sobre este fondo? Gana el texto que mejor contraste da, no la mitad de
    la escala: un azul medio se lee mejor con texto blanco que con negro."""
    bg = analizar(texto)
    return contraste(TEXTO_CLARO, bg) >= contraste(TEXTO_OSCURO, bg)


def contraste(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def derivar(fondo: str, oscuro: bool) -> dict:
    """Las entradas de la paleta que dependen del color de fondo. El resto (verde de marca, aviso, error…) se queda
    como en la paleta clara u oscura."""
    bg = analizar(fondo)
    hacia = (255, 255, 255) if oscuro else (0, 0, 0)          # los paneles se separan del fondo hacia el contraste
    opuesto = (0, 0, 0) if oscuro else (255, 255, 255)
    texto = TEXTO_CLARO if oscuro else TEXTO_OSCURO

    def sube(t: float) -> RGB:
        return mezclar(bg, hacia, t)

    tenue = mezclar(texto, bg, 0.22)
    entrada = mezclar(bg, opuesto, 0.45)
    return {
        "bg": a_hex(bg), "bg2": a_hex(bg),
        "panel": a_hex(sube(0.07)), "panel_hover": a_hex(sube(0.11)), "border": a_hex(sube(0.17)),
        "text": a_hex(texto), "dim": a_hex(tenue),
        "card": tuple(round(v) for v in sube(0.06)), "card_hover": tuple(round(v) for v in sube(0.10)),
        "glass": tuple(round(v) for v in sube(0.04)),
        "glass_input": "rgba(%d, %d, %d, 0.59)" % tuple(round(v) for v in entrada),
    }
