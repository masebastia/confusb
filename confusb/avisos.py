# SPDX-License-Identifier: GPL-3.0-or-later
"""Avisos de «dispositivo conectado» pendientes (~/.local/share/confusb/avisos.json).

El servicio y la ventana son procesos distintos: el servicio apunta aquí lo que ha ofrecido (con su
notificación) y la ventana lo lee para mostrarlo en la tarjeta «Avisos» y lo quita cuando se atiende."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from gi.repository import GLib


@dataclass
class Aviso:
    path: str          # ruta sysfs del dispositivo
    titulo: str
    usb_id: str
    cuando: float      # instante de la conexión (segundos desde 1970)

    @property
    def notificacion(self) -> str:
        """Identificador de su notificación del sistema (para retirarla)."""
        return f"usb-{self.usb_id}"

    @property
    def hora(self) -> str:
        return GLib.DateTime.new_from_unix_local(int(self.cuando)).format("%R")


class Almacen:
    def __init__(self, ruta: str | None = None):
        self.ruta = ruta or os.path.join(GLib.get_user_data_dir(), "confusb", "avisos.json")

    def leer(self, solo_presentes: bool = True) -> list[Aviso]:
        """Los avisos pendientes, del más antiguo al más reciente. Los de dispositivos que ya no están
        conectados se descartan (la oferta caducó)."""
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            return []
        avisos = []
        for d in datos if isinstance(datos, list) else []:
            try:
                a = Aviso(str(d["path"]), str(d["titulo"]), str(d["usb_id"]), float(d["cuando"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not solo_presentes or os.path.exists(a.path):
                avisos.append(a)
        return avisos

    def _escribir(self, avisos: list[Aviso]):
        try:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            tmp = self.ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([asdict(a) for a in avisos], f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.ruta)
        except OSError:
            pass

    def podar(self):
        """Quita del fichero los avisos de dispositivos que ya no están conectados."""
        todos = self.leer(False)
        presentes = [a for a in todos if os.path.exists(a.path)]
        if len(presentes) != len(todos):
            self._escribir(presentes)

    def anadir(self, path: str, titulo: str, usb_id: str) -> Aviso:
        """Apunta un aviso; si el dispositivo ya tenía uno, lo sustituye."""
        nuevo = Aviso(path, titulo, usb_id, time.time())
        self._escribir([a for a in self.leer(False) if a.path != path] + [nuevo])
        return nuevo

    def quitar(self, path: str) -> Aviso | None:
        """Quita el aviso de un dispositivo; devuelve el quitado (None si no había)."""
        todos = self.leer(False)
        quitado = next((a for a in todos if a.path == path), None)
        if quitado:
            self._escribir([a for a in todos if a.path != path])
        return quitado

    def vaciar(self) -> list[Aviso]:
        """Quita todos; devuelve los que había."""
        todos = self.leer(False)
        if todos:
            self._escribir([])
        return todos
