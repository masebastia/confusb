# SPDX-License-Identifier: GPL-3.0-or-later
"""El catálogo de dispositivos (kb) y la lógica que decide qué se ofrece (resolver), sin tocar el sistema."""
import unittest
from unittest import mock

from confusb import i18n, kb, resolver, usbinfo


class PruebasCatalogo(unittest.TestCase):
    def test_todas_las_entradas_tienen_titulo_y_descripcion(self):
        entradas = [e for lista in (*kb.CLASS_KB.values(), *kb.VENDOR_KB.values()) for e in lista]
        self.assertGreater(len(entradas), 20)
        for e in entradas:
            with self.subTest(titulo=e["title"]):
                self.assertTrue(e["title"] and (e.get("desc") or e.get("externa")))

    def test_marcadores_de_desc_args(self):
        for lista in kb.VENDOR_KB.values():
            for e in lista:
                if "desc_args" in e:
                    self.assertEqual(e["desc"].format(**e["desc_args"]).count("{"), 0)


class PruebasResolver(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")

    def test_todo_instalado(self):
        entrada = kb.CLASS_KB[0x0B][0]            # pcscd + libccid
        item = resolver.make_item_from_kb(entrada, {"pcscd": "installed", "libccid": "installed"})
        self.assertEqual(item.status, "Installed")
        self.assertFalse([a for a in item.actions if a.kind == "apt"])

    def test_falta_un_paquete_ofrece_solo_ese(self):
        entrada = kb.CLASS_KB[0x0B][1]            # opensc + opensc-pkcs11
        item = resolver.make_item_from_kb(entrada, {"opensc": "installed", "opensc-pkcs11": "available"})
        self.assertEqual(item.status, "Needs installing")
        apt = [a for a in item.actions if a.kind == "apt"]
        self.assertEqual(apt[0].payload, ["opensc-pkcs11"])
        self.assertIn("Already installed: opensc", item.desc)

    def test_aplicacion_externa_instalada_y_no_instalada(self):
        entrada = next(e for e in kb.CLASS_KB[0x0B] if e.get("externa"))
        with mock.patch.object(resolver.shutil, "which", return_value="/usr/bin/autofirma"):
            ok = resolver.make_item_from_kb(entrada, {"autofirma": "installed"})
        self.assertEqual(ok.status, "Installed")
        with mock.patch.object(resolver.shutil, "which", return_value=None):
            falta = resolver.make_item_from_kb(entrada, {"autofirma": "missing"})
        self.assertEqual(falta.status, "Needs installing")
        self.assertEqual(falta.actions[0].kind, "url")

    def test_flatpak_ya_instalado_no_se_ofrece(self):
        entrada = kb.VENDOR_KB["2341"][0]
        item = resolver.make_item_from_kb(entrada, {"arduino-cli": "installed"}, {"cc.arduino.IDE2"})
        self.assertFalse([a for a in item.actions if a.kind == "flatpak"])

    def test_palabras(self):
        self.assertTrue(resolver.word_match("au9540", "AU9540 Smartcard Reader"))
        self.assertFalse(resolver.word_match("micro", "microlens"))
        self.assertEqual(resolver.tokens("AU9540 Smartcard Reader", "Alcor Micro Corp."), ["au9540", "alcor"])


class PruebasUsbinfo(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")

    def test_nombres_de_clase(self):
        self.assertEqual(usbinfo.class_name(0x0B), "0x0b · Smart card (CCID)")
        self.assertEqual(usbinfo.class_name(0x77), "0x77 · Unknown")
        self.assertEqual(usbinfo.class_name(None), "?")

    def test_hexint_y_read(self):
        self.assertEqual(usbinfo.hexint("046d"), 0x046D)
        self.assertIsNone(usbinfo.hexint("zz"))
        self.assertIsNone(usbinfo.read("/ruta/que/no/existe"))


if __name__ == "__main__":
    unittest.main()
