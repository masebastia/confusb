# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondas: más información de un dispositivo, la que no está en sysfs ni en udev y hay que preguntarle al propio
aparato o al sistema. Sin GTK (también la usa «confusb --dump»).

  Android   por ADB, si el teléfono tiene la depuración USB activada y autorizada para este equipo: modelo y
            nombre comercial, versión de Android, procesador, memoria, pantalla, batería y almacenamiento.
  MTP       el almacenamiento del teléfono, si el sistema ya lo tiene montado (confusb no lo monta).
  udev      para cualquier dispositivo, el árbol completo de atributos («udevadm info -a»).

Cada sonda es independiente y nunca debe fallar hacia fuera: si no puede, lo dice con un consejo («Instala adb…»,
«Acepta la depuración USB en el teléfono…») para que se sepa cómo ver más datos.
"""
from __future__ import annotations

import locale
import os
import re
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass, field

from gi.repository import Gio, GLib

from .almacenamiento import formatear
from .i18n import N_, _
from .usbinfo import DeviceInfo, read, run

ADB_INTERFAZ = (0xFF, 0x42, 0x01)       # clase, subclase y protocolo de la interfaz ADB
TIEMPO_ADB = 15                          # segundos que se le da a ADB

# Un solo «adb shell» con marcadores: una conexión en vez de seis (tarda unos 150 ms)
SCRIPT_ADB = (
    "echo @@props; getprop; "
    "echo @@bateria; dumpsys battery; "
    "echo @@mem; grep -E '^(MemTotal|MemAvailable)' /proc/meminfo; "
    "echo @@cpu; grep -c '^processor' /proc/cpuinfo; grep -m1 '^Hardware' /proc/cpuinfo; "
    "echo @@pantalla; wm size; wm density; "
    "echo @@disco; df -k /data"
)

# Valores de «dumpsys battery» (constantes de BatteryManager de Android)
ESTADOS_BATERIA = {"1": N_("Unknown"), "2": N_("Charging"), "3": N_("Discharging"), "4": N_("Not charging"),
                   "5": N_("Full")}
SALUD_BATERIA = {"1": N_("Unknown"), "2": N_("Good"), "3": N_("Overheating"), "4": N_("Dead"),
                 "5": N_("Over voltage"), "6": N_("Failure"), "7": N_("Cold")}

# Dónde dicen los fabricantes el nombre comercial (el modelo de ro.product.model es un código: CPH1941)
PROPIEDADES_NOMBRE = ("ro.product.marketname", "ro.vendor.oplus.market.name", "ro.oppo.market.name",
                      "ro.config.marketing_name", "ro.product.vendor.marketname", "ro.product.odm.marketname",
                      "ro.product.system.marketname", "ro.product.product.marketname")


@dataclass
class Resultado:
    resumen: str = ""
    secciones: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    crudos: list[tuple[str, str]] = field(default_factory=list)
    consejos: list[str] = field(default_factory=list)


# --------------------------------------------------------------- qué sondas valen
def tiene_adb(info: DeviceInfo) -> bool:
    return any((i.cls, i.subcls, i.proto) == ADB_INTERFAZ for i in info.interfaces)


def es_mtp(info: DeviceInfo) -> bool:
    return info.props.get("ID_MTP_DEVICE") == "1" or any((i.label or "").upper() == "MTP" for i in info.interfaces)


def puede_tardar(info: DeviceInfo) -> bool:
    """Las sondas que hablan con el aparato (ADB, MTP) pueden tardar: se avisa en la ventana mientras trabajan."""
    return tiene_adb(info) or es_mtp(info)


# ------------------------------------------------------------------- formato
def decimal(valor: float, cifras: int = 1) -> str:
    """Número con el separador decimal del sistema («31,2» en español)."""
    return locale.format_string(f"%.{cifras}f", valor)


def entero(texto: str | None) -> int | None:
    try:
        return int(str(texto).strip())
    except (TypeError, ValueError):
        return None


def fila(etiqueta: str, valor: str | None, filas: list[tuple[str, str]]):
    if valor is not None and str(valor).strip() != "":
        filas.append((etiqueta, str(valor).strip()))


# ----------------------------------------------------------------------- ADB
def parsear_adb_devices(salida: str) -> list[dict]:
    """«adb devices -l» → [{serie, estado, usb, modelo}]. Estados: device, unauthorized, offline, permiso…"""
    dispositivos = []
    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith(("List of devices", "*")):
            continue
        partes = linea.split(None, 1)
        if len(partes) < 2:
            continue
        serie, resto = partes
        estado = "permiso" if resto.startswith("no permissions") else resto.split()[0]
        usb = re.search(r"\busb:(\S+)", resto)
        modelo = re.search(r"\bmodel:(\S+)", resto)
        dispositivos.append({"serie": serie, "estado": estado, "usb": usb.group(1) if usb else "",
                             "modelo": modelo.group(1) if modelo else ""})
    return dispositivos


def buscar_adb(dispositivos: list[dict], puerto: str, serie: str) -> dict | None:
    """El dispositivo de ADB que corresponde a este USB: por el puerto (usb:3-1) y, si no, por el número de serie."""
    for d in dispositivos:
        if d["usb"] and d["usb"] == puerto:
            return d
    return next((d for d in dispositivos if serie and d["serie"] == serie), None)


def partir_bloques(salida: str) -> dict[str, str]:
    """Separa la salida de SCRIPT_ADB en bloques por sus marcadores «@@nombre»."""
    bloques: dict[str, list[str]] = {}
    actual = None
    for linea in salida.splitlines():
        if linea.startswith("@@"):
            actual = linea[2:].strip()
            bloques[actual] = []
        elif actual is not None:
            bloques[actual].append(linea.rstrip("\r"))
    return {k: "\n".join(v) for k, v in bloques.items()}


def parsear_props(texto: str) -> dict[str, str]:
    """Salida de «getprop»: «[clave]: [valor]»."""
    return {m.group(1): m.group(2) for m in re.finditer(r"^\[(.+?)\]: \[(.*)\]$", texto, re.M)}


def parsear_clave_valor(texto: str) -> dict[str, str]:
    """Líneas «clave: valor» (dumpsys battery, /proc/meminfo)."""
    return {m.group(1).strip(): m.group(2).strip()
            for m in re.finditer(r"^\s*([A-Za-z][A-Za-z ]*?):\s*(.*?)\s*$", texto, re.M)}


def primero(props: dict[str, str], claves) -> str:
    return next((props[c] for c in claves if props.get(c)), "")


def datos_android(bloques: dict[str, str]) -> Resultado:
    """Convierte lo que devuelve el teléfono en secciones listas para mostrar."""
    props = parsear_props(bloques.get("props", ""))
    res = Resultado()

    # --- el aparato
    version, api = props.get("ro.build.version.release", ""), props.get("ro.build.version.sdk", "")
    nombre = primero(props, PROPIEDADES_NOMBRE)
    modelo = props.get("ro.product.model", "")
    fab = props.get("ro.product.manufacturer", "")
    mem = parsear_clave_valor(bloques.get("mem", ""))
    cpu = bloques.get("cpu", "").splitlines()
    nucleos = entero(cpu[0]) if cpu else None
    hardware = next((l.split(":", 1)[1].strip() for l in cpu[1:] if l.startswith("Hardware")), "")
    plataforma = props.get("ro.board.platform", "")
    soc = hardware or " ".join(x for x in (props.get("ro.soc.manufacturer"), props.get("ro.soc.model")) if x)
    if plataforma and plataforma not in soc:
        soc = f"{soc} ({plataforma})" if soc else plataforma
    arquitectura = props.get("ro.product.cpu.abi", "")
    if arquitectura and nucleos:
        arquitectura += " · " + _("{n} cores").format(n=nucleos)
    ram = entero(re.sub(r"\D", "", mem.get("MemTotal", "")))
    pantalla = re.search(r"(\d+)x(\d+)", bloques.get("pantalla", "").split("Override")[0])
    densidad = re.search(r"Physical density:\s*(\d+)", bloques.get("pantalla", ""))
    pantalla_txt = ""
    if pantalla:
        pantalla_txt = f"{pantalla.group(1)}×{pantalla.group(2)} px" + (f" · {densidad.group(1)} dpi" if densidad else "")
    bloqueado = {"1": _("locked"), "0": _("unlocked")}.get(props.get("ro.boot.flash.locked", ""), "")
    banda = props.get("gsm.version.baseband", "").split(",")[0]

    tel: list[tuple[str, str]] = []
    fila(_("Commercial name"), nombre, tel)
    fila(_("Manufacturer"), fab, tel)
    fila(_("Model"), modelo, tel)
    fila(_("Android version"), f"{version} (API {api})" if version and api else version, tel)
    fila(_("Security patch"), props.get("ro.build.version.security_patch"), tel)
    fila(_("Build"), props.get("ro.build.display.id"), tel)
    fila(_("Platform"), soc, tel)
    fila(_("CPU architecture"), arquitectura, tel)
    fila(_("RAM"), formatear(ram * 1024) if ram else "", tel)
    fila(_("Screen"), pantalla_txt, tel)
    fila(_("Baseband"), banda, tel)
    fila(_("Bootloader"), bloqueado, tel)
    if tel:
        res.secciones.append((_("Android phone"), tel))
    res.resumen = " · ".join(x for x in (nombre or " ".join(y for y in (fab, modelo) if y),
                                         f"Android {version}" if version else "") if x)

    # --- batería
    b = parsear_clave_valor(bloques.get("bateria", ""))
    nivel, escala = entero(b.get("level")), entero(b.get("scale")) or 100
    temperatura, voltaje = entero(b.get("temperature")), entero(b.get("voltage"))
    fuentes = [txt for clave, txt in (("AC powered", "AC"), ("USB powered", "USB"),
                                      ("Wireless powered", _("Wireless"))) if b.get(clave) == "true"]
    bat: list[tuple[str, str]] = []
    if nivel is not None:
        fila(_("Level"), f"{round(nivel * 100 / escala)} %", bat)
        fila(_("Status"), _(ESTADOS_BATERIA[b["status"]]) if b.get("status") in ESTADOS_BATERIA else "", bat)
        fila(_("Health"), _(SALUD_BATERIA[b["health"]]) if b.get("health") in SALUD_BATERIA else "", bat)
        fila(_("Temperature"), f"{decimal(temperatura / 10)} °C" if temperatura is not None else "", bat)
        fila(_("Voltage"), f"{decimal(voltaje / 1000, 2)} V" if voltaje else "", bat)
        fila(_("Technology"), b.get("technology"), bat)
        fila(_("Power source"), ", ".join(fuentes) or _("On battery"), bat)
        res.secciones.append((_("Battery"), bat))

    # --- almacenamiento interno (la partición de datos)
    for linea in bloques.get("disco", "").splitlines():
        columnas = linea.split()
        if len(columnas) >= 4 and columnas[1].isdigit() and columnas[-1].startswith("/data"):
            total, usado = int(columnas[1]) * 1024, int(columnas[2]) * 1024
            libre = int(columnas[3]) * 1024
            res.secciones.append((_("Phone storage"), [(
                _("Internal storage"),
                f"{formatear(total)} · " + _("{used} used").format(used=formatear(usado)) + " · "
                + _("{free} free").format(free=formatear(libre)))]))
            break
    return res


def servidor_adb_en_marcha() -> bool:
    """¿Hay ya un servidor de ADB escuchando? (lo habrá arrancado el usuario o Android Studio)."""
    puerto = int(os.environ.get("ANDROID_ADB_SERVER_PORT") or 5037)
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.3):
            return True
    except OSError:
        return False


def _adb(adb: str, *args: str) -> str:
    r = subprocess.run([adb, *args], capture_output=True, text=True, timeout=TIEMPO_ADB)
    return r.stdout + r.stderr


def sonda_android(info: DeviceInfo, res: Resultado):
    if not tiene_adb(info):
        return
    adb = shutil.which("adb")
    if not adb:
        res.consejos.append(_("Install adb (sudo apt install adb) to read the phone's hardware data."))
        return
    estaba = servidor_adb_en_marcha()
    try:
        d = buscar_adb(parsear_adb_devices(_adb(adb, "devices", "-l")), os.path.basename(info.syspath), info.serial)
        if d is None or d["estado"] in ("offline", "permiso"):
            res.consejos.append(_("The phone does not answer through adb: unplug it and plug it in again."))
        elif d["estado"] == "unauthorized":
            res.consejos.append(_("Unlock the phone and accept «Allow USB debugging?» to read its data."))
        elif d["estado"] == "device":
            datos = datos_android(partir_bloques(_adb(adb, "-s", d["serie"], "shell", SCRIPT_ADB)))
            res.secciones = datos.secciones + res.secciones
            res.resumen = res.resumen or datos.resumen
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if not estaba:      # el servidor lo ha arrancado esta consulta: no se deja en marcha (retiene la interfaz USB)
            try:
                subprocess.run([adb, "kill-server"], capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass


# ----------------------------------------------------------------------- MTP
def volumen_mtp(info: DeviceInfo) -> Gio.Volume | None:
    bus, dev = entero(read(f"{info.syspath}/busnum")), entero(read(f"{info.syspath}/devnum"))
    if bus is None or dev is None:
        return None
    ruta = f"/dev/bus/usb/{bus:03d}/{dev:03d}"
    for v in Gio.VolumeMonitor.get().get_volumes():
        if v.get_identifier(Gio.VOLUME_IDENTIFIER_KIND_UNIX_DEVICE) == ruta:
            return v
    return None


def almacenamientos_mtp(montaje: Gio.Mount, segundos: int = 8) -> list[tuple[str, int, int]]:
    """(nombre, tamaño, libre) de cada almacenamiento del teléfono montado. Si no responde en unos segundos
    (teléfono bloqueado), se corta."""
    cancelar = Gio.Cancellable()
    temporizador = threading.Timer(segundos, cancelar.cancel)
    temporizador.start()
    out: list[tuple[str, int, int]] = []
    try:
        raiz = montaje.get_root()
        for hijo in raiz.enumerate_children("standard::name,standard::display-name", Gio.FileQueryInfoFlags.NONE,
                                            cancelar):
            fs = raiz.get_child(hijo.get_name()).query_filesystem_info("filesystem::size,filesystem::free", cancelar)
            out.append((hijo.get_display_name(), fs.get_attribute_uint64("filesystem::size"),
                        fs.get_attribute_uint64("filesystem::free")))
    except GLib.Error:
        pass
    finally:
        temporizador.cancel()
    return out


def sonda_mtp(info: DeviceInfo, res: Resultado):
    if not es_mtp(info):
        return
    volumen = volumen_mtp(info)
    montaje = volumen.get_mount() if volumen else None
    if montaje is None:
        if not any(t == _("Phone storage") for t, _f in res.secciones):    # ADB ya dio el almacenamiento
            res.consejos.append(_("Unlock the phone and open it in the file manager to see its storage."))
        return
    filas = [(nombre, f"{formatear(tam)} · " + _("{free} free").format(free=formatear(libre)))
             for nombre, tam, libre in almacenamientos_mtp(montaje) if tam]
    if filas:
        res.secciones.append((_("Storage (MTP)"), filas))


# ---------------------------------------------------------------------- udev
def sonda_udev(info: DeviceInfo, res: Resultado):
    texto = run(["udevadm", "info", "-a", "-p", info.syspath]).strip()
    if texto:
        res.crudos.append((_("udev attributes (udevadm info -a)"), texto))


# ------------------------------------------------------------------- conjunto
SONDAS = (sonda_android, sonda_mtp, sonda_udev)


def completar(info: DeviceInfo) -> DeviceInfo:
    """Ejecuta las sondas y deja sus resultados en el propio DeviceInfo (se puede repetir). Ninguna falla hacia
    fuera: lo que no se pueda saber, simplemente no aparece."""
    res = Resultado()
    for sonda in SONDAS:
        try:
            sonda(info, res)
        except Exception as e:  # noqa: BLE001
            print(f"confusb: {sonda.__name__}: {e}", flush=True)
    info.resumen, info.extra, info.crudos, info.consejos = res.resumen, res.secciones, res.crudos, res.consejos
    return info
