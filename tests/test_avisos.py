# SPDX-License-Identifier: GPL-3.0-or-later
"""Los avisos de «dispositivo conectado»: además de la notificación del sistema quedan en la aplicación, y se
retiran las notificaciones (el contador del icono) cuando se ven o se atienden."""
import unittest
from unittest import mock

import confusb
from confusb import i18n, usbinfo

confusb.APP_ID = "es.masebastia.prueba"
from confusb import app as appmod  # noqa: E402


def dispositivo(vid="046d", pid="c31c", titulo="Teclado"):
    return usbinfo.DeviceInfo(syspath=f"/sys/devices/x/{vid}", vid=vid, pid=pid, product=titulo)


class PruebasAvisos(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        self.app = appmod.ConfusbApp()
        self.enviadas, self.retiradas, self.abiertas = [], [], []
        self.app.send_notification = lambda id_, n: self.enviadas.append(id_)
        self.app.withdraw_notification = lambda id_: self.retiradas.append(id_)
        self.app.open_device = lambda path: self.abiertas.append(path)

    def test_al_ofrecer_queda_el_aviso_en_la_aplicacion_y_se_envia_la_notificacion(self):
        info = dispositivo()
        self.app.notificar(info, info.syspath)
        self.assertEqual(list(self.app.avisos), [info.syspath])
        a = self.app.avisos[info.syspath]
        self.assertEqual((a.titulo, a.usb_id), ("Teclado", "046d:c31c"))
        self.assertEqual(self.enviadas, ["usb-046d:c31c"])

    def test_al_abrir_la_ventana_principal_se_retiran_las_notificaciones_pero_no_los_avisos(self):
        for vid in ("046d", "093a"):
            i = dispositivo(vid=vid)
            self.app.notificar(i, i.syspath)
        self.app.marcar_leidos()
        self.assertEqual(sorted(self.retiradas), ["usb-046d:c31c", "usb-093a:c31c"])
        self.assertEqual(len(self.app.avisos), 2)

    def test_descartar_un_aviso_retira_su_notificacion(self):
        i = dispositivo()
        self.app.notificar(i, i.syspath)
        self.app.descartar_aviso(i.syspath)
        self.assertEqual(self.app.avisos, {})
        self.assertEqual(self.retiradas, ["usb-046d:c31c"])

    def test_descartar_todos(self):
        for vid in ("046d", "093a"):
            i = dispositivo(vid=vid)
            self.app.notificar(i, i.syspath)
        self.app.descartar_avisos()
        self.assertEqual(self.app.avisos, {})
        self.assertEqual(len(self.retiradas), 2)

    def test_aceptar_la_oferta_abre_el_dispositivo_y_atiende_el_aviso(self):
        i = dispositivo()
        self.app.notificar(i, i.syspath)
        self.app.al_detalle(i.syspath)
        self.assertEqual(self.abiertas, [i.syspath])
        self.assertEqual(self.app.avisos, {})

    def test_descartar_uno_que_no_existe_no_falla(self):
        self.app.descartar_aviso("/sys/devices/no-existe")
        self.assertEqual(self.retiradas, [])

    def test_con_la_ventana_principal_delante_no_se_envia_notificacion(self):
        self.app.devices_win = mock.Mock()
        self.app.devices_win.is_active.return_value = True
        i = dispositivo()
        self.app.notificar(i, i.syspath)
        self.assertEqual(self.enviadas, [])
        self.assertIn(i.syspath, self.app.avisos)
        self.app.devices_win.pintar_avisos.assert_called()


if __name__ == "__main__":
    unittest.main()
