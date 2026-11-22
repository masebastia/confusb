# SPDX-License-Identifier: GPL-3.0-or-later
"""Unidades de almacenamiento de un dispositivo USB: capacidad, particiones, sistema de ficheros y montaje.

Los datos salen de «lsblk» (util-linux). Si no está disponible se usa sysfs, que al menos da la capacidad.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from gi.repository import Gio, GLib

from .i18n import _

COLUMNAS = "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS,MODEL,VENDOR,RO,RM,TRAN,FSAVAIL,FSUSED,PTTYPE"


@dataclass
class Particion:
    ruta: str
    tam: int = 0
    fstype: str = ""
    etiqueta: str = ""
    uuid: str = ""
    montajes: list[str] = field(default_factory=list)
    libre: int | None = None
    usado: int | None = None


@dataclass
class Unidad:
    ruta: str                                    # /dev/sdd
    tam: int = 0                                 # bytes; 0 = sin soporte (lector de tarjetas vacío)
    modelo: str = ""
    fabricante: str = ""
    solo_lectura: bool = False
    extraible: bool = False
    tabla: str = ""                              # dos, gpt…
    fstype: str = ""                             # si el sistema de ficheros ocupa el disco entero
    etiqueta: str = ""
    montajes: list[str] = field(default_factory=list)
    particiones: list[Particion] = field(default_factory=list)

    @property
    def todos_los_montajes(self) -> list[str]:
        return self.montajes + [m for p in self.particiones for m in p.montajes]


def formatear(n: int | None) -> str:
    """Tamaño legible con unidades decimales (1 GB = 10⁹ B), como en el gestor de archivos de GNOME."""
    return GLib.format_size(n) if n is not None else "—"


def capacidad(unidades: list[Unidad]) -> int | None:
    """Capacidad total de las unidades, o None si no hay ninguna con soporte."""
    total = sum(u.tam for u in unidades)
    return total if total > 0 else None


def es_particion(ruta: str) -> bool:
    return os.path.exists(f"/sys/class/block/{os.path.basename(ruta)}/partition")


def _montajes(valor) -> list[str]:
    return [m for m in (valor or []) if m]


def _entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def analizar(texto: str) -> list[Unidad]:
    """Convierte la salida JSON de «lsblk -J -b» en unidades. Lo que no sea un disco se descarta."""
    try:
        datos = json.loads(texto)
    except ValueError:
        return []
    unidades: list[Unidad] = []
    for d in datos.get("blockdevices", []):
        if d.get("type") not in ("disk", "rom"):
            continue
        u = Unidad(
            ruta=d.get("path") or "/dev/" + d.get("name", "?"),
            tam=_entero(d.get("size")) or 0,
            modelo=(d.get("model") or "").strip(),
            fabricante=(d.get("vendor") or "").strip(),
            solo_lectura=bool(d.get("ro")),
            extraible=bool(d.get("rm")),
            tabla=d.get("pttype") or "",
            fstype=d.get("fstype") or "",
            etiqueta=d.get("label") or "",
            montajes=_montajes(d.get("mountpoints")),
        )
        for h in d.get("children") or []:
            if h.get("type") != "part":
                continue
            u.particiones.append(Particion(
                ruta=h.get("path") or "/dev/" + h.get("name", "?"),
                tam=_entero(h.get("size")) or 0,
                fstype=h.get("fstype") or "",
                etiqueta=h.get("label") or "",
                uuid=h.get("uuid") or "",
                montajes=_montajes(h.get("mountpoints")),
                libre=_entero(h.get("fsavail")),
                usado=_entero(h.get("fsused")),
            ))
        unidades.append(u)
    return unidades


def _desde_sysfs(ruta: str) -> Unidad:
    base = f"/sys/class/block/{os.path.basename(ruta)}"
    try:
        with open(f"{base}/size") as f:
            sectores = int(f.read().strip())
    except (OSError, ValueError):
        sectores = 0
    return Unidad(ruta=ruta, tam=sectores * 512)


def leer(rutas: list[str]) -> list[Unidad]:
    """Unidades (discos) a las que pertenecen los nodos de bloque dados; las particiones se ignoran
    porque ya cuelgan de su disco."""
    discos = sorted({r for r in rutas if not es_particion(r)})
    if not discos:
        return []
    lsblk = shutil.which("lsblk")
    if lsblk:
        try:
            r = subprocess.run([lsblk, "-J", "-b", "-o", COLUMNAS, *discos], capture_output=True, text=True,
                               timeout=10)
            if r.returncode == 0 and (res := analizar(r.stdout)):
                return res
        except (OSError, subprocess.TimeoutExpired):
            pass
    return [_desde_sysfs(d) for d in discos]


def filas(unidades: list[Unidad]) -> list[tuple[str, str]]:
    """Filas (etiqueta, valor) para la sección «Almacenamiento» de la ficha del dispositivo."""
    out: list[tuple[str, str]] = []
    varias = len(unidades) > 1
    for u in unidades:
        pref = f"{os.path.basename(u.ruta)} · " if varias else ""
        if u.tam > 0:
            exactos = f"{u.tam:,}".replace(",", " ")       # separador de millares; la coma decimal de formatear() no se toca
            out.append((pref + _("Capacity"), f"{formatear(u.tam)} · {exactos} B"))
        else:
            out.append((pref + _("Capacity"), _("No media inserted")))
        modelo = " ".join(x for x in (u.fabricante, u.modelo) if x)
        if modelo:
            out.append((pref + _("Drive model"), modelo))
        if u.solo_lectura:
            out.append((pref + _("Access"), _("Read-only")))
        if u.tabla:
            out.append((pref + _("Partition table"), u.tabla))
        if u.fstype:
            out.append((pref + _("File system"), u.fstype + (f" «{u.etiqueta}»" if u.etiqueta else "")))
        for m in u.montajes:
            out.append((pref + _("Mounted at"), m))
        for p in u.particiones:
            partes = [formatear(p.tam)]
            if p.fstype:
                partes.append(p.fstype)
            if p.etiqueta:
                partes.append(f"«{p.etiqueta}»")
            if p.libre is not None and p.tam:
                partes.append(_("{free} free").format(free=formatear(p.libre)))
            if p.montajes:
                partes.append(_("mounted at {path}").format(path=", ".join(p.montajes)))
            else:
                partes.append(_("not mounted"))
            out.append((_("Partition {name}").format(name=os.path.basename(p.ruta)), " · ".join(partes)))
    return out


def puntos_de_montaje(unidades: list[Unidad]) -> list[str]:
    return [m for u in unidades for m in u.todos_los_montajes]


# ------------------------------------------------- montaje y aplicación predeterminada

MEDIA = "org.gnome.desktop.media-handling"


def _ajustes_medios() -> Gio.Settings | None:
    """Los ajustes de GNOME para medios extraíbles (None si no hay GNOME instalado)."""
    origen = Gio.SettingsSchemaSource.get_default()
    if origen is None or origen.lookup(MEDIA, True) is None:
        return None
    return Gio.Settings.new(MEDIA)


def _booleano(ajustes: Gio.Settings | None, clave: str, defecto: bool) -> bool:
    try:
        return ajustes.get_boolean(clave) if ajustes else defecto
    except (GLib.Error, TypeError):
        return defecto


def automount_open() -> bool:
    """GNOME abre por sí mismo la unidad al montarla (Configuración › Medios extraíbles): entonces confusb no
    debe abrirla otra vez."""
    return _booleano(_ajustes_medios(), "automount-open", False)


def dispositivo_de(mount: Gio.Mount) -> str:
    """Nodo de bloque (/dev/sdd1) del volumen que está montado."""
    vol = mount.get_volume()
    return (vol.get_identifier(Gio.VOLUME_IDENTIFIER_KIND_UNIX_DEVICE) or "") if vol else ""


def pertenece(dev: str, syspath: str) -> bool:
    """¿El nodo de bloque «dev» cuelga del dispositivo USB que está en «syspath» (sysfs)?"""
    if not dev:
        return False
    real = os.path.realpath(f"/sys/class/block/{os.path.basename(dev)}")
    return real.startswith(syspath.rstrip("/") + "/")


def aplicacion_para(mount: Gio.Mount, tipos: list[str] | None = None) -> Gio.AppInfo | None:
    """La aplicación predeterminada para abrir una unidad: la que GNOME tiene para su tipo de contenido
    (fotos, música, software…) si el usuario la ha activado y, si no, el gestor de archivos (inode/directory).
    None si el usuario ha pedido que no se abra nada."""
    ajustes = _ajustes_medios()
    if _booleano(ajustes, "autorun-never", False):
        return None

    def lista(clave: str) -> list[str]:
        try:
            return list(ajustes.get_strv(clave)) if ajustes else []
        except (GLib.Error, TypeError):
            return []

    iniciar, ignorar = lista("autorun-x-content-start-app"), lista("autorun-x-content-ignore")
    for t in tipos or []:
        if t in ignorar:
            return None
        if t in iniciar and (app := Gio.AppInfo.get_default_for_type(t, False)):
            return app
    return Gio.AppInfo.get_default_for_type("inode/directory", False)


def abrir(mount: Gio.Mount, hecho=None):
    """Abre la unidad montada con su aplicación predeterminada. «hecho(app|None)» se llama al terminar."""
    def tipos_listos(_m, res):
        try:
            tipos = list(mount.guess_content_type_finish(res) or [])
        except GLib.Error:
            tipos = []
        app = aplicacion_para(mount, tipos)
        if app is not None:
            try:
                try:
                    from gi.repository import Gdk
                    ctx = Gdk.Display.get_default().get_app_launch_context()
                except (ImportError, AttributeError, ValueError):
                    ctx = Gio.AppLaunchContext()
                app.launch([mount.get_root()], ctx)
            except GLib.Error as e:
                print(f"confusb: no se pudo abrir {mount.get_name()}: {e.message}", flush=True)
                app = None
        if hecho:
            hecho(app)

    mount.guess_content_type(False, None, tipos_listos)


class EsperaMontaje:
    """Espera a que el sistema monte las particiones de un dispositivo USB (el montaje automático tarda unos
    segundos tras conectarlo). Avisa de cada montaje con «al_montar(mount)» y, si pasado el tiempo no se ha
    montado nada, con «al_agotar()»."""

    def __init__(self, syspath: str, al_montar, al_agotar, segundos: int = 30):
        self.syspath = syspath
        self.al_montar = al_montar
        self.al_agotar = al_agotar
        self.vistos: set[str] = set()
        self.monitor = Gio.VolumeMonitor.get()
        self._senal = self.monitor.connect("mount-added", lambda _mon, m: self._nuevo(m))
        self._plazo = GLib.timeout_add_seconds(segundos, self._agotado)
        for m in self.monitor.get_mounts():      # puede que ya esté montado
            self._nuevo(m)

    def _nuevo(self, mount: Gio.Mount):
        uri = mount.get_root().get_uri()
        if uri in self.vistos or not pertenece(dispositivo_de(mount), self.syspath):
            return
        self.vistos.add(uri)
        self.al_montar(mount)

    def _agotado(self):
        self.monitor.disconnect(self._senal)
        if not self.vistos:
            self.al_agotar()
        return False
