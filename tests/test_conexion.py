# SPDX-License-Identifier: GPL-3.0-or-later
"""La política de conexión: cuándo aparece confusb, cuándo no y el registro de dispositivos conocidos."""
import json
import os
import tempfile
import unittest
from unittest import mock

from confusb import conexion, i18n, usbinfo
from confusb.conexion import Registro, decidir

BASE = dict(activa=True, previo=None, modo="notificar", solo_nuevos=True, abrir_almacenamiento=True,
            automount_open=False)


def dispositivo(clases=(0x03,), drivers=("usbhid",), vid="046d", pid="c31c", serie="", hub=False, sin_driver=False):
    """Un DeviceInfo mínimo: una interfaz por clase."""
    info = usbinfo.DeviceInfo(syspath="/sys/devices/x/1-3", vid=vid, pid=pid, serial=serie, product="Prueba")
    info.dev_class = 0x09 if hub else 0x00
    info.classes = set(clases)
    info.interfaces = [usbinfo.Interface(name=f"1-3:1.{n}", number=str(n), cls=c, subcls=0, proto=0, label=None,
                                         driver=None if sin_driver else drivers[0], modalias=None, modules=[],
                                         endpoints=[]) for n, c in enumerate(clases)]
    info.drivers = [] if sin_driver else list(drivers)
    return info


class PruebasDecision(unittest.TestCase):
    def decidir(self, info, **kw):
        return decidir(info, **{**BASE, **kw})

    def test_sesion_en_segundo_plano_no_hace_nada(self):
        # el caso original: otro usuario conectó una unidad y se abrió confusb en la sesión inactiva
        self.assertEqual(self.decidir(dispositivo((0x08,), ("usb-storage",)), activa=False).accion, "nada")
        self.assertEqual(self.decidir(dispositivo(), activa=False).accion, "nada")

    def test_dispositivo_nuevo_ofrece_abrir(self):
        self.assertEqual(self.decidir(dispositivo((0x0B,), sin_driver=True)).accion, "notificar")

    def test_el_ajuste_decide_como_se_ofrece(self):
        self.assertEqual(self.decidir(dispositivo(), modo="ventana").accion, "ventana")
        self.assertEqual(self.decidir(dispositivo(), modo="nada").accion, "nada")

    def test_dispositivo_conocido_y_operativo_no_aparece(self):
        previo = {"operativo": True, "veces": 3}
        self.assertEqual(self.decidir(dispositivo(), previo=previo).accion, "nada")

    def test_conocido_sin_controlador_de_siempre_no_molesta_cada_vez(self):
        # un lector que funciona desde el espacio de usuario (pcscd) nunca tiene controlador de kernel
        previo = {"operativo": False}
        self.assertEqual(self.decidir(dispositivo((0x0B,), sin_driver=True), previo=previo).accion, "nada")

    def test_conocido_que_ha_dejado_de_funcionar_avisa(self):
        previo = {"operativo": True}
        d = self.decidir(dispositivo(sin_driver=True), previo=previo)
        self.assertEqual(d.accion, "notificar")

    def test_conocido_de_la_siembra_inicial_no_avisa(self):
        self.assertEqual(self.decidir(dispositivo(sin_driver=True), previo={"operativo": None}).accion, "nada")

    def test_avisar_siempre_si_no_se_pide_solo_nuevos(self):
        self.assertEqual(self.decidir(dispositivo(), previo={"operativo": True}, solo_nuevos=False).accion,
                         "notificar")

    def test_los_hubs_no_aparecen(self):
        self.assertEqual(self.decidir(dispositivo((0x09,), ("hub",), hub=True)).accion, "nada")

    def test_unidad_de_almacenamiento_abre_la_aplicacion_predeterminada(self):
        d = self.decidir(dispositivo((0x08,), ("usb-storage",)))
        self.assertEqual(d.accion, "almacenamiento")
        # también si ya se conocía: es lo que se espera al enchufar un pendrive
        self.assertEqual(self.decidir(dispositivo((0x08,), ("usb-storage",)), previo={"operativo": True}).accion,
                         "almacenamiento")

    def test_si_gnome_ya_abre_la_unidad_confusb_no_la_abre_otra_vez(self):
        d = self.decidir(dispositivo((0x08,), ("usb-storage",)), automount_open=True)
        self.assertEqual(d.accion, "nada")

    def test_almacenamiento_desactivado_se_trata_como_cualquier_dispositivo(self):
        self.assertEqual(self.decidir(dispositivo((0x08,), ("usb-storage",)), abrir_almacenamiento=False).accion,
                         "notificar")
        self.assertEqual(self.decidir(dispositivo((0x08,), ("usb-storage",)), abrir_almacenamiento=False,
                                      previo={"operativo": True}).accion, "nada")


class PruebasOperativo(unittest.TestCase):
    def test_operativo_si_todas_las_interfaces_tienen_controlador(self):
        self.assertTrue(conexion.operativo(dispositivo((0x01, 0x03), ("snd-usb-audio",))))

    def test_no_operativo_si_alguna_interfaz_no_lo_tiene(self):
        info = dispositivo((0x01, 0x03), ("snd-usb-audio",))
        info.interfaces[1].driver = None
        self.assertFalse(conexion.operativo(info))

    def test_sin_interfaces_vale_el_controlador_del_dispositivo(self):
        info = dispositivo()
        info.interfaces = []
        self.assertTrue(conexion.operativo(info))
        info.drivers = []
        self.assertFalse(conexion.operativo(info))


class PruebasRegistro(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = os.path.join(self.tmp.name, "confusb", "dispositivos.json")

    def test_clave_con_y_sin_numero_de_serie(self):
        self.assertEqual(conexion.clave("046D", "C31C"), "046d:c31c")
        self.assertEqual(conexion.clave("346d", "5678", " ABC123 "), "346d:5678:ABC123")

    def test_primera_vez_desconocido_y_despues_conocido(self):
        r = Registro(self.ruta)
        info = dispositivo(serie="S1")
        self.assertFalse(r.existe)
        self.assertIsNone(r.buscar(info))
        r.anotar(info)
        e = r.buscar(info)
        self.assertEqual((e["veces"], e["operativo"], e["nombre"]), (1, True, "Prueba"))
        r.anotar(info)
        self.assertEqual(r.buscar(info)["veces"], 2)

    def test_el_numero_de_serie_distingue_dos_unidades_iguales(self):
        r = Registro(self.ruta)
        r.anotar(dispositivo(vid="346d", pid="5678", serie="A"))
        self.assertIsNone(r.buscar(dispositivo(vid="346d", pid="5678", serie="B")))

    def test_se_guarda_en_disco_y_sobrevive_a_un_reinicio(self):
        Registro(self.ruta).anotar(dispositivo())
        self.assertTrue(Registro(self.ruta).buscar(dispositivo()))
        with open(self.ruta, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], 1)

    def test_un_fichero_estropeado_se_ignora(self):
        os.makedirs(os.path.dirname(self.ruta))
        with open(self.ruta, "w") as f:
            f.write("{no es json")
        r = Registro(self.ruta)
        self.assertIsNone(r.buscar(dispositivo()))
        r.anotar(dispositivo())          # y se puede volver a escribir
        self.assertTrue(Registro(self.ruta).buscar(dispositivo()))

    def test_olvidar(self):
        r = Registro(self.ruta)
        r.anotar(dispositivo())
        r.olvidar()
        self.assertIsNone(Registro(self.ruta).buscar(dispositivo()))

    def test_siembra_con_lo_que_ya_esta_conectado(self):
        d = os.path.join(self.tmp.name, "1-3")
        os.makedirs(d)
        for nombre, valor in (("idVendor", "046d"), ("idProduct", "c31c"), ("product", "Teclado")):
            with open(os.path.join(d, nombre), "w") as f:
                f.write(valor + "\n")
        r = Registro(self.ruta)
        r.sembrar([d, os.path.join(self.tmp.name, "no-existe")])
        e = r.buscar(dispositivo())
        self.assertEqual(e["nombre"], "Teclado")
        self.assertIsNone(e["operativo"])
        self.assertEqual(len(r.datos), 1)


class PruebasSesion(unittest.TestCase):
    def test_sesion_inactiva(self):
        respuestas = {"show-user": "9", "show-session": "no"}
        with mock.patch.object(conexion, "_loginctl", lambda orden, *a: respuestas[orden]):
            self.assertFalse(conexion.sesion_activa())

    def test_sesion_activa(self):
        respuestas = {"show-user": "9", "show-session": "yes"}
        with mock.patch.object(conexion, "_loginctl", lambda orden, *a: respuestas[orden]):
            self.assertTrue(conexion.sesion_activa())

    def test_sin_logind_se_supone_activa(self):
        with mock.patch.object(conexion, "_loginctl", lambda *a: None), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(conexion.sesion_activa())


if __name__ == "__main__":
    i18n.activar("en")
    unittest.main()
