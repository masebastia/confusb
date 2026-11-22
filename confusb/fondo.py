# SPDX-License-Identifier: GPL-3.0-or-later
"""Fondo de las ventanas: la «rambla» de Rambleando dibujada como un plano (curvas de nivel, cauce de
arena y una ruta fucsia entre dos puntos), que se ve a través de las tarjetas translúcidas.
Se genera como SVG, con una paleta para el modo claro y otra para el oscuro."""
from __future__ import annotations

import math

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402

W, H = 2560, 1440
PALETAS = {
    False: dict(base="#e3e8df", curva="#c5d0be", cauce="#efe2c3", orilla="#e0cfa5"),
    True: dict(base="#0e1418", curva="#1a2b27", cauce="#2b2a22", orilla="#201f19"),
}
_cache: dict[bool, Gdk.Texture | None] = {}


def _rio(x: float) -> float:
    return H * 0.64 + 190 * math.sin(x / 520) + 70 * math.sin(x / 210 + 1)


def _polilinea(puntos) -> str:
    return " ".join(f"{x:.0f},{y:.0f}" for x, y in puntos)


def svg(oscuro: bool) -> str:
    p = PALETAS[oscuro]
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
              f'<rect width="{W}" height="{H}" fill="{p["base"]}"/>']
    n = 30
    for k in range(n):  # curvas de nivel: líneas onduladas
        y0 = -60 + k * (H + 120) / (n - 1)
        pts = [(x, y0 + 40 * math.sin(x / 240 + k * 0.55) + 24 * math.sin(x / 97 - k * 0.9)
                + 15 * math.sin(x / 420 + k * 0.2)) for x in range(-30, W + 31, 24)]
        grosor = 3.2 if k % 5 == 0 else 1.8
        partes.append(f'<polyline points="{_polilinea(pts)}" fill="none" stroke="{p["curva"]}" '
                      f'stroke-width="{grosor}" stroke-linejoin="round"/>')
    cauce = [(x, _rio(x)) for x in range(-60, W + 61, 12)]
    partes.append(f'<polyline points="{_polilinea(cauce)}" fill="none" stroke="{p["orilla"]}" '
                  f'stroke-width="170" stroke-linecap="round" stroke-linejoin="round"/>')
    partes.append(f'<polyline points="{_polilinea(cauce)}" fill="none" stroke="{p["cauce"]}" '
                  f'stroke-width="96" stroke-linecap="round" stroke-linejoin="round"/>')
    x1, x2 = W * 0.17, W * 0.78
    ruta = [(x, _rio(x) + 6 * math.sin(x / 31)) for x in range(int(x1), int(x2), 8)]
    partes.append(f'<polyline points="{_polilinea(ruta)}" fill="none" stroke="#ff2d95" stroke-width="16" '
                  f'stroke-linecap="round" stroke-dasharray="34 26" opacity="0.9"/>')
    partes.append(f'<circle cx="{x1:.0f}" cy="{_rio(x1):.0f}" r="30" fill="#2fbf71" stroke="#ffffff" stroke-width="10"/>')
    partes.append(f'<circle cx="{x2:.0f}" cy="{_rio(x2):.0f}" r="30" fill="#ff2d95" stroke="#ffffff" stroke-width="10"/>')
    partes.append("</svg>")
    return "".join(partes)


def textura(oscuro: bool) -> Gdk.Texture | None:
    if oscuro not in _cache:
        try:
            _cache[oscuro] = Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg(oscuro).encode()))
        except GLib.Error:
            _cache[oscuro] = None   # sin cargador de SVG: la ventana se queda con el color liso
    return _cache[oscuro]
