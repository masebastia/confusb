# SPDX-License-Identifier: GPL-3.0-or-later
"""Las traducciones: cada .po es válido, conserva los {marcadores} y se carga igual que con msgfmt."""
import glob
import os
import re
import unittest

from confusb import i18n

PO_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "po")
POS = sorted(glob.glob(os.path.join(PO_DIR, "*.po")))


def marcadores(texto):
    return sorted(re.findall(r"\{[a-z_]*(?::[^}]*)?\}", texto))


@unittest.skipUnless(POS, "no hay carpeta po/ (p. ej. pruebas sobre el paquete instalado)")
class PruebasPo(unittest.TestCase):
    def test_hay_un_po_por_idioma(self):
        codigos = {os.path.basename(p)[:-3] for p in POS}
        self.assertEqual(codigos, set(i18n.IDIOMAS) - {i18n.FUENTE})

    def test_marcadores_conservados(self):
        for po in POS:
            for msgid, msgstr in i18n.leer_po(po).items():
                with self.subTest(po=os.path.basename(po), msgid=msgid[:40]):
                    self.assertEqual(marcadores(msgid), marcadores(msgstr))

    def test_los_textos_principales_estan_traducidos(self):
        for po in POS:
            tabla = i18n.leer_po(po)
            for texto in ("Close", "Refresh", "Language", "Drivers and applications"):
                with self.subTest(po=os.path.basename(po), texto=texto):
                    self.assertIn(texto, tabla)


class PruebasIdiomas(unittest.TestCase):
    def test_banderas_y_abreviaturas(self):
        for codigo, (bandera, nombre) in i18n.IDIOMAS.items():
            self.assertTrue(bandera and nombre, codigo)
            self.assertEqual(i18n.etiqueta(codigo), f"{bandera} {codigo.upper()}")
        self.assertEqual(i18n.etiqueta("es"), "\U0001F1EA\U0001F1F8 ES")

    def test_sin_traduccion_devuelve_el_texto_fuente(self):
        i18n.activar("en")
        self.assertEqual(i18n._("Close"), "Close")
        self.assertEqual(i18n._("Texto que no existe"), "Texto que no existe")

    def test_idioma_desconocido_cae_en_ingles(self):
        self.assertEqual(i18n.activar("xx"), i18n.FUENTE)

    def test_mayusculas_en_turco(self):
        i18n.activar("tr")
        try:
            self.assertEqual(i18n.mayusculas("izin"), "İZİN")
        finally:
            i18n.activar("en")


@unittest.skipUnless(POS, "no hay carpeta po/")
class PruebasLector(unittest.TestCase):
    def test_lee_el_po_y_traduce(self):
        tabla = i18n.leer_po(os.path.join(PO_DIR, "es.po"))
        self.assertEqual(tabla["Close"], "Cerrar")
        self.assertEqual(tabla["Version {version}"], "Versión {version}")
        self.assertNotIn("", tabla)


if __name__ == "__main__":
    unittest.main()
