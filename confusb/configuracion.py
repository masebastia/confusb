# SPDX-License-Identifier: GPL-3.0-or-later
"""¿Se puede configurar este dispositivo? Sin GTK.

El veredicto sale de pruebas objetivas, sin tocar el aparato:

  · el descriptor HID: un canal de informes «del fabricante» (Feature/Output en la página de uso 0xFF00+) es por
    donde el software de un ratón o teclado gaming guarda DPI, botones e iluminación;
  · la clase USB: una cámara o una tarjeta de sonido exponen controles (brillo, volumen…);
  · si una herramienta lo soporta (libratbag, Solaar, OpenRazer: tablas de «soporte.py» o datos instalados);
  · lo que se ajusta en los ajustes del sistema (ratón, teclado, impresora, Bluetooth…);
  · y si no hay nada seguro, qué herramientas del fabricante suelen servir.

La página «Configuración» añade los valores actuales (cámara por V4L2, audio por ALSA, ratón y teclado del
sistema) y las herramientas con su estado (instalada o no).
"""
from __future__ import annotations

import fcntl
import glob
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field

from gi.repository import Gio, GLib

from . import kb, resolver, soporte
from .i18n import N_, _
from .usbinfo import DeviceInfo, ENV, read

NIVELES = {"configurable": N_("Configurable"), "posible": N_("Maybe configurable"),
           "sistema": N_("System settings"), "ninguna": N_("Not configurable")}
ORDEN = ("configurable", "posible", "sistema", "ninguna")     # de más a menos
PAGINA_FABRICANTE = 0xFF00


# =============================================================== HID
@dataclass
class InformeHid:
    tipo: str                  # Input | Output | Feature
    id: int | None
    pagina: int
    bits: int

    @property
    def bytes(self) -> int:
        return (self.bits + 7) // 8


@dataclass
class ResumenHid:
    interfaz: str
    aplicaciones: list[tuple[int, int]] = field(default_factory=list)    # (página, uso) de las colecciones principales
    botones: int = 0
    ejes: list[str] = field(default_factory=list)
    informes: list[InformeHid] = field(default_factory=list)

    def del_fabricante(self, *tipos: str) -> list[InformeHid]:
        """Informes de las páginas de uso del fabricante: el canal de configuración de su software."""
        tipos = tipos or ("Feature", "Output")
        return [i for i in self.informes if i.tipo in tipos and i.pagina >= PAGINA_FABRICANTE]


EJES = {0x30: "X", 0x31: "Y", 0x32: "Z", 0x33: "Rx", 0x34: "Ry", 0x35: "Rz", 0x38: "Wheel", 0x39: "Hat"}
TIPOS_PRINCIPALES = {0x80: "Input", 0x90: "Output", 0xB0: "Feature"}


def analizar_hid(d: bytes, interfaz: str = "") -> ResumenHid:
    """Lee un descriptor de informes HID (elementos cortos) y resume qué es y qué informes tiene."""
    res = ResumenHid(interfaz)
    pagina = tam = cnt = 0
    rid: int | None = None
    usos: list[int] = []
    profundidad = 0
    i = 0
    while i < len(d):
        b = d[i]
        i += 1
        if b == 0xFE:                                  # elemento largo: se salta
            i += 2 + (d[i] if i < len(d) else 0)
            continue
        n = (0, 1, 2, 4)[b & 3]
        v = int.from_bytes(d[i:i + n], "little")
        i += n
        tipo, etiqueta = (b >> 2) & 3, b >> 4
        if tipo == 1:                                  # global
            if etiqueta == 0:
                pagina = v
            elif etiqueta == 7:
                tam = v
            elif etiqueta == 9:
                cnt = v
            elif etiqueta == 8:
                rid = v
        elif tipo == 2:                                # local
            if etiqueta == 0:
                usos.append(v & 0xFFFF)
        elif tipo == 0:                                # principal
            if etiqueta == 0xA:                        # colección
                if profundidad == 0 and v == 1:        # de aplicación
                    res.aplicaciones.append((pagina, usos[-1] if usos else 0))
                profundidad += 1
            elif etiqueta == 0xC:
                profundidad -= 1
            elif (b & 0xFC) in TIPOS_PRINCIPALES:
                nombre = TIPOS_PRINCIPALES[b & 0xFC]
                res.informes.append(InformeHid(nombre, rid, pagina, tam * cnt))
                if nombre == "Input" and not v & 1:    # datos, no relleno
                    if pagina == 9:
                        res.botones += cnt
                    elif pagina == 1:
                        res.ejes = [e for e in EJES.values() if e in res.ejes or e in [EJES[u] for u in usos if u in EJES]]
            usos = []
    return res


def descriptores_hid(syspath: str) -> list[ResumenHid]:
    """Un resumen por cada interfaz HID del dispositivo (descriptores de sysfs)."""
    out = []
    for f in sorted(glob.glob(os.path.join(glob.escape(syspath), "*:*", "0003:*", "report_descriptor"))):
        try:
            with open(f, "rb") as fh:
                datos = fh.read()
        except OSError:
            continue
        out.append(analizar_hid(datos, os.path.basename(os.path.dirname(os.path.dirname(f)))))
    return out


# ================================================ valores reales: cámara (V4L2)
@dataclass
class Control:
    nombre: str
    tipo: int                   # 1 entero, 2 booleano, 3 menú, 4 botón…
    valor: int | None
    minimo: int
    maximo: int
    defecto: int


VIDIOC_QUERYCAP = 0x80685600
VIDIOC_QUERYCTRL = 0xC0445624
VIDIOC_G_CTRL = 0xC008561B
CTRL_SIGUIENTE = 0x80000000
CTRL_DESACTIVADO = 0x1


def controles_v4l2(ruta: str) -> list[Control]:
    """Controles de imagen de una cámara (brillo, contraste, enfoque…) con su valor actual. Solo consulta."""
    try:
        fd = os.open(ruta, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return []
    out: list[Control] = []
    try:
        cap = fcntl.ioctl(fd, VIDIOC_QUERYCAP, b"\0" * 104)
        if not struct.unpack_from("I", cap, 88)[0] & 1:          # device_caps: ¿captura de vídeo?
            return []
        cid = CTRL_SIGUIENTE
        for _n in range(64):
            try:
                r = fcntl.ioctl(fd, VIDIOC_QUERYCTRL, struct.pack("I I 32s i i i i I 8x", cid, 0, b"", 0, 0, 0, 0, 0))
            except OSError:
                break                                             # no hay más
            id_, tipo, nombre, mn, mx, _paso, defecto, flags = struct.unpack("I I 32s i i i i I 8x", r)
            cid = id_ | CTRL_SIGUIENTE
            if flags & CTRL_DESACTIVADO or tipo == 6:             # 6 = cabecera de clase
                continue
            valor = None
            if tipo in (1, 2, 3):
                try:
                    valor = struct.unpack("I i", fcntl.ioctl(fd, VIDIOC_G_CTRL, struct.pack("I i", id_, 0)))[1]
                except OSError:
                    pass
            out.append(Control(nombre.split(b"\0")[0].decode(errors="replace"), tipo, valor, mn, mx, defecto))
    except OSError:
        pass
    finally:
        os.close(fd)
    return out


# ================================================= valores reales: audio (ALSA)
def tarjetas_alsa(info: DeviceInfo) -> list[int]:
    return sorted({int(m.group(1)) for _s, nodo in info.nodes if (m := re.search(r"controlC(\d+)$", nodo))})


def parsear_amixer(texto: str) -> list[tuple[str, str]]:
    """«amixer scontents» → [(control, valor)] solo de los que tienen volumen o interruptor."""
    out = []
    for bloque in re.split(r"(?m)^(?=Simple mixer control )", texto):
        cab = re.match(r"Simple mixer control '(.+)',(\d+)", bloque)
        caps = re.search(r"Capabilities:(.*)", bloque)
        if not cab or not caps or not re.search(r"volume|switch", caps.group(1)):
            continue
        nombre = cab.group(1) + (f" {cab.group(2)}" if cab.group(2) != "0" else "")
        porcentaje = re.search(r"\[(\d+)%\]", bloque)
        interruptor = re.search(r"\[(on|off)\]", bloque)
        partes = []
        if porcentaje:
            partes.append(f"{porcentaje.group(1)} %")
        if interruptor:
            partes.append(_(interruptor.group(1)))
        out.append((nombre, " · ".join(partes)))
    return out


def controles_alsa(tarjeta: int) -> list[tuple[str, str]]:
    exe = shutil.which("amixer")
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "-c", str(tarjeta), "scontents"], capture_output=True, text=True, timeout=5, env=ENV)
    except (OSError, subprocess.SubprocessError):
        return []
    return parsear_amixer(r.stdout) if r.returncode == 0 else []


# ====================================================== soporte conocido
_local: dict[str, str] | None = None


def libratbag_instalado() -> dict[str, str]:
    """Los dispositivos de libratbag según los datos instalados en este equipo (si hay)."""
    global _local
    if _local is None:
        _local = {}
        for f in glob.glob("/usr/share/libratbag/*.device"):
            try:
                with open(f, encoding="utf-8") as fh:
                    texto = fh.read()
            except OSError:
                continue
            nombre = re.search(r"^Name=(.+)$", texto, re.M)
            for m in re.finditer(r"usb:([0-9a-f]{4}):([0-9a-f]{4})", texto):
                _local[f"{m.group(1)}:{m.group(2)}"] = nombre.group(1).strip() if nombre else ""
    return _local


def soportado_por(info: DeviceInfo) -> list[tuple[str, str]]:
    """[(herramienta, nombre del modelo)] que soportan este dispositivo, sin instalar nada."""
    uid = info.usb_id
    out = []
    nombre = libratbag_instalado().get(uid) or soporte.LIBRATBAG.get(uid)
    if nombre is not None:
        out.append(("libratbag (Piper)", nombre))
    if uid in soporte.SOLAAR:
        out.append(("Solaar", soporte.SOLAAR[uid]))
    if uid in soporte.OPENRAZER:
        out.append(("OpenRazer", info.title))
    return out


# Fabricantes cuyos dispositivos suelen configurarse con una herramienta propia aunque no esté en las listas
POSIBLES = {
    "1532": ("OpenRazer", "Razer"), "1b1c": ("ckb-next", "Corsair"),
    "1038": ("Piper (libratbag)", "SteelSeries"), "1e7d": ("Piper (libratbag)", "Roccat"),
    "1e7e": ("Piper (libratbag)", "Roccat"),
}


# ================================================================ evaluación
def canal_del_fabricante(hid: list[ResumenHid]) -> list[InformeHid]:
    """Los informes Feature/Output de las páginas del fabricante, si forman un canal sustancial. Uno pequeño suelto
    (las teclas especiales de un teclado, p. ej. 5 bytes) no dice nada de ajustes: hacen falta varios informes o
    alguno grande (el ratón gaming de las pruebas tiene tres, el mayor de 324 bytes)."""
    informes = [i for r in hid for i in r.del_fabricante()]
    return informes if len(informes) >= 3 or any(i.bytes >= 16 for i in informes) else []



@dataclass
class Evaluacion:
    nivel: str = "ninguna"
    razones: list[tuple[str, str]] = field(default_factory=list)     # (nivel, texto)
    tipos: set[str] = field(default_factory=set)
    hid: list[ResumenHid] = field(default_factory=list)
    soportes: list[tuple[str, str]] = field(default_factory=list)

    def razon(self, nivel: str, texto: str):
        self.razones.append((nivel, texto))
        if ORDEN.index(nivel) < ORDEN.index(self.nivel):
            self.nivel = nivel


def tipos_de(info: DeviceInfo, hid: list[ResumenHid]) -> set[str]:
    """Qué es el dispositivo, por su clase USB y por lo que dice su descriptor HID."""
    apps = {a for r in hid for a in r.aplicaciones}
    t: set[str] = set()
    boot = {(i.subcls, i.proto) for i in info.interfaces if i.cls == 3}
    if (1, 2) in apps or (1, 2) in boot:
        t.add("raton")
    if (1, 6) in apps or (1, 1) in boot:
        t.add("teclado")
    if (1, 4) in apps or (1, 5) in apps:
        t.add("mando")
    if any(p == 0x0D for p, _u in apps) or info.vid == "056a":
        t.add("tableta")
    for clase, nombre in ((0x0E, "camara"), (0x01, "audio"), (0x07, "impresora"), (0xE0, "bluetooth"),
                          (0x08, "almacenamiento")):
        if clase in info.classes:
            t.add(nombre)
    if any(sub == "net" for sub, _n in info.nodes):
        t.add("red")
    return t


def evaluar(info: DeviceInfo) -> Evaluacion:
    """El veredicto y sus razones. Solo lee sysfs y tablas: es rápido (sirve para las tarjetas de la lista)."""
    ev = Evaluacion()
    ev.hid = descriptores_hid(info.syspath)
    ev.tipos = tipos_de(info, ev.hid)
    ev.soportes = soportado_por(info)

    canal = canal_del_fabricante(ev.hid)
    if canal:
        ev.razon("posible", _("It has a manufacturer-specific HID channel ({n} feature or output reports, up to {size} "
                              "bytes). The software of gaming mice usually uses it for settings such as DPI, buttons "
                              "and lighting.").format(n=len(canal), size=max(i.bytes for i in canal)))
    for herramienta, nombre in ev.soportes:
        ev.razon("configurable", _("{tool} supports this model ({name}).").format(tool=herramienta, name=nombre or info.title))
    if "camara" in ev.tipos:
        ev.razon("configurable", _("The camera exposes image controls (brightness, contrast…) that can be adjusted."))
    if "audio" in ev.tipos:
        ev.razon("configurable", _("The sound card exposes volume and mute controls."))
    if not ev.soportes and info.vid in POSIBLES:
        herramienta, marca = POSIBLES[info.vid]
        ev.razon("posible", _("It may be configurable with {tool}, a tool for {brand} devices.").format(tool=herramienta, brand=marca))
    if "mando" in ev.tipos:
        ev.razon("posible", _("A game controller can be remapped with input-remapper."))
    if "raton" in ev.tipos:
        ev.razon("sistema", _("The pointer speed, acceleration and buttons are set in the system settings."))
    if "teclado" in ev.tipos and "raton" not in ev.tipos:
        ev.razon("sistema", _("The layout and key repeat are set in the system settings."))
    if "tableta" in ev.tipos:
        ev.razon("sistema", _("The pen tablet is configured in the system settings."))
    if "impresora" in ev.tipos:
        ev.razon("sistema", _("Printers are configured in the system settings."))
    if "bluetooth" in ev.tipos:
        ev.razon("sistema", _("Bluetooth is configured in the system settings."))
    if "almacenamiento" in ev.tipos:
        ev.razon("sistema", _("A storage drive can be renamed and formatted with Disks."))
    if "red" in ev.tipos:
        ev.razon("sistema", _("The network connection is configured in the system settings."))
    if not ev.razones:
        ev.razon("ninguna", _("No configurable settings were found."))
    return ev


def nivel_rapido(info: DeviceInfo) -> str:
    return evaluar(info).nivel


# ========================================================= páginas y valores
@dataclass
class Informe:
    evaluacion: Evaluacion
    grupos: list[resolver.Group] = field(default_factory=list)

    @property
    def nivel(self) -> str:
        return self.evaluacion.nivel


def ajustes_sistema(esquema: str, claves: list[str]) -> dict[str, str]:
    """Valores de una configuración de GNOME (vacío si no hay GNOME)."""
    origen = Gio.SettingsSchemaSource.get_default()
    if origen is None or origen.lookup(esquema, True) is None:
        return {}
    ajustes = Gio.Settings.new(esquema)
    out = {}
    for c in claves:
        try:
            out[c] = ajustes.get_value(c).print_(False).strip("'")
        except GLib.Error:
            pass
    return out


PERFILES = {"default": N_("Default"), "flat": N_("Flat"), "adaptive": N_("Adaptive")}


def _panel(texto: str, panel: str) -> resolver.Action:
    exe = shutil.which("gnome-control-center")
    return resolver.Action(texto, "launch", ["gnome-control-center", panel], enabled=exe is not None,
                           tooltip="" if exe else _("Install «{name}» first").format(name="gnome-control-center"))


def grupo_valores(info: DeviceInfo, ev: Evaluacion) -> resolver.Group | None:
    """Lo que hoy se puede cambiar, con su valor actual."""
    items: list[resolver.Item] = []
    if "raton" in ev.tipos:
        v = ajustes_sistema("org.gnome.desktop.peripherals.mouse", ["speed", "accel-profile", "left-handed", "natural-scroll"])
        filas = []
        if "speed" in v:
            filas.append(_("Pointer speed") + f": {v['speed']}")
        if "accel-profile" in v:
            filas.append(_("Acceleration profile") + ": " + _(PERFILES.get(v["accel-profile"], v["accel-profile"])))
        for clave, etiqueta in (("left-handed", N_("Left-handed")), ("natural-scroll", N_("Natural scrolling"))):
            if clave in v:
                filas.append(_(etiqueta) + ": " + (_("on") if v[clave] == "true" else _("off")))
        it = resolver.Item(_("Mouse settings"), "\n".join(filas))
        it.actions.append(_panel(_("Open mouse settings"), "mouse"))
        items.append(it)
    if "teclado" in ev.tipos and "raton" not in ev.tipos:
        it = resolver.Item(_("Keyboard settings"))
        it.actions.append(_panel(_("Open keyboard settings"), "keyboard"))
        items.append(it)
    if "camara" in ev.tipos:
        controles = [c for _s, nodo in info.nodes if _s == "video4linux" for c in controles_v4l2(nodo)]
        if controles:
            filas = []
            for c in controles:
                if c.tipo == 2:
                    valor = _("on") if c.valor else _("off")
                elif c.valor is not None:
                    valor = f"{c.valor}" + (f" ({c.minimo}–{c.maximo})" if c.tipo == 1 else "")
                else:
                    valor = "—"
                filas.append(f"{c.nombre}: {valor}")
            items.append(resolver.Item(_("Camera controls"), "\n".join(dict.fromkeys(filas))))
    if "audio" in ev.tipos:
        filas = [f"{n}: {v}" for tarjeta in tarjetas_alsa(info) for n, v in controles_alsa(tarjeta)]
        it = resolver.Item(_("Audio controls"), "\n".join(filas))
        it.actions.append(_panel(_("Open sound settings"), "sound"))
        items.append(it)
    if "bluetooth" in ev.tipos:
        it = resolver.Item(_("Bluetooth settings"))
        it.actions.append(_panel(_("Open Bluetooth settings"), "bluetooth"))
        items.append(it)
    if "impresora" in ev.tipos:
        it = resolver.Item(_("Printer settings"))
        it.actions.append(_panel(_("Open printer settings"), "printers"))
        items.append(it)
    if "red" in ev.tipos:
        it = resolver.Item(_("Network settings"))
        it.actions.append(_panel(_("Open network settings"), "network"))
        items.append(it)
    return resolver.Group(_("Current settings"), items) if items else None


NOMBRES_APLICACION = {(1, 2): N_("Mouse"), (1, 6): N_("Keyboard"), (1, 4): N_("Joystick"), (1, 5): N_("Game pad"),
                      (0x0C, 1): N_("Consumer controls")}


def grupo_hid(ev: Evaluacion) -> resolver.Group | None:
    """El análisis técnico de cada interfaz HID, para quien quiera ver la evidencia."""
    items = []
    for r in ev.hid:
        filas = []
        if r.aplicaciones:
            filas.append(_("Function") + ": " + ", ".join(
                _(NOMBRES_APLICACION[a]) if a in NOMBRES_APLICACION else
                (_("Manufacturer-defined") if a[0] >= PAGINA_FABRICANTE else f"0x{a[0]:04x}/0x{a[1]:02x}")
                for a in dict.fromkeys(r.aplicaciones)))
        if r.botones:
            filas.append(_("Buttons") + f": {r.botones}")
        if r.ejes:
            filas.append(_("Axes") + ": " + ", ".join(r.ejes))
        for tipo, etiqueta in (("Feature", N_("Manufacturer-defined feature reports")),
                               ("Output", N_("Manufacturer-defined output reports"))):
            lista = r.del_fabricante(tipo)
            if lista:
                filas.append(_(etiqueta) + ": " + ", ".join(f"#{i.id or 0} ({i.bytes} B)" for i in lista))
        items.append(resolver.Item(_("HID interface {name}").format(name=r.interfaz), "\n".join(filas)))
    return resolver.Group(_("HID analysis"), items) if items else None


def grupo_herramientas(info: DeviceInfo, ev: Evaluacion) -> resolver.Group | None:
    """Las herramientas que sirven para configurarlo, con su estado (instalada o no)."""
    entradas: list[dict] = []
    notas: list[resolver.Item] = []
    nombres = {h for h, _n in ev.soportes}
    if "libratbag (Piper)" in nombres or (info.vid in POSIBLES and POSIBLES[info.vid][0].startswith("Piper")):
        entradas.append(kb.PIPER)
    if "Solaar" in nombres:
        entradas.append(kb.VENDOR_KB["046d"][0])
    if "OpenRazer" in nombres or (info.vid in POSIBLES and POSIBLES[info.vid][0] == "OpenRazer"):
        entradas.append(kb.OPENRAZER)
    if info.vid in POSIBLES and POSIBLES[info.vid][0] == "ckb-next":
        entradas.append(kb.CKB_NEXT)
    if ev.tipos & {"raton", "teclado", "mando"}:
        entradas.append(kb.INPUT_REMAPPER)
    if "camara" in ev.tipos:
        entradas.append(kb.GUVCVIEW)
    if "audio" in ev.tipos:
        entradas += kb.CLASS_KB[0x01]
    if "impresora" in ev.tipos:
        entradas += kb.CLASS_KB[0x07]
    if "almacenamiento" in ev.tipos:
        entradas += kb.CLASS_KB[0x08]
    if "bluetooth" in ev.tipos:
        entradas += kb.CLASS_KB[0xE0]
    # un ratón con canal propio del fabricante que libratbag no conoce: se dice, con enlace para pedirlo
    canal = bool(canal_del_fabricante(ev.hid))
    if canal and "raton" in ev.tipos and not any(h.startswith("libratbag") for h in nombres):
        it = resolver.Item("Piper (libratbag)", _("libratbag does not list this model ({id}), so Piper cannot configure it."
                                                  ).format(id=info.usb_id))
        it.actions.append(resolver.Action(
            _("Ask libratbag to support it"), "url",
            "https://github.com/libratbag/libratbag/issues?q=" + info.vid + "%3A" + info.pid))
        notas.append(it)
    if not entradas and not notas:
        return None
    pkgs = sorted({p for e in entradas for p in e.get("packages", [])})
    estados = resolver.pkg_states(pkgs)
    items = [resolver.make_item_from_kb(e, estados) for e in dict((id(e), e) for e in entradas).values()]
    return resolver.Group(_("Configuration tools"), items + notas)


def informe(info: DeviceInfo) -> Informe:
    """La página completa: veredicto, valores actuales, análisis HID y herramientas."""
    ev = evaluar(info)
    grupos = [g for g in (grupo_valores(info, ev), grupo_hid(ev), grupo_herramientas(info, ev)) if g]
    return Informe(ev, grupos)


def texto(info: DeviceInfo) -> list[str]:
    """El veredicto y sus razones, para «confusb --dump»."""
    ev = evaluar(info)
    return [f"== {_('Configuration')} ==", f"{_('Can it be configured?')} {_(NIVELES[ev.nivel])}",
            *[f"* {t}" for _n, t in ev.razones]]
