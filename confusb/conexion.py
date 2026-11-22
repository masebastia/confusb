# SPDX-License-Identifier: GPL-3.0-or-later
"""Qué hacer cuando se conecta un dispositivo USB.

confusb no debe aparecer cada vez ni en cualquier sesión. Antes de mostrar nada comprueba:

  1. que la sesión de este usuario sea la que está delante (con «cambiar de usuario» las demás reciben los
     mismos eventos de udev pero no deben abrir nada);
  2. si el dispositivo ya se conocía y funcionaba: entonces no aparece;
  3. si es la primera vez que se conecta: ofrece abrir la información (notificación con un botón);
  4. si es una unidad de almacenamiento: abre la aplicación predeterminada para ella (el gestor de archivos),
     salvo que GNOME ya lo haga por sí mismo.

Aquí está la parte que decide (sin interfaz, para poder probarla) y el registro de dispositivos conocidos.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime

from gi.repository import GLib

from .usbinfo import DeviceInfo


@dataclass
class Decision:
    accion: str      # "nada" | "ventana" | "notificar" | "almacenamiento"
    motivo: str      # para el registro de depuración (no se muestra)


# ------------------------------------------------------------------ sesión

def _loginctl(*args: str) -> str | None:
    try:
        r = subprocess.run(["loginctl", *args], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def sesion_activa() -> bool:
    """True si la sesión gráfica de este usuario es la que está en primer plano en su asiento.

    Con varios usuarios conectados a la vez, solo la sesión «activa» tiene el monitor, el teclado y el ratón.
    Si no se puede averiguar (sin logind, por ejemplo) se supone que sí, para no quedarnos mudos.
    """
    sesion = _loginctl("show-user", str(os.getuid()), "-p", "Display", "--value") or os.environ.get("XDG_SESSION_ID")
    if not sesion:
        return True
    activa = _loginctl("show-session", sesion, "-p", "Active", "--value")
    return activa != "no"


# ----------------------------------------------------------------- registro

def clave(vid: str, pid: str, serie: str = "") -> str:
    """Identifica un dispositivo: VID:PID y, si lo tiene, su número de serie (dos iguales sin serie coinciden)."""
    base = f"{vid.lower()}:{pid.lower()}"
    return f"{base}:{serie.strip()}" if serie and serie.strip() else base


def clave_de(info: DeviceInfo) -> str:
    return clave(info.vid, info.pid, info.serial)


def operativo(info: DeviceInfo) -> bool:
    """El kernel ya tiene un controlador asociado a cada interfaz del dispositivo."""
    if info.interfaces:
        return all(i.driver for i in info.interfaces)
    return bool(info.drivers)


class Registro:
    """Dispositivos que ya se han conectado alguna vez: ~/.local/share/confusb/dispositivos.json."""

    def __init__(self, ruta: str | None = None):
        self.ruta = ruta or os.path.join(GLib.get_user_data_dir(), "confusb", "dispositivos.json")
        self.datos: dict[str, dict] = {}
        self._cargar()

    @property
    def existe(self) -> bool:
        return os.path.exists(self.ruta)

    def _cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        if isinstance(d, dict) and isinstance(d.get("dispositivos"), dict):
            self.datos = {k: v for k, v in d["dispositivos"].items() if isinstance(v, dict)}

    def recargar(self):
        """Vuelve a leer el fichero: la ventana (otro proceso) puede haberlo vaciado con «Olvidar»."""
        self.datos = {}
        self._cargar()

    def _guardar(self):
        try:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "dispositivos": self.datos}, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.ruta)
        except OSError:
            pass   # sin registro, todo sigue funcionando: solo se avisará más veces

    def buscar(self, info: DeviceInfo) -> dict | None:
        return self.datos.get(clave_de(info))

    def anotar(self, info: DeviceInfo):
        """Apunta una conexión (la primera vez crea la entrada)."""
        ahora = datetime.now().astimezone().isoformat(timespec="seconds")
        e = self.datos.setdefault(clave_de(info), {"primera": ahora, "veces": 0})
        e.update(nombre=info.title, ultima=ahora, veces=e.get("veces", 0) + 1, operativo=operativo(info))
        self._guardar()

    def sembrar(self, rutas_sysfs: list[str]):
        """Primer arranque del servicio: lo que ya está conectado cuenta como conocido; si no, al volver a
        enchufar el ratón o el teclado de siempre se tomarían por dispositivos nuevos."""
        ahora = datetime.now().astimezone().isoformat(timespec="seconds")
        for p in rutas_sysfs:
            def leer(f: str) -> str:
                try:
                    with open(os.path.join(p, f), errors="replace") as fh:
                        return fh.read().strip()
                except OSError:
                    return ""
            vid, pid = leer("idVendor"), leer("idProduct")
            if not vid or not pid:
                continue
            self.datos.setdefault(clave(vid, pid, leer("serial")), {
                "primera": ahora, "ultima": ahora, "veces": 1, "operativo": None,
                "nombre": leer("product") or f"{vid}:{pid}"})
        self._guardar()

    def olvidar(self):
        self.datos = {}
        self._guardar()


# ----------------------------------------------------------------- decisión

def decidir(info: DeviceInfo, *, activa: bool, previo: dict | None, modo: str, solo_nuevos: bool,
            abrir_almacenamiento: bool, automount_open: bool) -> Decision:
    """Qué hacer con un dispositivo recién conectado. «previo» es su entrada en el registro, si la hay."""
    if not activa:
        return Decision("nada", "sesión en segundo plano")
    if info.is_hub:
        return Decision("nada", "hub")
    if info.es_almacenamiento and abrir_almacenamiento:
        if automount_open:
            return Decision("nada", "unidad de almacenamiento: GNOME ya abre su aplicación")
        return Decision("almacenamiento", "unidad de almacenamiento")
    if modo == "nada":
        return Decision("nada", "ajuste: no hacer nada")
    if previo is None:
        return Decision(modo, "primera vez")
    if not solo_nuevos:
        return Decision(modo, "ajuste: avisar siempre")
    if previo.get("operativo") and not operativo(info):
        return Decision(modo, "conocido, pero ha dejado de tener controlador")
    return Decision("nada", "ya conocido")


REGISTRO = Registro()   # el del usuario; el servicio y la ventana «Interfaz» comparten esta instancia
