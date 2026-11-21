"""Recopila toda la información posible de un dispositivo USB (sysfs + udev + lsusb)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

ENV = {**os.environ, "LC_ALL": "C"}

CLASS_NAMES = {
    0x00: "Definida a nivel de interfaz",
    0x01: "Audio",
    0x02: "Comunicaciones (CDC)",
    0x03: "Dispositivo de interfaz humana (HID)",
    0x05: "Físico",
    0x06: "Imagen",
    0x07: "Impresora",
    0x08: "Almacenamiento masivo",
    0x09: "Hub",
    0x0A: "CDC-Data",
    0x0B: "Tarjeta inteligente (CCID)",
    0x0D: "Seguridad / contenido",
    0x0E: "Vídeo",
    0x0F: "Salud personal",
    0x10: "Audio/Vídeo",
    0x11: "Billboard",
    0xDC: "Diagnóstico",
    0xE0: "Inalámbrico (p. ej. Bluetooth)",
    0xEF: "Miscelánea",
    0xFE: "Específica de aplicación (DFU, IrDA...)",
    0xFF: "Específica del fabricante",
}

SPEEDS = {
    "1.5": "Low Speed (1,5 Mb/s) · USB 1.0",
    "12": "Full Speed (12 Mb/s) · USB 1.1",
    "480": "High Speed (480 Mb/s) · USB 2.0",
    "5000": "SuperSpeed (5 Gb/s) · USB 3.0",
    "10000": "SuperSpeed+ (10 Gb/s) · USB 3.1",
    "20000": "SuperSpeed+ (20 Gb/s) · USB 3.2",
}

# Atributos de sysfs del dispositivo: (fichero, etiqueta)
DEVICE_ATTRS = [
    ("manufacturer", "Fabricante (descriptor)"),
    ("product", "Producto (descriptor)"),
    ("serial", "Nº de serie"),
    ("idVendor", "ID de fabricante (VID)"),
    ("idProduct", "ID de producto (PID)"),
    ("bcdDevice", "Versión del dispositivo (bcdDevice)"),
    ("version", "Versión de USB"),
    ("speed", "Velocidad negociada (Mb/s)"),
    ("bDeviceClass", "Clase del dispositivo"),
    ("bDeviceSubClass", "Subclase del dispositivo"),
    ("bDeviceProtocol", "Protocolo del dispositivo"),
    ("bMaxPacketSize0", "Tamaño máx. de paquete EP0"),
    ("bNumConfigurations", "Nº de configuraciones"),
    ("bConfigurationValue", "Configuración activa"),
    ("bNumInterfaces", "Nº de interfaces"),
    ("bmAttributes", "Atributos de configuración"),
    ("bMaxPower", "Consumo máximo declarado"),
    ("busnum", "Bus"),
    ("devnum", "Dirección en el bus"),
    ("devpath", "Ruta de puertos (devpath)"),
    ("maxchild", "Puertos hijos"),
    ("removable", "Extraíble"),
    ("authorized", "Autorizado"),
    ("configuration", "Nombre de la configuración"),
    ("ltm_capable", "LTM"),
    ("quirks", "Quirks del kernel"),
]

NODE_SKIP = {"power", "driver", "subsystem", "firmware_node", "device"}


def read(path: str) -> str | None:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def hexint(value: str | None) -> int | None:
    try:
        return int(value, 16) if value is not None else None
    except ValueError:
        return None


def run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=ENV)
        return r.stdout if r.stdout else r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"({e})"


def class_name(code: int | None) -> str:
    if code is None:
        return "?"
    return f"0x{code:02x} · {CLASS_NAMES.get(code, 'Desconocida')}"


@dataclass
class Interface:
    name: str
    number: str
    cls: int | None
    subcls: int | None
    proto: int | None
    label: str | None
    driver: str | None
    modalias: str | None
    modules: list[str]
    endpoints: list[str]


@dataclass
class DeviceInfo:
    syspath: str
    vid: str = ""
    pid: str = ""
    vendor: str = ""          # nombre de fabricante (usb.ids o descriptor)
    product: str = ""         # nombre de producto (usb.ids o descriptor)
    serial: str = ""
    dev_class: int | None = None
    classes: set[int] = field(default_factory=set)       # clases de dispositivo + interfaces
    sections: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)
    nodes: list[tuple[str, str]] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)
    props: dict[str, str] = field(default_factory=dict)
    lsusb: str = ""

    @property
    def title(self) -> str:
        return self.product or self.vendor or f"{self.vid}:{self.pid}"

    @property
    def usb_id(self) -> str:
        return f"{self.vid}:{self.pid}"

    @property
    def is_hub(self) -> bool:
        return self.dev_class == 0x09

    def as_text(self) -> str:
        out = [f"{self.title}  [{self.usb_id}]", f"sysfs: {self.syspath}", ""]
        for title, rows in self.sections:
            out.append(f"== {title} ==")
            out += [f"{k}: {v}" for k, v in rows]
            out.append("")
        for i in self.interfaces:
            out.append(f"== Interfaz {i.name} ==")
            out.append(f"clase={class_name(i.cls)} sub=0x{i.subcls or 0:02x} proto=0x{i.proto or 0:02x}")
            out.append(f"driver={i.driver or '(ninguno)'} módulos={', '.join(i.modules) or '-'}")
            out += [f"  {e}" for e in i.endpoints]
            out.append("")
        out.append("== Propiedades udev ==")
        out += [f"{k}={v}" for k, v in sorted(self.props.items())]
        out += ["", "== lsusb -v ==", self.lsusb]
        return "\n".join(out)


def find_modprobe() -> str | None:
    return shutil.which("modprobe") or next(
        (p for p in ("/usr/sbin/modprobe", "/sbin/modprobe") if os.path.exists(p)), None
    )


def resolve_modules(modalias: str | None) -> list[str]:
    mp = find_modprobe()
    if not modalias or not mp:
        return []
    out = run([mp, "--resolve-alias", modalias], timeout=5)
    return [l.strip() for l in out.splitlines() if l.strip() and " " not in l.strip()]


def loaded_modules() -> set[str]:
    txt = read("/proc/modules") or ""
    return {l.split()[0] for l in txt.splitlines() if l}


def read_endpoints(ifpath: str) -> list[str]:
    eps = []
    for e in sorted(os.listdir(ifpath)):
        if not e.startswith("ep_"):
            continue
        p = os.path.join(ifpath, e)
        eps.append(
            "Endpoint {} · {} · {} · máx. paquete {} B · intervalo {}".format(
                read(f"{p}/bEndpointAddress"),
                read(f"{p}/type"),
                read(f"{p}/direction"),
                int(read(f"{p}/wMaxPacketSize") or "0", 16),
                read(f"{p}/bInterval"),
            )
        )
    return eps


def collect_nodes(root: str) -> list[tuple[str, str]]:
    """Busca nodos hijos (tty, block, hidraw, video4linux, sound, net, input...)."""
    nodes: list[tuple[str, str]] = []
    base_depth = root.count(os.sep)
    for cur, dirs, _files in os.walk(root):
        if cur.count(os.sep) - base_depth > 5:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in NODE_SKIP and not d.startswith("ep_")]
        sub = os.path.join(cur, "subsystem")
        if cur != root and os.path.islink(sub):
            subsystem = os.path.basename(os.path.realpath(sub))
            if subsystem in ("usb", "scsi", "scsi_host", "scsi_target", "scsi_device"):
                continue
            uev = dict(
                l.split("=", 1) for l in (read(os.path.join(cur, "uevent")) or "").splitlines() if "=" in l
            )
            if "DEVNAME" in uev:
                nodes.append((subsystem, "/dev/" + uev["DEVNAME"]))
            elif "INTERFACE" in uev:
                nodes.append((subsystem, "interfaz de red " + uev["INTERFACE"]))
            elif subsystem not in ("input",):
                nodes.append((subsystem, os.path.basename(cur)))
    return sorted(set(nodes))


def collect(syspath: str, with_lsusb: bool = True) -> DeviceInfo:
    syspath = os.path.realpath(syspath)
    info = DeviceInfo(syspath=syspath)
    info.vid = (read(f"{syspath}/idVendor") or "").lower()
    info.pid = (read(f"{syspath}/idProduct") or "").lower()
    info.serial = read(f"{syspath}/serial") or ""

    # --- udev ---
    for line in run(["udevadm", "info", "-q", "property", "-p", syspath]).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info.props[k] = v
    p = info.props
    info.vendor = (
        p.get("ID_VENDOR_FROM_DATABASE")
        or (read(f"{syspath}/manufacturer") or "")
        or p.get("ID_VENDOR", "").replace("_", " ")
    )
    info.product = (
        p.get("ID_MODEL_FROM_DATABASE")
        or (read(f"{syspath}/product") or "")
        or p.get("ID_MODEL", "").replace("_", " ")
    )
    info.dev_class = hexint(read(f"{syspath}/bDeviceClass"))
    if info.dev_class is not None:
        info.classes.add(info.dev_class)

    # --- atributos del dispositivo ---
    rows: list[tuple[str, str]] = []
    for fname, label in DEVICE_ATTRS:
        v = read(f"{syspath}/{fname}")
        if v is None or v == "":
            continue
        if fname == "speed":
            v = f"{v} — {SPEEDS.get(v, '')}".rstrip(" —")
        elif fname == "bDeviceClass":
            v = class_name(hexint(v))
        elif fname == "bMaxPower":
            v = v.strip()
        rows.append((label, v))
    general = [
        ("Fabricante (usb.ids)", p.get("ID_VENDOR_FROM_DATABASE", "—")),
        ("Producto (usb.ids)", p.get("ID_MODEL_FROM_DATABASE", "—")),
        ("Ruta sysfs", syspath),
        ("Nodo /dev", p.get("DEVNAME", "—")),
        ("Subsistema / tipo", f"{p.get('SUBSYSTEM', '?')} / {p.get('DEVTYPE', '?')}"),
        ("Interfaces (ID_USB_INTERFACES)", p.get("ID_USB_INTERFACES", "—")),
        ("Driver del dispositivo", os.path.basename(os.path.realpath(f"{syspath}/driver"))
         if os.path.islink(f"{syspath}/driver") else "—"),
        ("Rutas persistentes (ID_PATH)", p.get("ID_PATH", "—")),
        ("Etiquetas udev (TAGS)", p.get("TAGS", "—")),
    ]
    ident_labels = {"Fabricante (descriptor)", "Producto (descriptor)", "Nº de serie", "ID de fabricante (VID)",
                    "ID de producto (PID)", "Versión del dispositivo (bcdDevice)", "Versión de USB",
                    "Velocidad negociada (Mb/s)"}
    info.sections.append(("Identificación", [r for r in rows if r[0] in ident_labels]))
    info.sections.append(("Descriptores y configuración", [r for r in rows if r[0] not in ident_labels]))
    info.sections.append(("Sistema", general))

    power = []
    for fname, label in [
        ("power/control", "Control de energía"),
        ("power/runtime_status", "Estado de energía"),
        ("power/autosuspend_delay_ms", "Retardo de autosuspensión (ms)"),
        ("power/persist", "Persistencia"),
        ("power/wakeup", "Despertar del sistema"),
        ("power/active_duration", "Tiempo activo (ms)"),
        ("power/connected_duration", "Tiempo conectado (ms)"),
        ("urbnum", "URBs procesados"),
    ]:
        v = read(f"{syspath}/{fname}")
        if v:
            power.append((label, v))
    if power:
        info.sections.append(("Energía y estadísticas", power))

    # Topología
    parent = os.path.dirname(syspath)
    pv, pp = read(f"{parent}/idVendor"), read(f"{parent}/idProduct")
    if pv:
        info.sections.append(("Topología", [
            ("Conectado a", f"{pv}:{pp} {read(parent + '/product') or ''}".strip()),
            ("Ruta del padre", parent),
        ]))

    # --- interfaces ---
    loaded = loaded_modules()
    pat = re.compile(r"^" + re.escape(os.path.basename(syspath)) + r":\d+\.\d+$")
    drivers: list[str] = []
    modules: list[str] = []
    for name in sorted(os.listdir(syspath)):
        if not pat.match(name):
            continue
        ip = os.path.join(syspath, name)
        drv = os.path.basename(os.path.realpath(f"{ip}/driver")) if os.path.islink(f"{ip}/driver") else None
        modalias = read(f"{ip}/modalias")
        mods = resolve_modules(modalias)
        cls = hexint(read(f"{ip}/bInterfaceClass"))
        if cls is not None:
            info.classes.add(cls)
        iface = Interface(
            name=name,
            number=read(f"{ip}/bInterfaceNumber") or "?",
            cls=cls,
            subcls=hexint(read(f"{ip}/bInterfaceSubClass")),
            proto=hexint(read(f"{ip}/bInterfaceProtocol")),
            label=read(f"{ip}/interface"),
            driver=drv,
            modalias=modalias,
            modules=[m + (" (cargado)" if m in loaded else "") for m in mods],
            endpoints=read_endpoints(ip),
        )
        info.interfaces.append(iface)
        if drv:
            drivers.append(drv)
        modules += mods
    info.drivers = sorted(set(drivers))
    info.modules = sorted(set(modules))
    info.nodes = collect_nodes(syspath)

    if with_lsusb and shutil.which("lsusb"):
        bus, dev = read(f"{syspath}/busnum"), read(f"{syspath}/devnum")
        if bus and dev:
            info.lsusb = run(["lsusb", "-v", "-s", f"{int(bus)}:{int(dev)}"], timeout=15).strip()
    return info


def list_usb_devices() -> list[str]:
    """Rutas sysfs de todos los dispositivos USB (no interfaces)."""
    base = "/sys/bus/usb/devices"
    return sorted(
        os.path.realpath(os.path.join(base, d))
        for d in os.listdir(base)
        if os.path.exists(os.path.join(base, d, "idVendor"))
    )
