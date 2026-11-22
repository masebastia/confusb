# SPDX-License-Identifier: GPL-3.0-or-later
"""El reparto en dos procesos: el servicio (ligero, sin GTK) y la ventana (se va de la memoria al cerrarla);
y las preferencias que comparten."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gi.repository import GLib

from confusb import i18n, preferencias

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PruebasServicioLigero(unittest.TestCase):
    def python(self, codigo: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": RAIZ})

    def test_el_servicio_no_carga_gtk_ni_libadwaita(self):
        r = self.python("import sys, confusb.servicio, confusb.cli\n"
                        "mal = sorted(m for m in sys.modules if m.startswith('gi.repository.') and "
                        "m.split('.')[-1] in ('Gtk', 'Adw', 'Gdk', 'Gsk', 'Graphene', 'Pango'))\n"
                        "print(mal)")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_la_linea_de_ordenes_sin_ventana_tampoco_carga_gtk(self):
        r = self.python("import sys\nfrom confusb import cli\n"
                        "cli.main(['confusb', '--version'])\n"
                        "print('Gtk' in ' '.join(sys.modules))")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("confusb ", r.stdout)
        self.assertTrue(r.stdout.strip().endswith("False"))

    def test_el_comando_sin_argumentos_es_el_servicio_y_con_opciones_la_ventana(self):
        from confusb import cli
        with mock.patch("confusb.servicio.ServicioApp") as srv, mock.patch("confusb.app.ConfusbApp") as win:
            srv.return_value.run.return_value = 0
            win.return_value.run.return_value = 0
            cli.main(["confusb"])
            srv.return_value.run.assert_called_once()
            win.return_value.run.assert_not_called()
            srv.reset_mock()
            cli.main(["confusb", "--devices"])
            win.return_value.run.assert_called_once_with(["confusb", "--devices"])
            srv.return_value.run.assert_not_called()
            win.reset_mock()
            cli.main(["confusb", "--show", "1-3"])
            win.return_value.run.assert_called_once_with(["confusb", "--show", "1-3"])

    @unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "necesita una pantalla")
    def test_la_ventana_termina_al_cerrar_la_ultima_ventana(self):
        """Sin «hold»: cuando se cierra la ventana, run() vuelve y el proceso se va de la memoria."""
        codigo = (
            "import confusb\n"
            "from gi.repository import GLib\n"
            "from confusb import app, usbinfo\n"
            "a = app.ConfusbApp(); a.register(None)\n"
            "GLib.idle_add(lambda: a.show_devices() or False)\n"
            "GLib.timeout_add(1500, lambda: a.devices_win.close() or False)\n"
            "GLib.timeout_add(15000, lambda: print('SIGUE VIVO') or a.quit() or False)\n"
            "print('salida', a.run([]))\n")
        r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": RAIZ, "CONFUSB_APP_ID": "es.masebastia.prueba3"},
                           timeout=60)
        self.assertNotIn("SIGUE VIVO", r.stdout, r.stderr)
        self.assertIn("salida 0", r.stdout)


class PruebasPreferencias(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parche = mock.patch.object(GLib, "get_user_config_dir", return_value=self.tmp.name)
        self.parche.start()
        self.addCleanup(self.parche.stop)
        self.addCleanup(i18n.activar, "en")
        self.ruta = os.path.join(self.tmp.name, "confusb", "ajustes.json")

    def escribir(self, datos: dict):
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f)

    def test_sin_fichero_valen_los_valores_por_defecto(self):
        p = preferencias.Preferencias()
        self.assertEqual((p.al_conectar, p.solo_nuevos, p.abrir_almacenamiento), ("notificar", True, True))

    def test_el_servicio_ve_lo_que_cambia_la_ventana(self):
        servicio = preferencias.Preferencias()
        self.assertTrue(servicio.solo_nuevos)
        ventana = preferencias.Preferencias()          # otro proceso
        ventana.cambiar(solo_nuevos=False, al_conectar="ventana")
        self.assertTrue(servicio.solo_nuevos)           # hasta que vuelve a leer
        servicio.recargar()
        self.assertEqual((servicio.solo_nuevos, servicio.al_conectar), (False, "ventana"))

    def test_los_ajustes_del_esquema_antiguo_pasan_a_notificar(self):
        self.escribir({"al_conectar": "ventana", "pie": False})            # 0.2.0: sin «esquema»
        p = preferencias.Preferencias()
        self.assertEqual(p.al_conectar, "notificar")
        self.assertFalse(p.pie)                                            # lo demás se conserva

    def test_con_el_esquema_nuevo_se_respeta_la_eleccion(self):
        self.escribir({"al_conectar": "ventana", "esquema": preferencias.ESQUEMA})
        self.assertEqual(preferencias.Preferencias().al_conectar, "ventana")

    def test_valores_no_validos_se_ignoran(self):
        self.escribir({"opacidad": "mucha", "marco": "raro", "solo_nuevos": "sí", "esquema": preferencias.ESQUEMA})
        p = preferencias.Preferencias()
        self.assertEqual((p.opacidad, p.marco, p.solo_nuevos), (80, "resaltado", True))

    def test_restablecer_conserva_el_idioma(self):
        p = preferencias.Preferencias()
        p.cambiar(idioma="de", opacidad=40)
        p.restablecer()
        self.assertEqual((p.idioma, p.opacidad), ("de", 80))


if __name__ == "__main__":
    unittest.main()
