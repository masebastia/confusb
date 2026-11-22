# SPDX-License-Identifier: GPL-3.0-or-later
"""Idiomas de confusb: gettext con los textos fuente en inglés.

  _("text")    traduce al idioma activo
  N_("text")   solo marca el texto para extraerlo (se traduce más tarde, con _())

Las traducciones son los .po de la carpeta po/ (en una instalación de Debian, los .mo de
/usr/share/locale). Al ejecutar desde el código fuente se leen los .po directamente, sin compilar.
"""
from __future__ import annotations

import gettext
import os
import re

DOMINIO = "confusb"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Idiomas europeos: los oficiales de cada país (los de la UE y los de los demás estados de Europa).
# No se incluyen lenguas regionales ni cooficiales. código: (bandera, nombre en su idioma); la
# abreviatura es el código en mayúsculas.
IDIOMAS: dict[str, tuple[str, str]] = {}


def _bandera(pais: str) -> str:
    """Emoji de bandera: dos letras de país (ISO 3166) o un código de región (GB-WLS, GB-SCT)."""
    if "-" in pais:  # banderas de región: bandera negra + etiquetas + cancelación
        return "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in pais.replace("-", "").lower()) + "\U000E007F"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in pais)


for _cod, _pais, _nombre in (
    ("be", "BY", "Беларуская"), ("bg", "BG", "Български"), ("bs", "BA", "Bosanski"), 
    ("cnr", "ME", "Crnogorski"), ("cs", "CZ", "Čeština"), ("da", "DK", "Dansk"),
    ("de", "DE", "Deutsch"), ("el", "GR", "Ελληνικά"), ("en", "GB", "English"), ("es", "ES", "Español"),
    ("et", "EE", "Eesti"), ("fi", "FI", "Suomi"), 
    ("fr", "FR", "Français"), ("ga", "IE", "Gaeilge"), 
    ("hr", "HR", "Hrvatski"), ("hu", "HU", "Magyar"), ("is", "IS", "Íslenska"), ("it", "IT", "Italiano"),
    ("lb", "LU", "Lëtzebuergesch"), ("lt", "LT", "Lietuvių"), ("lv", "LV", "Latviešu"), ("mk", "MK", "Македонски"),
    ("mt", "MT", "Malti"), ("nb", "NO", "Norsk bokmål"), ("nl", "NL", "Nederlands"), ("pl", "PL", "Polski"),
    ("pt", "PT", "Português"), ("ro", "RO", "Română"), ("ru", "RU", "Русский"), ("sk", "SK", "Slovenčina"),
    ("sl", "SI", "Slovenščina"), ("sq", "AL", "Shqip"), ("sr", "RS", "Српски"), ("sv", "SE", "Svenska"),
    ("tr", "TR", "Türkçe"), ("uk", "UA", "Українська"),
):
    IDIOMAS[_cod] = (_bandera(_pais), _nombre)

FUENTE = "en"   # idioma de los textos del código


def N_(texto: str) -> str:
    """Marca un texto como traducible sin traducirlo todavía."""
    return texto


class _TraduccionPO(gettext.NullTranslations):
    """Traducción leída de un .po (para ejecutar sin compilar)."""

    def __init__(self, tabla: dict[str, str]):
        super().__init__()
        self._tabla = tabla

    def gettext(self, mensaje):
        return self._tabla.get(mensaje) or mensaje


def _desescapar(s: str) -> str:
    return re.sub(r'\\(["\\nt])', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def leer_po(ruta: str) -> dict[str, str]:
    """Lee un .po sencillo (sin plurales ni contextos). Ignora las entradas «fuzzy» y las vacías."""
    tabla: dict[str, str] = {}
    msgid, msgstr, campo, difusa = None, "", None, False

    def cerrar():
        if msgid and msgstr and not difusa:
            tabla[msgid] = msgstr
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.rstrip("\n")
            if linea.startswith("#,") and "fuzzy" in linea:
                cerrar()
                msgid, msgstr, campo, difusa = None, "", None, True
            elif linea.startswith("msgid "):
                if campo == "msgstr":
                    cerrar()
                    difusa = False
                msgid, msgstr, campo = _desescapar(linea[7:-1]), "", "msgid"
            elif linea.startswith("msgstr "):
                msgstr, campo = _desescapar(linea[8:-1]), "msgstr"
            elif linea.startswith('"') and campo:
                if campo == "msgid":
                    msgid += _desescapar(linea[1:-1])
                else:
                    msgstr += _desescapar(linea[1:-1])
            elif not linea.strip():
                if campo == "msgstr":
                    cerrar()
                msgid, msgstr, campo, difusa = None, "", None, False
        if campo == "msgstr":
            cerrar()
    tabla.pop("", None)  # cabecera
    return tabla


def _cargar(codigo: str) -> gettext.NullTranslations:
    if codigo == FUENTE or codigo not in IDIOMAS:
        return gettext.NullTranslations()
    # .mo compilados: primero los del propio árbol de código (si se ejecuta desde el repositorio, que no mande
    # una versión vieja instalada en el sistema) y luego los instalados.
    for carpeta in (os.path.join(RAIZ, "locale"), "/usr/share/locale"):
        try:
            return gettext.translation(DOMINIO, localedir=carpeta, languages=[codigo])
        except OSError:
            pass
    po = os.path.join(RAIZ, "po", f"{codigo}.po")                               # código fuente
    if os.path.exists(po):
        try:
            return _TraduccionPO(leer_po(po))
        except (OSError, UnicodeDecodeError):
            pass
    return gettext.NullTranslations()


_traduccion: gettext.NullTranslations = gettext.NullTranslations()
_activo = FUENTE


def _(texto: str) -> str:
    """Traduce al idioma activo (si no hay traducción, devuelve el texto en inglés)."""
    return _traduccion.gettext(texto)


def activar(codigo: str) -> str:
    """Pone el idioma activo; devuelve el código realmente activado."""
    global _traduccion, _activo
    _activo = codigo if codigo in IDIOMAS else FUENTE
    _traduccion = _cargar(_activo)
    return _activo


def activo() -> str:
    return _activo


def idioma_del_sistema() -> str:
    """El idioma del escritorio si confusb lo tiene; si no, inglés."""
    try:
        import gi
        from gi.repository import GLib
        nombres = list(GLib.get_language_names())
    except (ImportError, ValueError):
        nombres = [os.environ.get("LANGUAGE", "") or os.environ.get("LANG", "")]
    for nombre in nombres:
        base = re.split(r"[_.@:]", nombre)[0].lower()
        base = {"no": "nb", "nn": "nb", "nob": "nb", "srp": "sr"}.get(base, base)
        if base in IDIOMAS:
            return base
    return FUENTE


def etiqueta(codigo: str) -> str:
    """«🇪🇸 ES»: bandera y abreviatura."""
    return f"{IDIOMAS[codigo][0]} {codigo.upper()}"


def mayusculas(texto: str) -> str:
    """Pasa a mayúsculas respetando las reglas del turco (i→İ, ı→I)."""
    if _activo == "tr":
        texto = texto.replace("i", "İ").replace("ı", "I")
    return texto.upper()
