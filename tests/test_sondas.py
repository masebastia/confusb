# SPDX-License-Identifier: GPL-3.0-or-later
"""Las sondas (más información de un dispositivo): interpretación de lo que devuelve un teléfono Android por ADB
—con datos reales de uno—, los consejos cuando no se puede, y que ADB no se deje en marcha."""
import os
import tempfile
import unittest
from unittest import mock

from confusb import i18n, sondas, usbinfo

# Lo que devuelve «adb devices -l» (con el ruido de cuando arranca el servidor)
ADB_DEVICES = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
e570d96e               device usb:3-1 product:CPH1941EEA model:CPH1941 device:OP4B80L1 transport_id:1
"""

# Lo que devuelve SCRIPT_ADB en un OPPO A9 2020 (recortado a lo que se lee)
SALIDA_ADB = """@@props
[gsm.version.baseband]: [Q_V1_P14,Q_V1_P14]
[ro.board.platform]: [trinket]
[ro.boot.flash.locked]: [1]
[ro.build.display.id]: [CPH1941_11_F.91]
[ro.build.version.release]: [11]
[ro.build.version.sdk]: [30]
[ro.build.version.security_patch]: [2021-08-05]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.product.manufacturer]: [OPPO]
[ro.product.model]: [CPH1941]
[ro.vendor.oplus.market.name]: [OPPO A9 2020]
@@bateria
Current OPPO Battery Service state:
  Charger voltage : 4858
  PlugType: 2
Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 500000
  status: 2
  health: 2
  present: true
  level: 96
  scale: 100
  voltage: 4389
  temperature: 272
  technology: Li-ion
@@mem
MemTotal:        3711056 kB
MemAvailable:    1330396 kB
@@cpu
8
Hardware	: Qualcomm Technologies, Inc SDM665
@@pantalla
Physical size: 720x1600
Physical density: 320
@@disco
Filesystem       1K-blocks    Used Available Use% Mounted on
/dev/block/sda10 111018304 8952632 101918216   9% /data/user/0
"""


def formato_simple(patron, valor):
    return patron % valor        # sin la configuración regional del sistema: «4.39», no «4,39»


def telefono(adb=True, mtp=True, syspath="/sys/devices/pci/usb3/3-1", serie="e570d96e") -> usbinfo.DeviceInfo:
    info = usbinfo.DeviceInfo(syspath=syspath, vid="22d9", pid="2765", serial=serie, product="Oppo N1")
    info.interfaces = []
    if mtp:
        info.interfaces.append(usbinfo.Interface("3-1:1.0", "0", 0xFF, 0xFF, 0, "MTP", None, None, [], []))
    if adb:
        info.interfaces.append(usbinfo.Interface("3-1:1.1", "1", 0xFF, 0x42, 1, "ADB Interface", "usbfs", None, [], []))
    return info


class Base(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        parche = mock.patch.object(sondas.locale, "format_string", formato_simple)
        parche.start()
        self.addCleanup(parche.stop)


class PruebasInterpretacion(Base):
    def test_adb_devices_ignora_el_ruido_y_lee_el_puerto(self):
        (d,) = sondas.parsear_adb_devices(ADB_DEVICES)
        self.assertEqual((d["serie"], d["estado"], d["usb"], d["modelo"]), ("e570d96e", "device", "3-1", "CPH1941"))

    def test_adb_devices_estados(self):
        salida = ("List of devices attached\n"
                  "AAA   unauthorized usb:1-2 transport_id:3\n"
                  "BBB   offline usb:1-3 transport_id:4\n"
                  "CCC   no permissions (user in plugdev group; are your udev rules wrong?); usb:1-4\n")
        self.assertEqual([d["estado"] for d in sondas.parsear_adb_devices(salida)], ["unauthorized", "offline", "permiso"])

    def test_se_encuentra_el_dispositivo_por_puerto_y_si_no_por_serie(self):
        ds = [{"serie": "AAA", "estado": "device", "usb": "1-2", "modelo": ""},
              {"serie": "BBB", "estado": "device", "usb": "", "modelo": ""}]
        self.assertEqual(sondas.buscar_adb(ds, "1-2", "")["serie"], "AAA")
        self.assertEqual(sondas.buscar_adb(ds, "9-9", "BBB")["serie"], "BBB")
        self.assertIsNone(sondas.buscar_adb(ds, "9-9", "ZZZ"))

    def test_un_telefono_real(self):
        res = sondas.datos_android(sondas.partir_bloques(SALIDA_ADB))
        self.assertEqual(res.resumen, "OPPO A9 2020 · Android 11")
        titulos = [t for t, _f in res.secciones]
        self.assertEqual(titulos, ["Android phone", "Battery", "Phone storage"])
        tel = dict(res.secciones[0][1])
        self.assertEqual(tel["Commercial name"], "OPPO A9 2020")
        self.assertEqual(tel["Model"], "CPH1941")
        self.assertEqual(tel["Android version"], "11 (API 30)")
        self.assertEqual(tel["Security patch"], "2021-08-05")
        self.assertEqual(tel["Platform"], "Qualcomm Technologies, Inc SDM665 (trinket)")
        self.assertEqual(tel["CPU architecture"], "arm64-v8a · 8 cores")
        self.assertEqual(tel["Screen"], "720×1600 px · 320 dpi")
        self.assertEqual(tel["Baseband"], "Q_V1_P14")
        self.assertEqual(tel["Bootloader"], "locked")
        self.assertIn("GB", tel["RAM"])

    def test_bateria(self):
        bateria = dict(sondas.datos_android(sondas.partir_bloques(SALIDA_ADB)).secciones[1][1])
        self.assertEqual(bateria, {"Level": "96 %", "Status": "Charging", "Health": "Good", "Temperature": "27.2 °C",
                                   "Voltage": "4.39 V", "Technology": "Li-ion", "Power source": "USB"})

    def test_almacenamiento_interno(self):
        (_t, filas), = [s for s in sondas.datos_android(sondas.partir_bloques(SALIDA_ADB)).secciones
                        if s[0] == "Phone storage"]
        valor = dict(filas)["Internal storage"]
        self.assertTrue(valor.startswith("113.7") or valor.startswith("113,7"), valor)
        self.assertIn("used", valor)
        self.assertIn("free", valor)

    def test_sin_nombre_comercial_se_usa_fabricante_y_modelo(self):
        salida = SALIDA_ADB.replace("[ro.vendor.oplus.market.name]: [OPPO A9 2020]\n", "")
        self.assertEqual(sondas.datos_android(sondas.partir_bloques(salida)).resumen, "OPPO CPH1941 · Android 11")

    def test_lo_que_falta_simplemente_no_aparece(self):
        res = sondas.datos_android(sondas.partir_bloques("@@props\n[ro.product.model]: [X1]\n"))
        self.assertEqual([t for t, _f in res.secciones], ["Android phone"])      # sin batería ni almacenamiento
        self.assertEqual(dict(res.secciones[0][1]), {"Model": "X1"})
        self.assertEqual(sondas.datos_android({}).secciones, [])

    def test_la_pantalla_ignora_el_tamano_forzado(self):
        salida = SALIDA_ADB.replace("Physical size: 720x1600", "Physical size: 1080x2400\nOverride size: 720x1600")
        tel = dict(sondas.datos_android(sondas.partir_bloques(salida)).secciones[0][1])
        self.assertTrue(tel["Screen"].startswith("1080×2400"))

    def test_el_estado_de_la_bateria_se_traduce(self):
        i18n.activar("es")
        self.addCleanup(i18n.activar, "en")
        bateria = dict(sondas.datos_android(sondas.partir_bloques(SALIDA_ADB)).secciones[1][1])
        self.assertIn("Cargando", bateria.values())

    def test_que_aparatos_son_candidatos(self):
        self.assertTrue(sondas.tiene_adb(telefono()))
        self.assertFalse(sondas.tiene_adb(telefono(adb=False)))
        self.assertTrue(sondas.es_mtp(telefono(adb=False)))
        raton = usbinfo.DeviceInfo(syspath="/x")
        self.assertFalse(sondas.puede_tardar(raton))
        raton.props["ID_MTP_DEVICE"] = "1"
        self.assertTrue(sondas.es_mtp(raton))


class PruebasAdb(Base):
    """Con «adb» simulado: qué consejos se dan y que el servidor no se deje arrancado."""

    def ejecutar(self, devices=ADB_DEVICES, servidor_antes=False, adb="/usr/bin/adb"):
        self.ordenes = []

        def falsa(orden, **kw):
            self.ordenes.append(orden[1:])
            salida = SALIDA_ADB if "shell" in orden else (devices if "devices" in orden else "")
            return mock.Mock(stdout=salida, stderr="", returncode=0)
        res = sondas.Resultado()
        with mock.patch.object(sondas.shutil, "which", return_value=adb), \
                mock.patch.object(sondas, "servidor_adb_en_marcha", return_value=servidor_antes), \
                mock.patch.object(sondas.subprocess, "run", falsa):
            sondas.sonda_android(telefono(), res)
        return res

    def test_telefono_autorizado(self):
        res = self.ejecutar()
        self.assertEqual(res.resumen, "OPPO A9 2020 · Android 11")
        self.assertEqual(len(res.secciones), 3)
        self.assertEqual(res.consejos, [])

    def test_el_servidor_que_arranco_yo_se_para(self):
        self.ejecutar(servidor_antes=False)
        self.assertIn(["kill-server"], self.ordenes)

    def test_el_servidor_que_ya_estaba_en_marcha_no_se_toca(self):
        self.ejecutar(servidor_antes=True)
        self.assertNotIn(["kill-server"], self.ordenes)

    def test_sin_autorizar_dice_que_hay_que_aceptar_en_el_telefono(self):
        res = self.ejecutar(devices="List of devices attached\ne570d96e unauthorized usb:3-1 transport_id:2\n")
        self.assertEqual(res.secciones, [])
        self.assertIn("Allow USB debugging", res.consejos[0])

    def test_sin_adb_instalado_dice_que_lo_instale(self):
        res = sondas.Resultado()
        with mock.patch.object(sondas.shutil, "which", return_value=None):
            sondas.sonda_android(telefono(), res)
        self.assertIn("sudo apt install adb", res.consejos[0])

    def test_sin_interfaz_adb_no_hace_nada(self):
        res = sondas.Resultado()
        with mock.patch.object(sondas.shutil, "which") as which:
            sondas.sonda_android(telefono(adb=False), res)
        which.assert_not_called()
        self.assertEqual((res.secciones, res.consejos), ([], []))

    def test_el_telefono_no_aparece_en_adb(self):
        res = self.ejecutar(devices="List of devices attached\n")
        self.assertIn("unplug it", res.consejos[0])


class FalsoMontaje:
    def __init__(self, raiz):
        from gi.repository import Gio
        self._raiz = Gio.File.new_for_path(raiz)

    def get_root(self):
        return self._raiz


class PruebasMtp(Base):
    def test_almacenamientos_de_un_montaje(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "Internal shared storage"))
            os.makedirs(os.path.join(t, "SD card"))
            nombres = sorted(n for n, tam, libre in sondas.almacenamientos_mtp(FalsoMontaje(t)) if tam > 0)
        self.assertEqual(nombres, ["Internal shared storage", "SD card"])

    def test_un_montaje_que_falla_no_rompe(self):
        self.assertEqual(sondas.almacenamientos_mtp(FalsoMontaje("/no/existe/de/verdad")), [])

    def test_montado_muestra_los_almacenamientos(self):
        res = sondas.Resultado()
        volumen = mock.Mock()
        volumen.get_mount.return_value = FalsoMontaje("/")
        with mock.patch.object(sondas, "volumen_mtp", return_value=volumen), \
                mock.patch.object(sondas, "almacenamientos_mtp", return_value=[("Internal shared storage", 5 * 10**9, 10**9)]):
            sondas.sonda_mtp(telefono(adb=False), res)
        (titulo, filas), = res.secciones
        self.assertEqual(titulo, "Storage (MTP)")
        self.assertEqual(filas[0][0], "Internal shared storage")
        self.assertIn("free", filas[0][1])

    def test_sin_montar_aconseja_abrirlo_en_el_gestor_de_archivos(self):
        res = sondas.Resultado()
        volumen = mock.Mock()
        volumen.get_mount.return_value = None
        with mock.patch.object(sondas, "volumen_mtp", return_value=volumen):
            sondas.sonda_mtp(telefono(adb=False), res)
        self.assertIn("open it in the file manager", res.consejos[0])

    def test_sin_montar_pero_con_el_almacenamiento_de_adb_no_hay_consejo(self):
        res = sondas.Resultado(secciones=[("Phone storage", [("Internal storage", "1 GB")])])
        volumen = mock.Mock()
        volumen.get_mount.return_value = None
        with mock.patch.object(sondas, "volumen_mtp", return_value=volumen):
            sondas.sonda_mtp(telefono(), res)
        self.assertEqual(res.consejos, [])


class PruebasConjunto(Base):
    def test_completar_deja_los_resultados_en_el_dispositivo(self):
        info = telefono()
        with mock.patch.object(sondas, "SONDAS", (lambda i, r: (setattr(r, "resumen", "X"),
                                                                 r.consejos.append("c"), r.crudos.append(("t", "texto"))),)):
            sondas.completar(info)
        self.assertEqual((info.resumen, info.consejos, info.crudos), ("X", ["c"], [("t", "texto")]))

    def test_una_sonda_que_falla_no_impide_las_demas(self):
        def mala(info, res):
            raise RuntimeError("boom")
        info = telefono()
        with mock.patch.object(sondas, "SONDAS", (mala, lambda i, r: r.consejos.append("sigue"))):
            sondas.completar(info)
        self.assertEqual(info.consejos, ["sigue"])

    def test_se_puede_repetir_sin_acumular(self):
        info = telefono()
        with mock.patch.object(sondas, "SONDAS", (lambda i, r: r.consejos.append("c"),)):
            sondas.completar(info)
            sondas.completar(info)
        self.assertEqual(info.consejos, ["c"])

    def test_el_volcado_en_texto_incluye_lo_que_aportan_las_sondas(self):
        info = telefono()
        info.extra = [("Android phone", [("Model", "CPH1941")])]
        info.consejos = ["Unlock the phone"]
        info.crudos = [("udev attributes", "ATTR{x}==1")]
        texto = info.as_text()
        for trozo in ("== Android phone ==", "Model: CPH1941", "* Unlock the phone", "== udev attributes ==", "ATTR{x}==1"):
            self.assertIn(trozo, texto)


if __name__ == "__main__":
    unittest.main()
