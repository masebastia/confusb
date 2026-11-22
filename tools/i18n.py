#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Herramientas de traducción de confusb (necesitan el paquete «gettext»).

  tools/i18n.py extract   regenera po/confusb.pot a partir del código
  tools/i18n.py merge     actualiza todos los po/*.po con el .pot nuevo (msgmerge)
  tools/i18n.py check     comprueba los .po: sintaxis (msgfmt) y que conserven los {marcadores}
  tools/i18n.py compile   compila los .po en locale/<idioma>/LC_MESSAGES/confusb.mo

Los textos del código están en inglés (_("...")); cada po/<código>.po traduce al idioma indicado.
"""
import glob
import os
import re
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PO = os.path.join(RAIZ, "po")


def run(*cmd):
    return subprocess.run(cmd, cwd=RAIZ, check=True)


def extract():
    run("xgettext", "--language=Python", "--keyword=_", "--keyword=N_", "--from-code=UTF-8",
        "--package-name=confusb", "--package-version=" + _version(),
        "--msgid-bugs-address=https://github.com/masebastia/confusb/issues",
        "--copyright-holder=the confusb authors", "-f", "po/POTFILES.in", "-o", "po/confusb.pot")


def _version():
    m = re.search(r'__version__ = "([^"]+)"', open(os.path.join(RAIZ, "confusb", "__init__.py")).read())
    return m.group(1) if m else "0"


def merge():
    for po in sorted(glob.glob(os.path.join(PO, "*.po"))):
        run("msgmerge", "--quiet", "--update", "--backup=none", po, "po/confusb.pot")


def _entradas(ruta):
    """[(msgid, msgstr)] de un .po (sin plurales ni contextos)."""
    from confusb.i18n import leer_po  # noqa: E402
    return leer_po(ruta)


def check():
    sys.path.insert(0, RAIZ)
    marcadores = lambda s: sorted(re.findall(r"\{[a-z_]*(?::[^}]*)?\}", s))
    fallos = 0
    for po in sorted(glob.glob(os.path.join(PO, "*.po"))):
        r = subprocess.run(["msgfmt", "--check-format", "--check-header", "-o", os.devnull, po],
                           capture_output=True, text=True)
        if r.returncode:
            print(f"{os.path.basename(po)}: {r.stderr.strip()}")
            fallos += 1
        for msgid, msgstr in _entradas(po).items():
            if marcadores(msgid) != marcadores(msgstr):
                print(f"{os.path.basename(po)}: marcadores distintos en «{msgid[:50]}»")
                fallos += 1
    print("OK" if not fallos else f"{fallos} problemas")
    return 1 if fallos else 0


def compile_():
    for po in sorted(glob.glob(os.path.join(PO, "*.po"))):
        lang = os.path.splitext(os.path.basename(po))[0]
        destino = os.path.join(RAIZ, "locale", lang, "LC_MESSAGES")
        os.makedirs(destino, exist_ok=True)
        run("msgfmt", "-o", os.path.join(destino, "confusb.mo"), po)


if __name__ == "__main__":
    acciones = {"extract": extract, "merge": merge, "check": check, "compile": compile_}
    if len(sys.argv) != 2 or sys.argv[1] not in acciones:
        sys.exit(__doc__)
    sys.exit(acciones[sys.argv[1]]() or 0)
