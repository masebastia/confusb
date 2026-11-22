# SPDX-License-Identifier: GPL-3.0-or-later
"""Los avisos de «dispositivo conectado»: el servicio los apunta (y envía la notificación), la ventana los
muestra, los descarta y retira las notificaciones (el contador del icono) cuando se ven o se atienden."""
import json
import os
import tempfile
import unittest
from unittest import mock

import confusb
from confusb import avisos, i18n, usbinfo

confusb.APP_ID = "es.masebastia.prueba"
from gi.repository import GLib  # noqa: E402

from confusb import app as appmod  # noqa: E402
from confusb import servicio  # noqa: E402


def dispositivo(vid="046d", pid="c31c", titulo="Teclado", presente=True, carpeta=None):
    ruta = os.path.join(carpeta or "/sys/devices/x", vid)
    if presente and carpeta:
        os.makedirs(ruta, exist_ok=True)
    return usbinfo.DeviceInfo(syspath=ruta, vid=vid, pid=pid, product=titulo)


class Base(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.almacen = avisos.Almacen(os.path.join(self.tmp.name, "datos", "avisos.json"))

    def dispositivo(self, vid="046d", pid="c31c", titulo="Teclado"):
        return dispositivo(vid, pid, titulo, carpeta=os.path.join(self.tmp.name, "sys"))


class PruebasAlmacen(Base):
    def test_anadir_y_leer(self):
        d = self.dispositivo()
        a = self.almacen.anadir(d.syspath, d.title, d.usb_id)
        self.assertEqual(self.almacen.leer(), [a])
        self.assertEqual(a.notificacion, "usb-046d:c31c")
        self.assertRegex(a.hora, r"^\d\d:\d\d$")

    def test_un_dispositivo_solo_tiene_un_aviso(self):
        d = self.dispositivo()
        self.almacen.anadir(d.syspath, "Antiguo", d.usb_id)
        self.almacen.anadir(d.syspath, "Nuevo", d.usb_id)
        self.assertEqual([a.titulo for a in self.almacen.leer()], ["Nuevo"])

    def test_quitar_y_vaciar(self):
        a, b = self.dispositivo(), self.dispositivo("093a", "2533", "Ratón")
        self.almacen.anadir(a.syspath, a.title, a.usb_id)
        self.almacen.anadir(b.syspath, b.title, b.usb_id)
        self.assertEqual(self.almacen.quitar(a.syspath).titulo, "Teclado")
        self.assertIsNone(self.almacen.quitar(a.syspath))
        self.assertEqual([x.titulo for x in self.almacen.vaciar()], ["Ratón"])
        self.assertEqual(self.almacen.leer(), [])

    def test_los_dispositivos_que_ya_no_estan_caducan(self):
        self.almacen.anadir("/sys/devices/no-existe/1-3", "Fantasma", "dead:beef")
        self.assertEqual(self.almacen.leer(), [])
        self.assertEqual(len(self.almacen.leer(solo_presentes=False)), 1)
        self.almacen.podar()
        self.assertEqual(self.almacen.leer(solo_presentes=False), [])

    def test_fichero_estropeado_o_con_entradas_incompletas(self):
        os.makedirs(os.path.dirname(self.almacen.ruta))
        with open(self.almacen.ruta, "w") as f:
            f.write("{no es json")
        self.assertEqual(self.almacen.leer(), [])
        d = self.dispositivo()
        with open(self.almacen.ruta, "w") as f:
            json.dump([{"path": d.syspath}, 3, {"path": d.syspath, "titulo": "Ok", "usb_id": "a:b", "cuando": 1}], f)
        self.assertEqual([a.titulo for a in self.almacen.leer()], ["Ok"])

    def test_dos_procesos_ven_lo_mismo(self):
        d = self.dispositivo()
        self.almacen.anadir(d.syspath, d.title, d.usb_id)
        otro = avisos.Almacen(self.almacen.ruta)     # la ventana lee lo que escribió el servicio
        self.assertEqual(len(otro.leer()), 1)
        otro.quitar(d.syspath)
        self.assertEqual(self.almacen.leer(), [])


class FalsasPreferencias:
    al_conectar, solo_nuevos, abrir_almacenamiento = "notificar", True, True

    def recargar(self):
        pass


class PruebasServicio(Base):
    def setUp(self):
        super().setUp()
        self.registro = mock.Mock()
        self.srv = servicio.ServicioApp(FalsasPreferencias(), self.registro, self.almacen)
        self.enviadas, self.retiradas, self.ventanas = [], [], []
        self.srv.send_notification = lambda id_, n: self.enviadas.append((id_, n))
        self.srv.withdraw_notification = lambda id_: self.retiradas.append(id_)
        self.srv.abrir_ventana = lambda *args: self.ventanas.append(args)

    def test_el_servicio_tiene_su_propio_identificador(self):
        self.assertEqual(self.srv.get_application_id(), "es.masebastia.prueba.servicio")
        self.assertEqual(servicio.RUTA_OBJETO, "/es/masebastia/prueba/servicio")

    def test_ofrecer_envia_la_notificacion_y_apunta_el_aviso(self):
        d = self.dispositivo()
        self.srv.notificar(d, d.syspath)
        self.assertEqual([i for i, _n in self.enviadas], ["usb-046d:c31c"])
        self.assertEqual([a.path for a in self.almacen.leer()], [d.syspath])

    def test_la_notificacion_tiene_boton_y_accion_por_defecto(self):
        d = self.dispositivo()
        self.srv.notificar(d, d.syspath)
        n = self.enviadas[0][1]
        self.assertEqual(n.get_title() if hasattr(n, "get_title") else "USB device connected", "USB device connected")

    def test_desconectar_retira_aviso_y_notificacion(self):
        d = self.dispositivo()
        self.srv.notificar(d, d.syspath)
        self.srv.desconectado(d.syspath)
        self.assertEqual(self.almacen.leer(), [])
        self.assertEqual(self.retiradas, ["usb-046d:c31c"])

    def test_desconectar_un_dispositivo_sin_aviso_no_hace_nada(self):
        self.srv.desconectado("/sys/devices/otro/1-4")
        self.assertEqual(self.retiradas, [])

    def test_aceptar_la_notificacion_abre_la_ventana_con_ese_dispositivo_y_atiende_el_aviso(self):
        d = self.dispositivo()
        self.srv.notificar(d, d.syspath)
        self.srv._al_detalle(None, GLib.Variant.new_string(d.syspath))
        self.assertEqual(self.ventanas, [("--show", d.syspath)])
        self.assertEqual(self.almacen.leer(), [])
        self.assertEqual(self.retiradas, ["usb-046d:c31c"])

    def test_la_ventana_pide_retirar_notificaciones(self):
        self.srv._al_retirar(None, GLib.Variant("as", ["usb-1:1", "usb-2:2"]))
        self.assertEqual(self.retiradas, ["usb-1:1", "usb-2:2"])

    def test_probar_ofrece_el_primer_dispositivo_que_no_sea_un_hub(self):
        hub, teclado = self.dispositivo("1d6b", "0002", "Hub"), self.dispositivo()
        hub.dev_class = 0x09
        infos = {hub.syspath: hub, teclado.syspath: teclado}
        with mock.patch.object(usbinfo, "list_usb_devices", return_value=list(infos)), \
                mock.patch.object(usbinfo, "collect", side_effect=lambda ruta, **kw: infos[ruta]):
            self.srv._al_probar(None, None)
        self.assertEqual([i for i, _n in self.enviadas], ["usb-046d:c31c"])
        self.assertEqual([a.path for a in self.almacen.leer()], [teclado.syspath])

    def test_si_el_servicio_no_esta_en_marcha_llamar_devuelve_falso(self):
        self.assertFalse(servicio.llamar("retirar", GLib.Variant("as", ["usb-1:1"])))


class PruebasArranqueDelServicio(unittest.TestCase):
    """La ventana arranca el servicio si está activado pero parado (justo tras instalar el paquete)."""

    def setUp(self):
        entorno = mock.patch.dict(os.environ)
        entorno.start()
        self.addCleanup(entorno.stop)
        os.environ.pop("CONFUSB_APP_ID", None)
        self.ordenes = []

    def systemctl(self, estado, falla_arranque=False):
        def falsa(orden, **kw):
            self.ordenes.append(orden[2])
            if orden[2] == "is-enabled":
                return mock.Mock(stdout=estado + "\n", returncode=0 if estado == "enabled" else 1)
            if falla_arranque:
                raise servicio.subprocess.CalledProcessError(1, orden)
            return mock.Mock(returncode=0)
        return mock.patch.object(servicio.subprocess, "run", falsa)

    def test_activado_y_parado_lo_arranca(self):
        with mock.patch.object(servicio, "esta_en_marcha", return_value=False), self.systemctl("enabled"):
            self.assertTrue(servicio.arrancar_si_hace_falta())
        self.assertEqual(self.ordenes, ["is-enabled", "start"])

    def test_si_ya_esta_en_marcha_no_hace_nada(self):
        with mock.patch.object(servicio, "esta_en_marcha", return_value=True), self.systemctl("enabled"):
            self.assertFalse(servicio.arrancar_si_hace_falta())
        self.assertEqual(self.ordenes, [])

    def test_desactivado_o_sin_unidad_no_se_toca(self):
        for estado in ("disabled", "masked", "not-found"):
            self.ordenes.clear()
            with self.subTest(estado=estado), mock.patch.object(servicio, "esta_en_marcha", return_value=False), \
                    self.systemctl(estado):
                self.assertFalse(servicio.arrancar_si_hace_falta())
            self.assertEqual(self.ordenes, ["is-enabled"])

    def test_sin_systemd_o_si_falla_el_arranque_no_rompe(self):
        with mock.patch.object(servicio, "esta_en_marcha", return_value=False), \
                mock.patch.object(servicio.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(servicio.arrancar_si_hace_falta())
        with mock.patch.object(servicio, "esta_en_marcha", return_value=False), \
                self.systemctl("enabled", falla_arranque=True):
            self.assertFalse(servicio.arrancar_si_hace_falta())

    def test_una_copia_de_pruebas_no_toca_el_servicio_instalado(self):
        os.environ["CONFUSB_APP_ID"] = "es.masebastia.prueba"
        with mock.patch.object(servicio, "esta_en_marcha", return_value=False), self.systemctl("enabled"):
            self.assertFalse(servicio.arrancar_si_hace_falta())
        self.assertEqual(self.ordenes, [])


class PruebasVentana(Base):
    """La ventana (otro proceso): lee el fichero del servicio y le pide retirar las notificaciones."""

    def setUp(self):
        super().setUp()
        self.app = appmod.ConfusbApp()
        self.app.almacen = self.almacen
        self.pedidos, self.abiertas = [], []
        self.parche = mock.patch.object(appmod.servicio, "llamar",
                                        lambda accion, *args: self.pedidos.append((accion, args[0].get_strv())) or True)
        self.parche.start()
        self.addCleanup(self.parche.stop)
        self.app.open_device = lambda path: self.abiertas.append(path)

    def dos_avisos(self):
        for vid in ("046d", "093a"):
            d = self.dispositivo(vid=vid)
            self.almacen.anadir(d.syspath, d.title, d.usb_id)

    def test_lista_los_avisos_del_servicio(self):
        self.dos_avisos()
        self.assertEqual(len(self.app.lista_avisos()), 2)

    def test_marcar_leidos_retira_las_notificaciones_pero_no_los_avisos(self):
        self.dos_avisos()
        self.app.marcar_leidos()
        self.assertEqual(self.pedidos, [("retirar", ["usb-046d:c31c", "usb-093a:c31c"])])
        self.assertEqual(len(self.almacen.leer()), 2)

    def test_marcar_leidos_sin_avisos_no_molesta_al_servicio(self):
        self.app.marcar_leidos()
        self.assertEqual(self.pedidos, [])

    def test_descartar_un_aviso(self):
        self.dos_avisos()
        d = self.dispositivo()
        self.app.descartar_aviso(d.syspath)
        self.assertEqual([a.usb_id for a in self.almacen.leer()], ["093a:c31c"])
        self.assertEqual(self.pedidos, [("retirar", ["usb-046d:c31c"])])

    def test_descartar_todos(self):
        self.dos_avisos()
        self.app.descartar_avisos()
        self.assertEqual(self.almacen.leer(), [])
        self.assertEqual(len(self.pedidos[0][1]), 2)

    def test_aceptar_la_oferta_desde_la_tarjeta_abre_el_dispositivo_y_la_atiende(self):
        self.dos_avisos()
        d = self.dispositivo()
        self.app.al_detalle(d.syspath)
        self.assertEqual(self.abiertas, [d.syspath])
        self.assertEqual(len(self.almacen.leer()), 1)

    def test_descartar_uno_que_no_existe_no_falla(self):
        self.app.descartar_aviso("/sys/devices/no-existe")
        self.assertEqual(self.pedidos, [])

    def test_al_abrirse_retira_las_notificaciones_que_dejo_la_version_anterior(self):
        retiradas = []
        self.app.withdraw_notification = retiradas.append
        d = self.dispositivo("346d", "5678", "Disk 20")
        for nombre, valor in (("idVendor", "346D"), ("idProduct", "5678")):
            with open(os.path.join(d.syspath, nombre), "w") as f:
                f.write(valor + "\n")
        with mock.patch.object(usbinfo, "list_usb_devices", return_value=[d.syspath, "/sys/devices/sin-id"]):
            self.app.retirar_de_la_version_anterior()
        self.assertEqual(retiradas, ["usb-346d:5678"])


if __name__ == "__main__":
    unittest.main()
