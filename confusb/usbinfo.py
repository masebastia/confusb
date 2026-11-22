# SPDX-License-Identifier: GPL-3.0-or-later
"""Recopila toda la información posible de un dispositivo USB (sysfs + udev + lsusb)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from . import almacenamiento
from .i18n import N_, _

ENV = {**os.environ, "LC_ALL": "C"}

CLASS_NAMES = {
    0x00: N_("Defined at interface level"),
    0x01: N_("Audio"),
    0x02: N_("Communications (CDC)"),
    0x03: N_("Human interface device (HID)"),
    0x05: N_("Physical"),
    0x06: N_("Image"),
    0x07: N_("Printer"),
    0x08: N_("Mass storage"),
    0x09: N_("Hub"),
    0x0A: "CDC-Data",
    0x0B: N_("Smart card (CCID)"),
    0x0D: N_("Content security"),
    0x0E: N_("Video"),
    0x0F: N_("Personal healthcare"),
    0x10: N_("Audio/Video"),
    0x11: "Billboard",
    0xDC: N_("Diagnostic"),
    0xE0: N_("Wireless (e.g. Bluetooth)"),
    0xEF: N_("Miscellaneous"),
    0xFE: N_("Application specific (DFU, IrDA...)"),
    0xFF: N_("Vendor specific"),
}

SPEEDS = {
    "1.5": "Low Speed (1.5 Mb/s) · USB 1.0",
    "12": "Full Speed (12 Mb/s) · USB 1.1",
    "480": "High Speed (480 Mb/s) · USB 2.0",
    "5000": "SuperSpeed (5 Gb/s) · USB 3.0",
    "10000": "SuperSpeed+ (10 Gb/s) · USB 3.1",
    "20000": "SuperSpeed+ (20 Gb/s) · USB 3.2",
}

# Atributos de sysfs del dispositivo: (fichero, etiqueta traducible)
DEVICE_ATTRS = [
    ("manufacturer", N_("Manufacturer (descriptor)")),
    ("product", N_("Product (descriptor)")),
    ("serial", N_("Serial number")),
    ("idVendor", N_("Vendor ID (VID)")),
    ("idProduct", N_("Product ID (PID)")),
    ("bcdDevice", N_("Device version (bcdDevice)")),
    ("version", N_("USB version")),
    ("speed", N_("Negotiated speed (Mb/s)")),
    ("bDeviceClass", N_("Device class")),
    ("bDeviceSubClass", N_("Device subclass")),
    ("bDeviceProtocol", N_("Device protocol")),
    ("bMaxPacketSize0", N_("Max. EP0 packet size")),
    ("bNumConfigurations", N_("Number of configurations")),
    ("bConfigurationValue", N_("Active configuration")),
    ("bNumInterfaces", N_("Number of interfaces")),
    ("bmAttributes", N_("Configuration attributes")),
    ("bMaxPower", N_("Declared maximum power")),
    ("busnum", N_("Bus")),
    ("devnum", N_("Address on the bus")),
    ("devpath", N_("Port path (devpath)")),
    ("maxchild", N_("Child ports")),
    ("removable", N_("Removable")),
    ("authorized", N_("Authorized")),
    ("configuration", N_("Configuration name")),
    ("ltm_capable", "LTM"),
    ("quirks", N_("Kernel quirks")),
]

NODE_SKIP = {"power", "driver", "subsystem", "firmware_node", "device"}
MAX_PROFUNDIDAD = 9   # interfaz › host › target › LUN › block › disco › partición (+ margen)


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
    nombre = CLASS_NAMES.get(code)
    return f"0x{code:02x} · {_(nombre) if nombre else _('Unknown')}"


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
    unidades: list[almacenamiento.Unidad] = field(default_factory=list)   # discos de un dispositivo de almacenamiento
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

    @property
    def es_almacenamiento(self) -> bool:
        return 0x08 in self.classes

    @property
    def capacidad(self) -> int | None:
        """Bytes de la unidad de almacenamiento (None si no es de almacenamiento o no tiene soporte)."""
        return almacenamiento.capacidad(self.unidades)

    def as_text(self) -> str:
        out = [f"{self.title}  [{self.usb_id}]", f"sysfs: {self.syspath}", ""]
        for title, rows in self.sections:
            out.append(f"== {title} ==")
            out += [f"{k}: {v}" for k, v in rows]
            out.append("")
        for i in self.interfaces:
            out.append(_("== Interface {name} ==").format(name=i.name))
            out.append(_("class={cls} subclass=0x{sub:02x} protocol=0x{proto:02x}").format(
                cls=class_name(i.cls), sub=i.subcls or 0, proto=i.proto or 0))
            out.append(_("driver={driver} modules={modules}").format(
                driver=i.driver or _("(none)"), modules=", ".join(i.modules) or "-"))
            out += [f"  Endpoint {e}" for e in i.endpoints]
            out.append("")
        out.append(_("== udev properties =="))
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
            _("{addr} · {type} · {dir} · max. packet {size} B · interval {interval}").format(
                addr=read(f"{p}/bEndpointAddress"),
                type=read(f"{p}/type"),
                dir=read(f"{p}/direction"),
                size=int(read(f"{p}/wMaxPacketSize") or "0", 16),
                interval=read(f"{p}/bInterval"),
            )
        )
    return eps


def collect_nodes(root: str) -> list[tuple[str, str]]:
    """Busca nodos hijos (tty, block, hidraw, video4linux, sound, net, input...)."""
    nodes: list[tuple[str, str]] = []
    base_depth = root.count(os.sep)
    for cur, dirs, _files in os.walk(root):
        if cur.count(os.sep) - base_depth > MAX_PROFUNDIDAD:
            dirs[:] = []
            continue
        # Sin entrar en los dispositivos USB hijos (un hub): sus nodos son de ellos, no del hub.
        dirs[:] = [d for d in dirs if d not in NODE_SKIP and not d.startswith("ep_")
                   and not os.path.exists(os.path.join(cur, d, "idVendor"))]
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
                nodes.append((subsystem, _("network interface {name}").format(name=uev["INTERFACE"])))
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
        rows.append((label, v))        # label = texto fuente (inglés): se traduce al construir las secciones
    general = [
        (_("Manufacturer (usb.ids)"), p.get("ID_VENDOR_FROM_DATABASE", "—")),
        (_("Product (usb.ids)"), p.get("ID_MODEL_FROM_DATABASE", "—")),
        (_("sysfs path"), syspath),
        (_("/dev node"), p.get("DEVNAME", "—")),
        (_("Subsystem / type"), f"{p.get('SUBSYSTEM', '?')} / {p.get('DEVTYPE', '?')}"),
        (_("Interfaces (ID_USB_INTERFACES)"), p.get("ID_USB_INTERFACES", "—")),
        (_("Device driver"), os.path.basename(os.path.realpath(f"{syspath}/driver"))
         if os.path.islink(f"{syspath}/driver") else "—"),
        (_("Persistent paths (ID_PATH)"), p.get("ID_PATH", "—")),
        (_("udev tags (TAGS)"), p.get("TAGS", "—")),
    ]
    ident_labels = ['Manufacturer (descriptor)', 'Product (descriptor)', 'Serial number', 'Vendor ID (VID)', 'Product ID (PID)', 'Device version (bcdDevice)', 'USB version', 'Negotiated speed (Mb/s)']
    info.sections.append((_("Identification"), [(_(k), v) for k, v in rows if k in ident_labels]))
    info.sections.append((_("Descriptors and configuration"), [(_(k), v) for k, v in rows if k not in ident_labels]))
    info.sections.append((_("System"), general))

    power = []
    for fname, label in [
        ("power/control", _("Power control")),
        ("power/runtime_status", _("Power state")),
        ("power/autosuspend_delay_ms", _("Autosuspend delay (ms)")),
        ("power/persist", _("Persistence")),
        ("power/wakeup", _("System wake-up")),
        ("power/active_duration", _("Active time (ms)")),
        ("power/connected_duration", _("Connected time (ms)")),
        ("urbnum", _("URBs processed")),
    ]:
        v = read(f"{syspath}/{fname}")
        if v:
            power.append((label, v))
    if power:
        info.sections.append((_("Power and statistics"), power))

    # Topología
    parent = os.path.dirname(syspath)
    pv, pp = read(f"{parent}/idVendor"), read(f"{parent}/idProduct")
    if pv:
        info.sections.append((_("Topology"), [
            (_("Connected to"), f"{pv}:{pp} {read(parent + '/product') or ''}".strip()),
            (_("Parent path"), parent),
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
            modules=[_("{module} (loaded)").format(module=m) if m in loaded else m for m in mods],
            endpoints=read_endpoints(ip),
        )
        info.interfaces.append(iface)
        if drv:
            drivers.append(drv)
        modules += mods
    info.drivers = sorted(set(drivers))
    info.modules = sorted(set(modules))
    info.nodes = collect_nodes(syspath)

    # --- almacenamiento: capacidad, particiones y montaje ---
    bloques = [n for sub, n in info.nodes if sub == "block"]
    if bloques:
        info.unidades = almacenamiento.leer(bloques)
        if info.unidades:
            info.sections.insert(1, (_("Storage"), almacenamiento.filas(info.unidades)))

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


def resolve_target(target: str) -> str | None:
    """Acepta '1-5', 'VID:PID' o una ruta sysfs."""
    if os.path.isabs(target):
        return target
    cand = f"/sys/bus/usb/devices/{target}"
    if os.path.exists(cand):
        return os.path.realpath(cand)
    for p in list_usb_devices():
        if read(p + "/idVendor") and f"{read(p + '/idVendor')}:{read(p + '/idProduct')}" == target.lower():
            return p
    return None
