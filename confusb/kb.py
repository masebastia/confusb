# SPDX-License-Identifier: GPL-3.0-or-later
"""Conocimiento integrado: qué paquetes y aplicaciones hacen funcionar cada tipo de dispositivo.

Formato de cada entrada (los textos llevan N_() para poder traducirlos; los nombres de marca van tal cual):
  title, desc            texto mostrado (desc_args: valores para los {marcadores} de desc)
  packages               paquetes Debian a instalar
  externa                aplicación que se instala por fuera de los repositorios: {nombre, paquetes,
                         comandos, lanzar, url}; se detecta si ya está instalada
  flatpak                id de la aplicación Flatpak equivalente
  apps                   [{label, cmd, terminal?, capture?, needs?}]  (needs = paquete que provee cmd[0])
"""
from .i18n import N_

CLASS_KB: dict[int, list[dict]] = {
    0x0B: [  # Lectores de tarjetas inteligentes (DNIe, tarjetas bancarias, FNMT...)
        {
            "title": N_("PC/SC service and CCID drivers"),
            "desc": N_("pcscd is the daemon that manages smart card readers; libccid provides the driver for standard USB readers (CCID). Without pcscd the reader shows up in USB but no application can use it."),
            "packages": ["pcscd", "libccid"],
        },
        {
            "title": N_("OpenSC (PKCS#11, supports DNIe and other cards)"),
            "desc": N_("Library and tools for cryptographic cards. It includes support for the DNIe (3.0/4.0) and the PKCS#11 module used by Firefox/Chromium and AutoFirma. Older DNIe cards (2.0) may need the official DNIe module."),
            "packages": ["opensc", "opensc-pkcs11"],
            "apps": [
                {"label": N_("List readers"), "cmd": ["opensc-tool", "--list-readers"], "capture": True, "needs": "opensc"},
                {"label": N_("Card info (ATR)"), "cmd": ["opensc-tool", "--atr"], "capture": True, "needs": "opensc"},
                {"label": N_("List PKCS#11 slots"), "cmd": ["pkcs11-tool", "--list-slots"], "capture": True, "needs": "opensc"},
                {"label": N_("List certificates"), "cmd": ["pkcs11-tool", "--list-objects", "--type", "cert"],
                 "capture": True, "needs": "opensc"},
            ],
        },
        {
            "title": N_("pcsc-tools (reader and card monitor)"),
            "desc": N_("pcsc_scan shows in real time when a card is inserted or removed and decodes its ATR."),
            "packages": ["pcsc-tools"],
            "apps": [{"label": N_("Open pcsc_scan"), "cmd": ["pcsc_scan"], "terminal": True, "needs": "pcsc-tools"}],
        },
        {
            "title": N_("AutoFirma (electronic signature)"),
            "desc": N_("Official Spanish Government application to sign documents with the DNIe or a digital certificate. It is not in the Debian repositories: it is downloaded from firmaelectronica.gob.es."),
            # «externa»: se instala por fuera de apt/Flatpak; se detecta por paquete o por comando
            "externa": {"nombre": "AutoFirma", "paquetes": ["autofirma"], "comandos": ["autofirma", "AutoFirma"],
                        "lanzar": ["autofirma"], "url": "https://firmaelectronica.gob.es/Home/Descargas.html"},
        },
    ],
    0x08: [
        {"title": N_("Mass storage"), "desc": N_("The system mounts it automatically (udisks2). To format or inspect it, use Disks."), "packages": ["udisks2"],
         "apps": [{"label": N_("Open Disks"), "cmd": ["gnome-disks"], "needs": "gnome-disk-utility"}]},
    ],
    0x07: [
        {"title": N_("Printer (CUPS)"), "desc": N_("CUPS detects USB printers automatically; it is configured in Settings → Printers."), "packages": ["cups", "system-config-printer"],
         "apps": [{"label": N_("Configure printers"), "cmd": ["system-config-printer"], "needs": "system-config-printer"}]},
    ],
    0x0E: [
        {"title": N_("Camera / video (UVC)"), "desc": N_("The kernel's uvcvideo driver supports it. Try it with Snapshot/Cheese."), "packages": ["v4l-utils"],
         "apps": [{"label": N_("List video devices"), "cmd": ["v4l2-ctl", "--list-devices"], "capture": True, "needs": "v4l-utils"},
                  {"label": N_("Open Snapshot"), "cmd": ["snapshot"], "needs": "snapshot"}]},
    ],
    0x01: [
        {"title": N_("USB audio"), "desc": N_("Supported by snd-usb-audio. Adjust volumes and outputs with pavucontrol."), "packages": ["pavucontrol"],
         "apps": [{"label": N_("Volume control"), "cmd": ["pavucontrol"], "needs": "pavucontrol"}]},
    ],
    0xE0: [
        {"title": "Bluetooth", "desc": N_("BlueZ stack with a graphical manager."), "packages": ["bluez", "blueman"],
         "apps": [{"label": N_("Bluetooth manager"), "cmd": ["blueman-manager"], "needs": "blueman"}]},
    ],
    0x06: [
        {"title": N_("Still camera / image scanner"), "desc": N_("libgphoto2 for PTP cameras; SANE for scanners."), "packages": ["gphoto2", "sane-utils", "simple-scan"],
         "apps": [{"label": N_("Detect cameras"), "cmd": ["gphoto2", "--auto-detect"], "capture": True, "needs": "gphoto2"},
                  {"label": N_("Scan documents"), "cmd": ["simple-scan"], "needs": "simple-scan"}]},
    ],
    0xFE: [
        {"title": N_("DFU / application specific device"), "desc": N_("To update firmware over DFU."), "packages": ["dfu-util"],
         "apps": [{"label": N_("List DFU devices"), "cmd": ["dfu-util", "-l"], "capture": True, "needs": "dfu-util"}]},
    ],
    0x02: [
        {"title": N_("Modem / CDC serial port"), "desc": N_("ModemManager manages modems; for serial consoles use minicom/picocom."), "packages": ["modemmanager", "picocom"],
         "apps": [{"label": N_("List modems"), "cmd": ["mmcli", "-L"], "capture": True, "needs": "modemmanager"}]},
    ],
}

# Conocimiento por fabricante (VID)
VENDOR_KB: dict[str, list[dict]] = {
    "046d": [{"title": "Logitech: Solaar", "desc": N_("Manages Unifying/Bolt receivers and Logitech devices."), "packages": ["solaar"],
              "apps": [{"label": N_("Open Solaar"), "cmd": ["solaar"], "needs": "solaar"}]}],
    "1050": [{"title": N_("Yubico: YubiKey tools"), "desc": N_("YubiKey manager and U2F/PAM support."),
              "packages": ["yubikey-manager", "libpam-u2f", "yubikey-personalization"],
              "apps": [{"label": N_("YubiKey information"), "cmd": ["ykman", "info"], "capture": True, "needs": "yubikey-manager"}]}],
    "2341": [{"title": "Arduino", "desc": N_("Arduino IDE and CLI."), "packages": ["arduino-cli"], "flatpak": "cc.arduino.IDE2"}],
    "0483": [{"title": "STMicroelectronics (ST-Link/DFU)", "desc": N_("ST-Link tools."), "packages": ["stlink-tools"]}],
    "05ac": [{"title": "Apple (iPhone/iPad)", "desc": "usbmuxd + libimobiledevice.",
              "packages": ["usbmuxd", "libimobiledevice-utils", "ifuse"],
              "apps": [{"label": N_("Device information"), "cmd": ["ideviceinfo"], "capture": True, "needs": "libimobiledevice-utils"}]}],
    "18d1": [{"title": "Android / Google", "desc": N_("ADB and MTP access."), "packages": ["adb", "gvfs-backends"],
              "apps": [{"label": "adb devices", "cmd": ["adb", "devices", "-l"], "capture": True, "needs": "adb"}]}],
    "04e8": [{"title": "Samsung (Android)", "desc": N_("ADB and MTP access."), "packages": ["adb", "gvfs-backends"]}],
    "03f0": [{"title": "HP: HPLIP", "desc": N_("Drivers and utilities for HP printers and scanners."), "packages": ["hplip"],
              "apps": [{"label": "HP Toolbox", "cmd": ["hp-toolbox"], "needs": "hplip-gui"}]}],
    "04a9": [{"title": "Canon", "desc": N_("Support for Canon printers and scanners."), "packages": ["printer-driver-gutenprint"]}],
    "04b8": [{"title": "Epson", "desc": N_("Support for Epson printers and scanners."), "packages": ["printer-driver-escpr", "sane-utils"]}],
    "0bda": [{"title": "Realtek: firmware", "desc": N_("Firmware for Realtek Wi-Fi/Bluetooth/Ethernet adapters."), "packages": ["firmware-realtek"]}],
    "0cf3": [{"title": "Qualcomm Atheros: firmware", "desc": N_("Atheros firmware."), "packages": ["firmware-atheros"]}],
    "0e8d": [{"title": "MediaTek: firmware", "desc": N_("MediaTek firmware."), "packages": ["firmware-misc-nonfree"]}],
    "1a86": [{"title": N_("WCH CH340 (USB serial)"), "desc": N_("Supported by the kernel ({module})."), "desc_args": {"module": "ch341"}, "packages": ["picocom"]}],
    "0403": [{"title": N_("FTDI (USB serial)"), "desc": N_("Supported by the kernel ({module})."), "desc_args": {"module": "ftdi_sio"}, "packages": ["picocom"]}],
    "10c4": [{"title": "Silicon Labs (CP210x)", "desc": N_("Supported by the kernel ({module})."), "desc_args": {"module": "cp210x"}, "packages": ["picocom"]}],
    "1d50": [{"title": N_("OpenMoko / free projects"), "desc": N_("Many free hardware devices use this VID."), "packages": ["dfu-util"]}],
}

# Palabras demasiado genéricas para buscar paquetes por nombre
GENERIC_WORDS = {
    "usb", "device", "reader", "controller", "adapter", "adaptor", "composite", "hub", "mouse", "keyboard",
    "camera", "wireless", "receiver", "dongle", "interface", "card", "smartcard", "technology", "corp",
    "inc", "ltd", "co", "corporation", "international", "electronics", "gaming", "audio", "storage",
    "drive", "flash", "disk", "mass", "bluetooth", "hci", "mode", "microelectronics", "systems", "the", "micro", "radio", "silicon", "cambridge", "generic", "emv", "smart", "digital", "tech", "group", "limited",
    "semiconductor", "semiconductors", "industrial", "computer", "computers", "products", "optical",
}
