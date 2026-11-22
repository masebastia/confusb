# SPDX-License-Identifier: GPL-3.0-or-later
"""Capacidad y particiones de las unidades de almacenamiento USB (sin tocar el sistema)."""
import json
import unittest

from confusb import almacenamiento as alm
from confusb import i18n

# Salida real de «lsblk -J -b» de un pendrive de 32 GB (FAT32, una partición, montado)
PENDRIVE = json.dumps({"blockdevices": [{
    "name": "sdd", "path": "/dev/sdd", "size": 31457280000, "type": "disk", "fstype": None, "label": None,
    "uuid": None, "mountpoints": [None], "model": "ProductCode", "vendor": "VendorC ", "ro": False, "rm": True,
    "tran": "usb", "fsavail": None, "fsused": None, "pttype": "dos",
    "children": [{
        "name": "sdd1", "path": "/dev/sdd1", "size": 31457263616, "type": "part", "fstype": "vfat",
        "label": "USB DISK", "uuid": "BEA6-BBCE", "mountpoints": ["/media/marcos/USB DISK"], "model": None,
        "vendor": None, "ro": False, "rm": True, "tran": None, "fsavail": 30405656576, "fsused": 1043922944,
        "pttype": "dos"}]}]})

LECTOR_VACIO = json.dumps({"blockdevices": [{
    "name": "sde", "path": "/dev/sde", "size": 0, "type": "disk", "model": "Card Reader", "vendor": "Generic ",
    "ro": False, "rm": True, "tran": "usb", "mountpoints": [None]}]})


class PruebasAlmacenamiento(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")

    def test_capacidad_y_particion_de_un_pendrive(self):
        (u,) = alm.analizar(PENDRIVE)
        self.assertEqual((u.ruta, u.tam, u.tabla, u.extraible), ("/dev/sdd", 31457280000, "dos", True))
        self.assertEqual(alm.capacidad([u]), 31457280000)
        (p,) = u.particiones
        self.assertEqual((p.fstype, p.etiqueta, p.libre, p.montajes), ("vfat", "USB DISK", 30405656576,
                                                                       ["/media/marcos/USB DISK"]))

    def test_los_puntos_de_montaje_nulos_de_lsblk_se_descartan(self):
        (u,) = alm.analizar(PENDRIVE)
        self.assertEqual(u.montajes, [])
        self.assertEqual(alm.puntos_de_montaje([u]), ["/media/marcos/USB DISK"])

    def test_filas_con_capacidad_primero(self):
        filas = dict(alm.filas(alm.analizar(PENDRIVE)))
        self.assertIn("31 457 280 000 B", filas["Capacity"])
        self.assertIn("GB", filas["Capacity"])
        self.assertEqual(filas["Drive model"], "VendorC ProductCode")
        particion = filas["Partition sdd1"]
        for trozo in ("vfat", "«USB DISK»", "free", "/media/marcos/USB DISK"):
            self.assertIn(trozo, particion)

    def test_la_coma_decimal_del_idioma_no_se_toca(self):
        from unittest import mock
        with mock.patch.object(alm, "formatear", return_value="31,5\u00a0GB"):
            self.assertEqual(dict(alm.filas(alm.analizar(PENDRIVE)))["Capacity"], "31,5\u00a0GB · 31 457 280 000 B")

    def test_lector_de_tarjetas_sin_tarjeta(self):
        unidades = alm.analizar(LECTOR_VACIO)
        self.assertIsNone(alm.capacidad(unidades))
        self.assertEqual(dict(alm.filas(unidades))["Capacity"], "No media inserted")

    def test_particion_sin_montar(self):
        (u,) = alm.analizar(PENDRIVE)
        u.particiones[0].montajes = []
        self.assertIn("not mounted", dict(alm.filas([u]))["Partition sdd1"])

    def test_varias_unidades_se_distinguen_por_su_nombre(self):
        a, b = alm.analizar(PENDRIVE)[0], alm.analizar(LECTOR_VACIO)[0]
        etiquetas = [k for k, _v in alm.filas([a, b])]
        self.assertIn("sdd · Capacity", etiquetas)
        self.assertIn("sde · Capacity", etiquetas)

    def test_salida_ilegible_o_sin_discos(self):
        self.assertEqual(alm.analizar("esto no es json"), [])
        self.assertEqual(alm.analizar(json.dumps({"blockdevices": [{"name": "loop0", "type": "loop"}]})), [])

    def test_sin_unidades_no_hay_capacidad(self):
        self.assertIsNone(alm.capacidad([]))


class PruebasPertenencia(unittest.TestCase):
    def test_un_nodo_de_bloque_pertenece_al_dispositivo_usb_del_que_cuelga(self):
        import os
        from unittest import mock
        real = "/sys/devices/pci0000:00/usb1/1-3/1-3:1.0/host10/target10:0:0/10:0:0:0/block/sdd/sdd1"
        with mock.patch.object(os.path, "realpath", return_value=real):
            self.assertTrue(alm.pertenece("/dev/sdd1", "/sys/devices/pci0000:00/usb1/1-3"))
            # otro dispositivo cuyo nombre empieza igual (1-3 / 1-30) no cuenta
            self.assertFalse(alm.pertenece("/dev/sdd1", "/sys/devices/pci0000:00/usb1/1-30"))
            self.assertFalse(alm.pertenece("", "/sys/devices/pci0000:00/usb1/1-3"))


if __name__ == "__main__":
    unittest.main()
