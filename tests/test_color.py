# SPDX-License-Identifier: GPL-3.0-or-later
"""Colores del fondo elegido por el usuario: validación, y que de cualquier color salga una paleta legible."""
import itertools
import os
import tempfile
import unittest
from unittest import mock

from gi.repository import GLib

from confusb import color, i18n, preferencias


class PruebasColor(unittest.TestCase):
    def test_hex_ida_y_vuelta(self):
        self.assertEqual(color.analizar("#0a1120"), (10, 17, 32))
        self.assertEqual(color.a_hex((10, 17, 32)), "#0a1120")
        self.assertEqual(color.a_hex((300, -5, 12.4)), "#ff000c")          # se acota a 0-255

    def test_validacion(self):
        for bueno in ("#000000", "#FFFFFF", "#0a1120"):
            self.assertTrue(color.valido(bueno), bueno)
        for malo in ("0a1120", "#0a112", "#0a11200", "#gggggg", "rojo", None, 5, ""):
            self.assertFalse(color.valido(malo), malo)

    def test_claros_y_oscuros(self):
        self.assertTrue(color.es_oscuro("#000000"))
        self.assertTrue(color.es_oscuro("#0a1120"))        # el fondo por defecto
        self.assertTrue(color.es_oscuro("#3070c0"))        # un azul medio se lee mejor con texto blanco
        self.assertFalse(color.es_oscuro("#ffffff"))
        self.assertFalse(color.es_oscuro("#f6f8fa"))
        self.assertFalse(color.es_oscuro("#ffd54f"))       # un amarillo, con texto oscuro

    def test_luminancia(self):
        self.assertAlmostEqual(color.luminancia((0, 0, 0)), 0.0)
        self.assertAlmostEqual(color.luminancia((255, 255, 255)), 1.0, places=3)

    def test_de_cualquier_fondo_el_texto_se_lee(self):
        """Barrido de 6×6×6 colores: el texto derivado debe tener contraste suficiente con el fondo, y el texto
        atenuado, que no sea ilegible."""
        pasos = (0, 51, 102, 153, 204, 255)
        peor_texto = peor_tenue = 99.0
        for r, g, b in itertools.product(pasos, repeat=3):
            fondo = color.a_hex((r, g, b))
            p = color.derivar(fondo, color.es_oscuro(fondo))
            bg = color.analizar(p["bg"])
            peor_texto = min(peor_texto, color.contraste(color.analizar(p["text"]), bg))
            peor_tenue = min(peor_tenue, color.contraste(color.analizar(p["dim"]), bg))
        self.assertGreaterEqual(peor_texto, 4.0, f"texto: {peor_texto:.2f}")
        self.assertGreaterEqual(peor_tenue, 2.8, f"texto atenuado: {peor_tenue:.2f}")

    def test_la_paleta_derivada_es_completa_y_valida(self):
        p = color.derivar("#336699", True)
        self.assertEqual(p["bg"], "#336699")
        for clave in ("bg2", "panel", "panel_hover", "border", "text", "dim"):
            self.assertTrue(color.valido(p[clave]), clave)
        for clave in ("card", "card_hover", "glass"):
            self.assertEqual(len(p[clave]), 3, clave)
            self.assertTrue(all(0 <= v <= 255 for v in p[clave]), clave)
        self.assertTrue(p["glass_input"].startswith("rgba("))

    def test_los_paneles_se_separan_del_fondo(self):
        oscuro = color.derivar("#0a1120", True)
        claro = color.derivar("#f0f0f0", False)
        self.assertGreater(color.luminancia(color.analizar(oscuro["panel"])), color.luminancia(color.analizar(oscuro["bg"])))
        self.assertLess(color.luminancia(color.analizar(claro["panel"])), color.luminancia(color.analizar(claro["bg"])))


class PruebasAjusteDeFondo(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        parche = mock.patch.object(GLib, "get_user_config_dir", return_value=self.tmp.name)
        parche.start()
        self.addCleanup(parche.stop)
        self.addCleanup(i18n.activar, "en")

    def test_por_defecto_la_imagen(self):
        p = preferencias.Preferencias()
        self.assertEqual((p.fondo, p.color_fondo), ("imagen", "#0a1120"))

    def test_se_guarda_y_se_recupera(self):
        p = preferencias.Preferencias()
        p.cambiar(fondo="color", color_fondo="#336699")
        otra = preferencias.Preferencias()
        self.assertEqual((otra.fondo, otra.color_fondo), ("color", "#336699"))

    def test_valores_no_validos_se_ignoran(self):
        os.makedirs(os.path.join(self.tmp.name, "confusb"))
        with open(os.path.join(self.tmp.name, "confusb", "ajustes.json"), "w") as f:
            f.write('{"fondo": "degradado", "color_fondo": "azul", "esquema": 2}')
        p = preferencias.Preferencias()
        self.assertEqual((p.fondo, p.color_fondo), ("imagen", "#0a1120"))

    def test_el_color_se_guarda_en_minusculas(self):
        os.makedirs(os.path.join(self.tmp.name, "confusb"))
        with open(os.path.join(self.tmp.name, "confusb", "ajustes.json"), "w") as f:
            f.write('{"fondo": "color", "color_fondo": "#AABBCC", "esquema": 2}')
        self.assertEqual(preferencias.Preferencias().color_fondo, "#aabbcc")

    def test_restablecer_vuelve_a_la_imagen(self):
        p = preferencias.Preferencias()
        p.cambiar(fondo="color", color_fondo="#ffffff")
        p.restablecer()
        self.assertEqual((p.fondo, p.color_fondo), ("imagen", "#0a1120"))


if __name__ == "__main__":
    unittest.main()
