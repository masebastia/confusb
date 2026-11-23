#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera confusb/soporte.py: qué dispositivos USB soportan las herramientas de configuración de Linux.

Se leen de los propios paquetes de Debian, descargados y extraídos sin instalar nada:

    mkdir /tmp/soporte && cd /tmp/soporte
    apt-get download ratbagd solaar openrazer-driver-dkms
    for p in *.deb; do dpkg-deb -x "$p" "ext-${p%%_*}"; done
    python3 tools/generar_soporte.py /tmp/soporte

  libratbag   ext-ratbagd/usr/share/libratbag/*.device            (MIT)
  Solaar      ext-solaar/usr/share/solaar/lib/logitech_receiver/base_usb.py   (GPL-2+)
  OpenRazer   ext-openrazer-driver-dkms/usr/lib/udev/rules.d/99-razer.rules   (GPL-2+)

Solo se guardan identificadores (VID:PID) y nombres de dispositivo, que son datos, no código.
"""
import glob
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def libratbag(d: str) -> dict[str, str]:
    out = {}
    for f in sorted(glob.glob(f"{d}/ext-ratbagd/usr/share/libratbag/*.device")):
        texto = open(f, encoding="utf-8").read()
        nombre = re.search(r"^Name=(.+)$", texto, re.M)
        for m in re.finditer(r"usb:([0-9a-f]{4}):([0-9a-f]{4})", re.search(r"^DeviceMatch=(.+)$", texto, re.M).group(1)):
            out[f"{m.group(1)}:{m.group(2)}"] = nombre.group(1).strip() if nombre else ""
    return out


def solaar(d: str) -> dict[str, str]:
    texto = open(f"{d}/ext-solaar/usr/share/solaar/lib/logitech_receiver/base_usb.py", encoding="utf-8").read()
    tipos = {"_bolt_receiver": "Bolt Receiver", "_unifying_receiver": "Unifying Receiver",
             "_nano_receiver": "Nano Receiver", "_nano_receiver_no_unpair": "Nano Receiver",
             "_nano_receiver_max2": "Nano Receiver", "_lenovo_receiver": "Nano Receiver",
             "_lightspeed_receiver": "Lightspeed Receiver", "_ex100_receiver": "EX100 Receiver"}
    out = {}
    for m in re.finditer(r"^[A-Z0-9_]+ = (_\w+)\(0x([0-9A-Fa-f]{4})\)", texto, re.M):
        vid = "17ef" if m.group(2) == "6042" else "046d"       # el receptor de Lenovo
        out[f"{vid}:{m.group(2).lower()}"] = tipos[m.group(1)]
    return out


def openrazer(d: str) -> list[str]:
    texto = open(f"{d}/ext-openrazer-driver-dkms/usr/lib/udev/rules.d/99-razer.rules", encoding="utf-8").read()
    pids = set()
    for m in re.finditer(r'idProduct\}=="([0-9a-f|]+)"', texto):
        pids.update(m.group(1).split("|"))
    return sorted(f"1532:{p}" for p in pids)


def main(d: str):
    lr, so, rz = libratbag(d), solaar(d), openrazer(d)
    out = ['# SPDX-License-Identifier: GPL-3.0-or-later',
           '"""Dispositivos USB que soportan las herramientas de configuración de Linux (VID:PID).',
           '',
           'GENERADO por tools/generar_soporte.py a partir de los paquetes de Debian 13 (ratbagd 0.18-1, solaar',
           '1.1.14-4, openrazer-driver-dkms 3.10.2). Son solo identificadores y nombres: no hay que instalar nada para',
           'saber si un dispositivo está soportado. Si la herramienta está instalada, sus datos locales mandan."""',
           '',
           '# libratbag (Piper/ratbagctl): ratones y otros periféricos gaming. «VID:PID» → nombre del dispositivo',
           'LIBRATBAG = {']
    out += [f'    "{k}": {v!r},' for k, v in sorted(lr.items())]
    out += ['}', '', '# Solaar: receptores de Logitech (Unifying, Bolt, Nano, Lightspeed…)', 'SOLAAR = {']
    out += [f'    "{k}": {v!r},' for k, v in sorted(so.items())]
    out += ['}', '', '# OpenRazer: productos de Razer (VID 1532)', 'OPENRAZER = frozenset({']
    out += [f'    "{k}",' for k in rz]
    out += ['})', '']
    ruta = os.path.join(RAIZ, "confusb", "soporte.py")
    open(ruta, "w", encoding="utf-8").write("\n".join(out))
    print(f"{ruta}: libratbag {len(lr)}, solaar {len(so)}, openrazer {len(rz)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
