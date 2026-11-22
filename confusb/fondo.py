# SPDX-License-Identifier: GPL-3.0-or-later
"""Fondo de las ventanas, como el de Contabilizando: azul azabache con degradado radial y el logotipo de
la marca como marca de agua. Detrás, motivos de hardware: pistas de circuito impreso, chips y conectores
USB. Se genera como SVG (una paleta clara y otra oscura) y se muestra a pantalla completa."""
from __future__ import annotations

import os
import random
import re

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402

from .ajustes import CLARO, OSCURO, RES  # noqa: E402

W, H = 2560, 1440
_cache: dict[bool, Gdk.Texture | None] = {}


def _logo(p: dict) -> str:
    """Contenido del logotipo (sin la etiqueta svg), con los colores de la paleta activa."""
    with open(os.path.join(RES, "logo.svg"), encoding="utf-8") as f:
        s = f.read().replace("#3fb950", p["brand"]).replace("#e6edf3", p["text"])
    s = re.sub(r"^.*?<svg[^>]*>", "", s, flags=re.S)
    return s.replace("</svg>", "")


def _pts(puntos) -> str:
    return " ".join(f"{x:.0f},{y:.0f}" for x, y in puntos)


def _bus(x0, y0, tramos, n, sep, orient, color, ancho=3.0) -> list[str]:
    """Haz de n pistas paralelas con el mismo recorrido (tramos rectos y diagonales a 45°) que acaban
    en una isleta cada una."""
    out = []
    for i in range(n):
        x, y = x0 + (i * sep if orient == "v" else 0), y0 + (i * sep if orient == "h" else 0)
        pts = [(x, y)]
        for dx, dy in tramos:
            x, y = x + dx, y + dy
            pts.append((x, y))
        out.append(f'<polyline points="{_pts(pts)}" fill="none" stroke="{color}" stroke-width="{ancho}" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="8" fill="none" stroke="{color}" stroke-width="{ancho}"/>')
        out.append(f'<circle cx="{pts[0][0]:.0f}" cy="{pts[0][1]:.0f}" r="4" fill="{color}"/>')
    return out


def _chip(x, y, w, h, etiqueta, color, mono) -> list[str]:
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="none" stroke="{color}" stroke-width="3"/>',
           f'<circle cx="{x + 22}" cy="{y + 22}" r="7" fill="none" stroke="{color}" stroke-width="2.5"/>',
           f'<text x="{x + w / 2}" y="{y + h / 2 + 8}" text-anchor="middle" font-family="{mono}" font-size="24" '
           f'font-weight="700" letter-spacing="3" fill="{color}">{etiqueta}</text>']
    for k in range(1, int(w // 34)):          # patillas arriba y abajo
        px = x + k * 34 - 6
        out.append(f'<rect x="{px}" y="{y - 20}" width="12" height="20" fill="none" stroke="{color}" stroke-width="2.5"/>')
        out.append(f'<rect x="{px}" y="{y + h}" width="12" height="20" fill="none" stroke="{color}" stroke-width="2.5"/>')
    for k in range(1, int(h // 34)):          # patillas a los lados
        py = y + k * 34 - 6
        out.append(f'<rect x="{x - 20}" y="{py}" width="20" height="12" fill="none" stroke="{color}" stroke-width="2.5"/>')
        out.append(f'<rect x="{x + w}" y="{py}" width="20" height="12" fill="none" stroke="{color}" stroke-width="2.5"/>')
    return out


def _usb_a(x, y, color) -> list[str]:
    """Conector USB-A de perfil: carcasa, lengüeta y cuatro contactos."""
    out = [f'<rect x="{x}" y="{y}" width="250" height="100" rx="8" fill="none" stroke="{color}" stroke-width="3"/>',
           f'<rect x="{x + 34}" y="{y + 20}" width="182" height="60" fill="none" stroke="{color}" stroke-width="2.5"/>',
           f'<rect x="{x + 34}" y="{y + 38}" width="150" height="24" fill="{color}" opacity="0.45"/>']
    for k in range(4):
        out.append(f'<rect x="{x + 48 + k * 34}" y="{y + 42}" width="18" height="16" fill="none" stroke="{color}" stroke-width="2"/>')
    return out


def _usb_c(x, y, color) -> list[str]:
    return [f'<rect x="{x}" y="{y}" width="170" height="72" rx="36" fill="none" stroke="{color}" stroke-width="3"/>',
            f'<rect x="{x + 22}" y="{y + 20}" width="126" height="32" rx="16" fill="none" stroke="{color}" stroke-width="2.5"/>',
            f'<rect x="{x + 40}" y="{y + 32}" width="90" height="8" rx="4" fill="{color}" opacity="0.5"/>']


def svg(oscuro: bool) -> str:
    p = OSCURO if oscuro else CLARO
    traza = "#1c3052" if oscuro else "#c4d4ea"
    mono = "'DejaVu Sans Mono', 'SF Mono', Consolas, 'Liberation Mono', monospace"
    parte = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<defs><radialGradient id="degradado" cx="0.15" cy="0" r="1.2" fx="0.15" fy="0">'
             f'<stop offset="0" stop-color="{p["bg2"]}"/><stop offset="1" stop-color="{p["bg"]}"/></radialGradient></defs>',
             f'<rect width="{W}" height="{H}" fill="url(#degradado)"/>']

    # ---- circuito impreso: haces de pistas, pistas sueltas con vías, chips y conectores
    arte: list[str] = []
    arte += _bus(-20, 1110, [(380, 0), (150, 150), (430, 0), (120, -120), (300, 0)], 6, 24, "h", traza)
    arte += _bus(2580, 190, [(-430, 0), (-140, 140), (-390, 0)], 5, 24, "h", traza)
    arte += _bus(160, -20, [(0, 230), (120, 120), (0, 270)], 5, 24, "v", traza)
    arte += _bus(2380, 1460, [(0, -310), (-110, -110), (0, -250)], 6, 24, "v", traza)
    arte += _bus(-20, 300, [(250, 0), (100, -100), (210, 0)], 4, 22, "h", traza)
    arte += _bus(2580, 1290, [(-370, 0), (-120, -120), (-300, 0)], 4, 22, "h", traza)
    chips = [(560, 320, 260, 170, "HUB"), (1700, 130, 200, 130, "PHY"), (1830, 920, 320, 200, "USB-CTRL"),
             (190, 860, 220, 150, "EEPROM")]
    conectores = [(1500, 1230, 250, 100), (760, 90, 170, 72)]
    ocupado = [(W / 2 - 660, H / 2 - 600, W / 2 + 660, H / 2 + 640)]          # el logotipo del centro
    ocupado += [(0, 0, 560, 600), (0, 1020, 1000, 1300), (1500, 80, W, 520), (2180, 760, W, H),   # haces de pistas
                (1880, 1000, W, 1320)]
    ocupado += [(x - 90, y - 90, x + w + 90, y + h + 90) for x, y, w, h, _ in chips]
    ocupado += [(x - 60, y - 60, x + w + 60, y + h + 60) for x, y, w, h in conectores]

    def libre(x0, y0, x1, y1) -> bool:
        for t in range(0, 11):
            x, y = x0 + (x1 - x0) * t / 10, y0 + (y1 - y0) * t / 10
            if not (60 < x < W - 60 and 60 < y < H - 60):
                return False
            if any(a <= x <= c and b <= y <= d for a, b, c, d in ocupado):
                return False
        return True

    rng = random.Random(11)
    hechas = 0
    for _ in range(400):                      # pistas sueltas con una vía al final, sin cruzar nada
        if hechas >= 14:
            break
        x, y = rng.randrange(80, W - 80, 40), rng.randrange(80, H - 80, 40)
        pts, ok = [(x, y)], True
        for _ in range(rng.randrange(2, 4)):
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)])
            n = rng.randrange(2, 6) * 40
            nx, ny = x + dx * n, y + dy * n
            if not libre(x, y, nx, ny):
                ok = False
                break
            x, y = nx, ny
            pts.append((x, y))
        if not ok or len(pts) < 3:
            continue
        hechas += 1
        arte.append(f'<polyline points="{_pts(pts)}" fill="none" stroke="{traza}" stroke-width="2.5" '
                    f'stroke-linejoin="round" stroke-linecap="round"/>')
        arte.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="9" fill="none" stroke="{traza}" stroke-width="2.5"/>')
        arte.append(f'<circle cx="{pts[0][0]:.0f}" cy="{pts[0][1]:.0f}" r="3.5" fill="{traza}"/>')
    for x, y, w, h, nombre in chips:
        arte += _chip(x, y, w, h, nombre, traza, mono)
    arte += _usb_a(1500, 1230, traza)
    arte += _usb_c(760, 90, traza)
    parte.append(f'<g opacity="{0.95 if oscuro else 1}">' + "".join(arte) + "</g>")

    # ---- el logotipo como marca de agua (misma proporción y opacidad que en Contabilizando)
    lado = 0.8 * min(W, H)
    k = lado / 400
    parte.append(f'<g opacity="{0.22 if oscuro else 0.12}" transform="translate({(W - lado) / 2:.0f},'
                 f'{(H - lado) / 2 + 30:.0f}) scale({k:.4f})">{_logo(p)}</g>')
    parte.append("</svg>")
    return "".join(parte)


def textura_svg(nombre: str, px: int, oscuro: bool) -> Gdk.Texture | None:
    """Un SVG de marca (logo.svg, icono.svg) con el color de marca y de texto del tema activo."""
    p = OSCURO if oscuro else CLARO
    with open(os.path.join(RES, nombre), encoding="utf-8") as f:
        svg_ = f.read().replace("#3fb950", p["brand"]).replace("#e6edf3", p["text"])
    svg_ = svg_.replace('width="400" height="400"', f'width="{px}" height="{px}"', 1)
    try:
        return Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg_.encode()))
    except GLib.Error:
        return None


def textura(oscuro: bool) -> Gdk.Texture | None:
    if oscuro not in _cache:
        try:
            _cache[oscuro] = Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg(oscuro).encode()))
        except GLib.Error:
            _cache[oscuro] = None   # sin cargador de SVG: la ventana se queda con el color liso
    return _cache[oscuro]
