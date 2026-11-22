# SPDX-License-Identifier: GPL-3.0-or-later
"""Conocimiento integrado: qué paquetes/aplicaciones hacen funcionar cada tipo de dispositivo.

Formato de cada entrada:
  title, desc            texto mostrado
  packages               paquetes Debian a instalar
  apps                   [{label, cmd, terminal?, capture?, needs?}]  (needs = paquete que provee cmd[0])
  links                  [(etiqueta, url)]
"""

CLASS_KB: dict[int, list[dict]] = {
    0x0B: [  # Lectores de tarjetas inteligentes (DNIe, tarjetas bancarias, FNMT...)
        {
            "title": "Servicio PC/SC y controladores CCID",
            "desc": "pcscd es el demonio que gestiona los lectores de tarjetas; libccid trae el controlador "
                    "para lectores USB estándar (CCID). Sin pcscd el lector se ve en USB pero ninguna "
                    "aplicación puede usarlo.",
            "packages": ["pcscd", "libccid"],
        },
        {
            "title": "OpenSC (PKCS#11, soporta DNIe y otras tarjetas)",
            "desc": "Librería y herramientas para tarjetas criptográficas. Incluye soporte del DNIe "
                    "(3.0/4.0) y el módulo PKCS#11 que usan Firefox/Chromium y AutoFirma. Para DNIe "
                    "antiguos (2.0) puede hacer falta el módulo oficial del DNIe.",
            "packages": ["opensc", "opensc-pkcs11"],
            "apps": [
                {"label": "Listar lectores", "cmd": ["opensc-tool", "--list-readers"],
                 "capture": True, "needs": "opensc"},
                {"label": "Info de la tarjeta (ATR)", "cmd": ["opensc-tool", "--atr"],
                 "capture": True, "needs": "opensc"},
                {"label": "Listar slots PKCS#11", "cmd": ["pkcs11-tool", "--list-slots"],
                 "capture": True, "needs": "opensc"},
                {"label": "Listar certificados", "cmd": ["pkcs11-tool", "--list-objects", "--type", "cert"],
                 "capture": True, "needs": "opensc"},
            ],
        },
        {
            "title": "pcsc-tools (monitor de lectores y tarjetas)",
            "desc": "pcsc_scan muestra en tiempo real cuándo se inserta/retira una tarjeta y decodifica "
                    "su ATR.",
            "packages": ["pcsc-tools"],
            "apps": [{"label": "Abrir pcsc_scan", "cmd": ["pcsc_scan"], "terminal": True,
                      "needs": "pcsc-tools"}],
        },
    ],
    0x08: [
        {"title": "Almacenamiento masivo", "desc": "El sistema lo monta automáticamente (udisks2). "
         "Para formatear o inspeccionar usa Discos.", "packages": ["udisks2"],
         "apps": [{"label": "Abrir Discos", "cmd": ["gnome-disks"], "needs": "gnome-disk-utility"}]},
    ],
    0x07: [
        {"title": "Impresora (CUPS)", "desc": "CUPS detecta impresoras USB automáticamente; "
         "se configura en Ajustes → Impresoras.", "packages": ["cups", "system-config-printer"],
         "apps": [{"label": "Configurar impresoras", "cmd": ["system-config-printer"],
                   "needs": "system-config-printer"}]},
    ],
    0x0E: [
        {"title": "Cámara / vídeo (UVC)", "desc": "El controlador uvcvideo del kernel la soporta. "
         "Pruébala con Snapshot/Cheese.", "packages": ["v4l-utils"],
         "apps": [{"label": "Listar dispositivos de vídeo", "cmd": ["v4l2-ctl", "--list-devices"],
                   "capture": True, "needs": "v4l-utils"},
                  {"label": "Abrir Snapshot", "cmd": ["snapshot"], "needs": "snapshot"}]},
    ],
    0x01: [
        {"title": "Audio USB", "desc": "Soportado por snd-usb-audio. Ajusta volúmenes y salidas "
         "con pavucontrol.", "packages": ["pavucontrol"],
         "apps": [{"label": "Control de volumen", "cmd": ["pavucontrol"], "needs": "pavucontrol"}]},
    ],
    0xE0: [
        {"title": "Bluetooth", "desc": "Pila BlueZ con gestor gráfico.", "packages": ["bluez", "blueman"],
         "apps": [{"label": "Gestor Bluetooth", "cmd": ["blueman-manager"], "needs": "blueman"}]},
    ],
    0x06: [
        {"title": "Cámara fotográfica / escáner de imagen", "desc": "libgphoto2 para cámaras PTP; "
         "SANE para escáneres.", "packages": ["gphoto2", "sane-utils", "simple-scan"],
         "apps": [{"label": "Detectar cámaras", "cmd": ["gphoto2", "--auto-detect"], "capture": True,
                   "needs": "gphoto2"},
                  {"label": "Escanear documentos", "cmd": ["simple-scan"], "needs": "simple-scan"}]},
    ],
    0xFE: [
        {"title": "Dispositivo DFU / específico de aplicación", "desc": "Para actualizar firmware "
         "por DFU.", "packages": ["dfu-util"],
         "apps": [{"label": "Listar dispositivos DFU", "cmd": ["dfu-util", "-l"], "capture": True,
                   "needs": "dfu-util"}]},
    ],
    0x02: [
        {"title": "Módem / puerto serie CDC", "desc": "ModemManager gestiona módems; para consolas "
         "serie usa minicom/picocom.", "packages": ["modemmanager", "picocom"],
         "apps": [{"label": "Listar módems", "cmd": ["mmcli", "-L"], "capture": True,
                   "needs": "modemmanager"}]},
    ],
}

# Conocimiento por fabricante (VID) y, opcionalmente, producto (VID:PID)
VENDOR_KB: dict[str, list[dict]] = {
    "046d": [{"title": "Logitech: Solaar", "desc": "Gestiona receptores Unifying/Bolt y dispositivos "
              "Logitech.", "packages": ["solaar"], "apps": [{"label": "Abrir Solaar", "cmd": ["solaar"],
              "needs": "solaar"}]}],
    "1050": [{"title": "Yubico: herramientas YubiKey", "desc": "Gestor de YubiKey y soporte U2F/PAM.",
              "packages": ["yubikey-manager", "libpam-u2f", "yubikey-personalization"],
              "apps": [{"label": "Información de la YubiKey", "cmd": ["ykman", "info"], "capture": True,
                        "needs": "yubikey-manager"}]}],
    "2341": [{"title": "Arduino", "desc": "IDE y CLI de Arduino.", "packages": ["arduino-cli"],
              "flatpak": "cc.arduino.IDE2"}],
    "0483": [{"title": "STMicroelectronics (ST-Link/DFU)", "desc": "Herramientas ST-Link.",
              "packages": ["stlink-tools"]}],
    "05ac": [{"title": "Apple (iPhone/iPad)", "desc": "usbmuxd + libimobiledevice.",
              "packages": ["usbmuxd", "libimobiledevice-utils", "ifuse"],
              "apps": [{"label": "Información del dispositivo", "cmd": ["ideviceinfo"], "capture": True,
                        "needs": "libimobiledevice-utils"}]}],
    "18d1": [{"title": "Android / Google", "desc": "ADB y acceso MTP.", "packages": ["adb", "gvfs-backends"],
              "apps": [{"label": "adb devices", "cmd": ["adb", "devices", "-l"], "capture": True,
                        "needs": "adb"}]}],
    "04e8": [{"title": "Samsung (Android)", "desc": "ADB y acceso MTP.", "packages": ["adb", "gvfs-backends"]}],
    "03f0": [{"title": "HP: HPLIP", "desc": "Controladores y utilidades de impresoras/escáneres HP.",
              "packages": ["hplip"], "apps": [{"label": "HP Toolbox", "cmd": ["hp-toolbox"], "needs": "hplip-gui"}]}],
    "04a9": [{"title": "Canon", "desc": "Soporte de impresoras/escáneres Canon.", "packages": ["printer-driver-gutenprint"]}],
    "04b8": [{"title": "Epson", "desc": "Soporte de impresoras/escáneres Epson.",
              "packages": ["printer-driver-escpr", "sane-utils"]}],
    "0bda": [{"title": "Realtek: firmware", "desc": "Firmware de adaptadores Wi-Fi/Bluetooth/Ethernet Realtek.",
              "packages": ["firmware-realtek"]}],
    "0cf3": [{"title": "Qualcomm Atheros: firmware", "desc": "Firmware Atheros.", "packages": ["firmware-atheros"]}],
    "0e8d": [{"title": "MediaTek: firmware", "desc": "Firmware MediaTek.", "packages": ["firmware-misc-nonfree"]}],
    "1a86": [{"title": "WCH CH340 (serie USB)", "desc": "Soportado por el kernel (ch341).",
              "packages": ["picocom"]}],
    "0403": [{"title": "FTDI (serie USB)", "desc": "Soportado por el kernel (ftdi_sio).", "packages": ["picocom"]}],
    "10c4": [{"title": "Silicon Labs (CP210x)", "desc": "Soportado por el kernel (cp210x).", "packages": ["picocom"]}],
    "1d50": [{"title": "OpenMoko/proyectos libres", "desc": "Muchos dispositivos libres usan este VID.",
              "packages": ["dfu-util"]}],
}

# Palabras demasiado genéricas para buscar paquetes por nombre
GENERIC_WORDS = {
    "usb", "device", "reader", "controller", "adapter", "adaptor", "composite", "hub", "mouse", "keyboard",
    "camera", "wireless", "receiver", "dongle", "interface", "card", "smartcard", "technology", "corp",
    "inc", "ltd", "co", "corporation", "international", "electronics", "gaming", "audio", "storage",
    "drive", "flash", "disk", "mass", "bluetooth", "hci", "mode", "microelectronics", "systems", "the", "micro", "radio", "silicon", "cambridge", "generic", "emv", "smart", "digital", "tech", "group", "limited",
    "semiconductor", "semiconductors", "industrial", "computer", "computers", "products", "optical",
}
