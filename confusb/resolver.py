# SPDX-License-Identifier: GPL-3.0-or-later
"""Busca drivers y aplicaciones para un dispositivo USB.

Fuentes (de más rápida a más lenta; cada grupo se emite en cuanto está listo):
  1. Estado del driver del kernel (sysfs/modules.alias)
  2. Conocimiento integrado por clase USB y fabricante (kb.py)
  3. Paquetes Debian por nombre (apt-cache, local)
  4. Aplicaciones Flatpak (flatpak search)
  5. Firmware gestionado por fwupd
  6. Enlaces web (búsqueda del fabricante, linux-hardware.org)

No se envía nada a Internet salvo que el usuario pulse un enlace o `flatpak search`
consulte el catálogo que ya tiene configurado.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

from . import kb
from .i18n import _
from .usbinfo import CLASS_NAMES, ENV, DeviceInfo, run


@dataclass
class Action:
    label: str
    kind: str                     # apt | flatpak | launch | terminal | capture | url
    payload: list[str] | str
    enabled: bool = True
    tooltip: str = ""


@dataclass
class Item:
    title: str
    desc: str = ""
    status: str = ""              # texto corto a la derecha (p. ej. "Instalado")
    actions: list[Action] = field(default_factory=list)


@dataclass
class Group:
    title: str
    items: list[Item]
    subtitle: str = ""


# ------------------------------------------------------------------ utilidades

def pkg_states(pkgs: list[str]) -> dict[str, str]:
    """installed | available | missing para cada paquete (una sola llamada a apt-cache)."""
    states = {p: "missing" for p in pkgs}
    if not pkgs or not shutil.which("apt-cache"):
        return states
    try:
        out = subprocess.run(["apt-cache", "policy", *pkgs], capture_output=True, text=True,
                             timeout=15, env=ENV).stdout
    except (OSError, subprocess.TimeoutExpired):
        return states
    cur = None
    inst = cand = None

    def flush():
        if cur is None:
            return
        if inst and inst != "(none)":
            states[cur] = "installed"
        elif cand and cand != "(none)":
            states[cur] = "available"

    for line in out.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            flush()
            cur, inst, cand = line[:-1], None, None
        elif line.strip().startswith("Installed:"):
            inst = line.split(":", 1)[1].strip()
        elif line.strip().startswith("Candidate:"):
            cand = line.split(":", 1)[1].strip()
    flush()
    return states


def tokens(*texts: str, limit: int = 4) -> list[str]:
    seen: list[str] = []
    for t in texts:
        for w in re.findall(r"[A-Za-z0-9]+", t or ""):
            lw = w.lower()
            if len(w) < 3 or lw in kb.GENERIC_WORDS or lw in seen or w.isdigit():
                continue
            seen.append(lw)
    return seen[:limit]


def word_match(tok: str, text: str) -> bool:
    """El token aparece como palabra completa (separada por no alfanuméricos)."""
    return re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", text.lower()) is not None


def terminal_cmd() -> list[str] | None:
    for t, args in (("gnome-terminal", ["--"]), ("kgx", ["-e"]), ("konsole", ["-e"]),
                    ("xfce4-terminal", ["-x"]), ("x-terminal-emulator", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(t):
            return [t, *args]
    return None


def pkg_version(pkg: str) -> str:
    out = run(["dpkg-query", "-W", "-f=${Version}", pkg], timeout=5).strip()
    return out if out and " " not in out else ""


def flatpaks_instalados() -> set[str]:
    if not shutil.which("flatpak"):
        return set()
    return set(run(["flatpak", "list", "--app", "--columns=application"], timeout=10).split())


def detectar_externa(ext: dict, states: dict[str, str]) -> tuple[bool, str]:
    """¿Está instalada una aplicación que no viene de apt ni de Flatpak? (por paquete o por comando)."""
    for p in ext.get("paquetes", []):
        if states.get(p) == "installed":
            return True, pkg_version(p)
    if any(shutil.which(c) for c in ext.get("comandos", [])):
        return True, ""
    return False, ""


def make_item_from_kb(entry: dict, states: dict[str, str], flatpaks: set[str] | frozenset = frozenset()) -> Item:
    """Elemento ofrecido: siempre dice si ya está instalado y solo ofrece instalar lo que falta.
    El estado (item.status) es el texto fuente en inglés: la interfaz lo clasifica y lo traduce."""
    pkgs = entry.get("packages", [])
    instalados = [p for p in pkgs if states.get(p) == "installed"]
    missing = [p for p in pkgs if states.get(p) == "available"]
    unavailable = [p for p in pkgs if states.get(p) == "missing"]
    desc = _(entry["desc"]).format(**entry["desc_args"]) if entry.get("desc_args") else _(entry.get("desc", ""))
    item = Item(_(entry["title"]), desc)
    notas: list[str] = []
    falta = bool(missing)

    if pkgs:
        notas.append(_("Packages: {list}").format(list=", ".join(pkgs)))
        if instalados and (missing or unavailable):
            notas.append(_("Already installed: {list}").format(list=", ".join(instalados)))
        if unavailable:
            notas.append(_("Not in the repositories: {list}").format(list=", ".join(unavailable)))
        if missing:
            item.actions.append(Action(_("Install {packages}").format(packages=", ".join(missing)), "apt", missing))

    ext = entry.get("externa")
    if ext:
        puesta, version = detectar_externa(ext, states)
        if puesta:
            notas.append(_("The application is already installed on your computer (version {version}).").format(version=version)
                         if version else _("The application is already installed on your computer."))
            if ext.get("lanzar"):
                exe = ext["lanzar"][0]
                item.actions.append(Action(_("Open {name}").format(name=ext["nombre"]), "launch", ext["lanzar"],
                                           enabled=shutil.which(exe) is not None,
                                           tooltip="" if shutil.which(exe) else _("«{exe}» not found").format(exe=exe)))
        else:
            falta = True
            notas.append(_("It is not installed."))
            item.actions.append(Action(_("Download {name}").format(name=ext["nombre"]), "url", ext["url"]))

    fp = entry.get("flatpak")
    if fp:
        if fp in flatpaks:
            notas.append(_("Already installed as a Flatpak ({id}).").format(id=fp))
            item.actions.append(Action(_("Open (Flatpak)"), "launch", ["flatpak", "run", fp]))
        else:
            falta = True
            item.actions.append(Action(_("Install Flatpak {id}").format(id=fp), "flatpak", fp))

    if falta:
        item.status = "Needs installing"
    elif unavailable:
        item.status = "Not in the repositories"
    elif pkgs or ext or fp:
        item.status = "Installed"
    if item.status == "Installed" and pkgs and not ext and not fp:
        notas.append(_("Already installed on your computer."))
    item.desc = "\n".join([item.desc, *notas]).strip()

    for app in entry.get("apps", []):
        exe = app["cmd"][0]
        ok = shutil.which(exe) is not None
        tip = "" if ok else _("Install «{name}» first").format(name=app.get("needs", exe))
        kind = "capture" if app.get("capture") else ("terminal" if app.get("terminal") else "launch")
        item.actions.append(Action(_(app["label"]), kind, app["cmd"], enabled=ok, tooltip=tip))
    return item


# -------------------------------------------------------------------- grupos

def kernel_group(info: DeviceInfo) -> Group:
    items: list[Item] = []
    if info.is_hub:
        items.append(Item(_("USB hub"), _("Managed by the kernel's «hub» driver."), "OK"))
    for i in info.interfaces:
        cname = _(CLASS_NAMES[i.cls]) if i.cls in CLASS_NAMES else "?"
        label = _("Interface {number} · {label}").format(number=i.number, label=i.label or cname)
        mods = ", ".join(i.modules) if i.modules else _("none found")
        if i.driver:
            items.append(Item(label, _("Driver: {driver}").format(driver=i.driver) + "\n"
                              + _("Candidate modules: {modules}").format(modules=mods), "Active driver"))
        elif i.cls == 0x0B:
            items.append(Item(label, _("Normal: CCID smart card readers do not use a kernel driver; they are "
                                       "managed by the pcscd daemon (user space) with libccid."), "User space"))
        elif i.modules:
            items.append(Item(label, _("No driver bound, but there are candidate modules: {modules}.").format(modules=mods)
                              + "\n" + _("Try: sudo modprobe <module>"), "Not bound"))
        else:
            items.append(Item(label, _("The kernel has no module for this interface.") + "\n"
                              + _("It probably needs user-space software (see below) or an external driver."), "No driver"))
    if not items:
        items.append(Item(_("No interfaces"), _("The device's interfaces could not be read.")))
    return Group(_("Kernel driver status"), items)


def kb_groups(info: DeviceInfo) -> list[Group]:
    entries: list[tuple[str, dict]] = []
    for cls in sorted(info.classes):
        nombre = _(CLASS_NAMES[cls]) if cls in CLASS_NAMES else str(cls)
        for e in kb.CLASS_KB.get(cls, []):
            entries.append((_("Recommended for the «{name}» class").format(name=nombre), e))
    for e in kb.VENDOR_KB.get(info.vid, []):
        entries.append((_("Recommended for the manufacturer ({vid})").format(vid=info.vid), e))
    if not entries:
        return []
    all_pkgs = sorted({p for _t, e in entries for p in (*e.get("packages", []), *e.get("externa", {}).get("paquetes", []))})
    states = pkg_states(all_pkgs)
    flatpaks = flatpaks_instalados() if any(e.get("flatpak") for _t, e in entries) else set()
    groups: dict[str, list[Item]] = {}
    for title, e in entries:
        groups.setdefault(title, []).append(make_item_from_kb(e, states, flatpaks))
    return [Group(t, items) for t, items in groups.items()]


def apt_group(info: DeviceInfo) -> Group | None:
    if not shutil.which("apt-cache"):
        return None
    queries = tokens(info.product, info.vendor, limit=4)
    found: dict[str, str] = {}
    for q in queries:
        out = run(["apt-cache", "search", "--names-only", q], timeout=15)
        for line in out.splitlines()[:40]:
            if " - " in line:
                name, desc = line.split(" - ", 1)
                if (word_match(q, name) and not name.endswith(("-dbgsym", "-doc", "-dev", "-prof", "-dbg"))
                        and len(found) < 12):
                    found.setdefault(name, desc)
    if not found:
        return None
    states = pkg_states(list(found))
    items = []
    for name, desc in found.items():
        st = states.get(name)
        it = Item(name, desc, "Installed" if st == "installed" else "")
        if st == "available":
            it.actions.append(Action(_("Install"), "apt", [name]))
        items.append(it)
    return Group(_("Debian packages whose name matches"), items,
                 subtitle=_("Searched for: {terms}").format(terms=", ".join(queries)))


def flatpak_group(info: DeviceInfo) -> Group | None:
    if not shutil.which("flatpak"):
        return None
    queries = tokens(info.vendor, info.product, limit=3)
    installed = set(run(["flatpak", "list", "--app", "--columns=application"], timeout=10).split())
    found: dict[str, tuple[str, str]] = {}
    for q in queries:
        out = run(["flatpak", "search", "--columns=application,name,description", q], timeout=25)
        for line in out.splitlines():
            parts = line.split("\t")
            if (len(parts) >= 2 and "." in parts[0] and " " not in parts[0] and len(found) < 8
                    and word_match(q, " ".join(parts[:2]))):
                found.setdefault(parts[0], (parts[1], parts[2] if len(parts) > 2 else ""))
    if not found:
        return None
    items = []
    for app_id, (name, desc) in found.items():
        it = Item(name, f"{desc}\n{app_id}", "Installed" if app_id in installed else "")
        if app_id in installed:
            it.actions.append(Action(_("Open"), "launch", ["flatpak", "run", app_id]))
        else:
            it.actions.append(Action(_("Install"), "flatpak", app_id))
        items.append(it)
    return Group(_("Related Flatpak applications"), items,
                 subtitle=_("Searched for: {terms}").format(terms=", ".join(queries)))


def fwupd_group(info: DeviceInfo) -> Group | None:
    if not shutil.which("fwupdmgr") or not info.vid:
        return None
    out = run(["fwupdmgr", "get-devices", "--json"], timeout=25)
    if f"VID_{info.vid.upper()}&PID_{info.pid.upper()}" not in out.upper():
        return None
    return Group("Firmware (fwupd)", [Item(
        _("fwupd recognizes this device"),
        _("Official firmware updates from the manufacturer (LVFS) can be checked and applied."),
        "Supported",
        [Action(_("Check for updates"), "capture", ["fwupdmgr", "get-updates", "--no-unreported-check"])],
    )])


def web_group(info: DeviceInfo) -> Group:
    name = f"{info.vendor} {info.product}".strip() or info.usb_id
    q = lambda s: urllib.parse.quote_plus(s)
    consulta1 = f"{name} linux driver download"
    consulta2 = f"{info.vendor} support downloads"
    return Group(_("Manufacturer website and databases"), [
        Item(_("Search for the manufacturer's official driver"), _("Search: «{query}»").format(query=consulta1), "",
             [Action(_("Open search"), "url", "https://duckduckgo.com/?q=" + q(consulta1))]),
        Item(_("Official site / support"), _("Search: «{query}»").format(query=consulta2), "",
             [Action(_("Open search"), "url", "https://duckduckgo.com/?q=" + q(consulta2))]),
        Item("Linux Hardware Database",
             _("Probes from other users with this same device and the driver they used."), "",
             [Action(_("Open"), "url", f"https://linux-hardware.org/?id=usb:{info.vid}-{info.pid}")]),
        Item(_("USB ID database"), _("Page for ID {id}.").format(id=info.usb_id), "",
             [Action(_("Open"), "url", f"https://devicehunt.com/view/type/usb/vendor/{info.vid.upper()}/device/{info.pid.upper()}")]),
        *_class_links(info),
    ])


def _class_links(info: DeviceInfo) -> list[Item]:
    if 0x0B in info.classes:
        return [
            Item(_("DNIe: official portal"), _("Drivers, PKCS#11 module and guides for the Spanish electronic ID card."),
                 "", [Action(_("Open the DNIe portal"), "url", "https://www.dnielectronico.es/")]),
        ]
    return []


# ----------------------------------------------------------------------- API

def resolve(info: DeviceInfo, emit: Callable[[Group], None]) -> None:
    """Calcula los grupos y llama a emit(group) a medida que están listos (hilo de trabajo)."""
    emit(kernel_group(info))
    for g in kb_groups(info):
        emit(g)
    for fn in (apt_group, flatpak_group, fwupd_group):
        try:
            g = fn(info)
        except Exception as e:  # una fuente fallida no debe tumbar las demás
            g = Group(_("Search error"), [Item(_("Error while querying"), str(e))])
        if g:
            emit(g)
    emit(web_group(info))
