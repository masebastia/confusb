# SPDX-License-Identifier: GPL-3.0-or-later
"""confusb: avisa al conectar un dispositivo USB, muestra su información y busca su controlador y
las aplicaciones para usarlo."""
import os

# CONFUSB_APP_ID permite probar una copia sin que choque con la instalada (lo heredan los procesos que lanza).
APP_ID = os.environ.get("CONFUSB_APP_ID") or "es.masebastia.confusb"
__version__ = "0.2.2"
