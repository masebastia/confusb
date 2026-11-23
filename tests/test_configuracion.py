# SPDX-License-Identifier: GPL-3.0-or-later
"""¿Se puede configurar el dispositivo?: análisis del descriptor HID (con los de un ratón gaming y un teclado
reales), controles de cámara y audio, soporte conocido y el veredicto."""
import errno
import os
import struct
import tempfile
import unittest
from unittest import mock

from confusb import configuracion as c
from confusb import i18n, resolver, soporte, usbinfo

# Descriptores reales (sysfs, report_descriptor) de un ratón gaming PixArt 093a:2533 y de un Logitech K120
RATON_1 = bytes.fromhex("05010902a1010901a100050919012905150025017501950581027503950181030600ff0940950275081581257f"
                        "8102050109381581257f7508950181060930093116018026ff7f751095028106c0c0")
RATON_2 = bytes.fromhex("0600ff0901a101150026ff0075080902950285018102090195018510b10209019644018511b102090195028512b102"
                        "c005010906a1018503050719e029e715002501750195088102190029ff150026ff00750895018100c0050c0901a101"
                        "850219002a9c021500269c02751095018100c0")
TECLADO_1 = bytes.fromhex("05010906a101050719e029e71500250175019508810295017508810195057501050819012905910295017503"
                          "910195067508150026ff00050719002aff008100c0")
TECLADO_2 = bytes.fromhex("050c0901a101850109e015e8251875079501810615002501750109e28106c00601000980a10185022501150075"
                          "010a81000a82000a83009503810695058101c0060c000901a10185032501150075010ab5000ab6000ab7000ab800"
                          "0acd000ae2000ae9000aea00950881020a83010a8a010a92010a94010a21020a23020a24020a2502950881020a26"
                          "020a27020a2a020ab3000ab4009505810295038101c00600ff0901a1018505150026ff001901290275089505b102c0")

AMIXER_CAMARA = """Simple mixer control 'Mic',0
  Capabilities: cvolume cvolume-joined cswitch cswitch-joined
  Capture channels: Mono
  Limits: Capture 0 - 3072
  Mono: Capture 3072 [100%] [6.00dB] [on]
"""


def info(vid="093a", pid="2533", titulo="Gaming Mouse", clases=(0x03,), interfaces=(), nodos=(), syspath="/x/1-6"):
    i = usbinfo.DeviceInfo(syspath=syspath, vid=vid, pid=pid, product=titulo)
    i.classes = set(clases)
    i.interfaces = [usbinfo.Interface(f"1-6:1.{n}", str(n), cls, sub, proto, None, None, None, [], [])
                    for n, (cls, sub, proto) in enumerate(interfaces)]
    i.nodes = list(nodos)
    return i


def hid(*descriptores):
    return [c.analizar_hid(d, f"1-6:1.{n}") for n, d in enumerate(descriptores)]


class Base(unittest.TestCase):
    def setUp(self):
        i18n.activar("en")
        self.addCleanup(i18n.activar, "en")


class PruebasHid(Base):
    def test_el_primer_descriptor_del_raton(self):
        r = c.analizar_hid(RATON_1)
        self.assertEqual(r.aplicaciones, [(1, 2)])
        self.assertEqual((r.botones, r.ejes), (5, ["X", "Y", "Wheel"]))
        self.assertEqual(r.del_fabricante(), [])

    def test_el_segundo_tiene_un_canal_del_fabricante(self):
        r = c.analizar_hid(RATON_2)
        self.assertEqual(r.aplicaciones, [(0xFF00, 1), (1, 6), (0x0C, 1)])
        self.assertEqual([(i.tipo, i.id, i.bytes) for i in r.del_fabricante()],
                         [("Feature", 16, 1), ("Feature", 17, 324), ("Feature", 18, 2)])

    def test_un_teclado_normal_no_tiene_canal_propio(self):
        for d in (TECLADO_1, TECLADO_2):
            self.assertEqual(c.canal_del_fabricante([c.analizar_hid(d)]).__class__, list)
        self.assertEqual(c.canal_del_fabricante(hid(TECLADO_1, TECLADO_2)), [])    # un informe suelto de 5 bytes

    def test_el_canal_del_raton_si_es_sustancial(self):
        self.assertEqual(len(c.canal_del_fabricante(hid(RATON_1, RATON_2))), 3)

    def test_varios_informes_pequenos_o_uno_grande_cuentan(self):
        pequeno = lambda n: c.ResumenHid("x", informes=[c.InformeHid("Feature", i, 0xFF00, 8) for i in range(n)])  # noqa: E731
        self.assertEqual(c.canal_del_fabricante([pequeno(2)]), [])
        self.assertEqual(len(c.canal_del_fabricante([pequeno(3)])), 3)
        grande = c.ResumenHid("x", informes=[c.InformeHid("Output", 1, 0xFF42, 20 * 8)])
        self.assertEqual(len(c.canal_del_fabricante([grande])), 1)

    def test_descriptor_vacio_o_cortado_no_falla(self):
        self.assertEqual(c.analizar_hid(b"").informes, [])
        c.analizar_hid(RATON_2[:40])            # cortado a mitad de un elemento
        c.analizar_hid(b"\xfe\x05\x00")         # elemento largo incompleto

    def test_se_lee_de_sysfs(self):
        with tempfile.TemporaryDirectory() as t:
            ruta = os.path.join(t, "1-6:1.0", "0003:093A:2533.0001")
            os.makedirs(ruta)
            with open(os.path.join(ruta, "report_descriptor"), "wb") as f:
                f.write(RATON_1)
            (r,) = c.descriptores_hid(t)
        self.assertEqual((r.interfaz, r.botones), ("1-6:1.0", 5))


class PruebasEvaluacion(Base):
    def evaluar(self, i, descriptores=()):
        with mock.patch.object(c, "descriptores_hid", return_value=hid(*descriptores)), \
                mock.patch.object(c, "libratbag_instalado", return_value={}):
            return c.evaluar(i)

    def test_el_raton_gaming_quiza_es_configurable(self):
        i = info(interfaces=[(3, 1, 2), (3, 0, 1)])
        ev = self.evaluar(i, (RATON_1, RATON_2))
        self.assertEqual(ev.nivel, "posible")
        self.assertEqual(ev.tipos, {"raton", "teclado"})
        textos = " ".join(t for _n, t in ev.razones)
        self.assertIn("324 bytes", textos)
        self.assertEqual(sum("layout" in t for _n, t in ev.razones), 0)      # su «teclado» no se cuenta aparte

    def test_un_teclado_normal_solo_tiene_ajustes_del_sistema(self):
        ev = self.evaluar(info("046d", "c31c", "Keyboard K120", interfaces=[(3, 1, 1), (3, 0, 0)]), (TECLADO_1, TECLADO_2))
        self.assertEqual((ev.nivel, ev.tipos), ("sistema", {"teclado"}))

    def test_una_camara_es_configurable_y_se_dice_por_que(self):
        ev = self.evaluar(info("05a3", "9331", "Camera", clases=(0x0E, 0x01)))
        self.assertEqual(ev.nivel, "configurable")
        self.assertEqual(ev.tipos, {"camara", "audio"})

    def test_bluetooth_impresora_y_almacenamiento_son_ajustes_del_sistema(self):
        for clase, tipo in ((0xE0, "bluetooth"), (0x07, "impresora"), (0x08, "almacenamiento")):
            with self.subTest(tipo=tipo):
                ev = self.evaluar(info("1111", "2222", "X", clases=(clase,)))
                self.assertEqual((ev.nivel, ev.tipos), ("sistema", {tipo}))

    def test_un_adaptador_de_red(self):
        ev = self.evaluar(info("1111", "2222", "X", nodos=[("net", "network interface eth1")]))
        self.assertEqual((ev.nivel, ev.tipos), ("sistema", {"red"}))

    def test_un_mando_es_posible_con_input_remapper(self):
        gamepad = bytes.fromhex("05010905a101050919012910150025017501951081020501c0")
        ev = self.evaluar(info("1111", "2222", "Pad"), (gamepad,))
        self.assertEqual((ev.nivel, ev.tipos), ("posible", {"mando"}))

    def test_un_dispositivo_sin_nada_no_es_configurable(self):
        ev = self.evaluar(info("1111", "2222", "Cosa", clases=(0xFF,)))
        self.assertEqual(ev.nivel, "ninguna")
        self.assertEqual([t for _n, t in ev.razones], ["No configurable settings were found."])

    def test_un_receptor_de_logitech_conocido_es_configurable_con_solaar(self):
        ev = self.evaluar(info("046d", "c52b", "Unifying Receiver"))
        self.assertEqual(ev.nivel, "configurable")
        self.assertIn(("Solaar", "Unifying Receiver"), ev.soportes)

    def test_un_razer_sin_soporte_confirmado_es_posible(self):
        ev = self.evaluar(info("1532", "ffff", "Razer X", clases=(0x03,)))
        self.assertEqual(ev.nivel, "posible")
        self.assertIn("OpenRazer", ev.razones[0][1])

    def test_el_veredicto_es_el_mejor_de_sus_razones(self):
        ev = c.Evaluacion()
        ev.razon("sistema", "a")
        ev.razon("configurable", "b")
        ev.razon("posible", "c")
        self.assertEqual(ev.nivel, "configurable")


class PruebasSoporte(Base):
    def test_tablas_generadas(self):
        self.assertGreater(len(soporte.LIBRATBAG), 100)
        self.assertEqual(soporte.SOLAAR["046d:c52b"], "Unifying Receiver")
        self.assertIn("1532:0013", soporte.OPENRAZER)
        self.assertNotIn("093a:2533", soporte.LIBRATBAG)        # el ratón de las pruebas: libratbag no lo conoce

    def test_soportado_por(self):
        with mock.patch.object(c, "libratbag_instalado", return_value={}):
            self.assertEqual(c.soportado_por(info("046d", "0a87", "G935")), [("libratbag (Piper)", "Logitech G935")])
            self.assertEqual(c.soportado_por(info("093a", "2533")), [])

    def test_los_datos_instalados_de_libratbag_tambien_valen(self):
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, "raro.device")
            with open(f, "w") as fh:
                fh.write("[Device]\nName=Ratón Raro\nDeviceMatch=usb:093a:2533;bluetooth:1:2:3\n")
            c._local = None
            self.addCleanup(setattr, c, "_local", None)
            with mock.patch.object(c.glob, "glob", return_value=[f]):
                self.assertEqual(c.libratbag_instalado(), {"093a:2533": "Ratón Raro"})
                self.assertEqual(c.soportado_por(info("093a", "2533")), [("libratbag (Piper)", "Ratón Raro")])


class PruebasValores(Base):
    def test_amixer(self):
        self.assertEqual(c.parsear_amixer(AMIXER_CAMARA), [("Mic", "100 % · on")])

    def test_amixer_ignora_controles_sin_volumen_ni_interruptor(self):
        texto = "Simple mixer control 'Capture Source',0\n  Capabilities: enum\n  Items: 'Mic' 'Line'\n"
        self.assertEqual(c.parsear_amixer(texto), [])

    def test_amixer_con_varios_controles_numerados(self):
        texto = ("Simple mixer control 'IEC958',0\n  Capabilities: pswitch pswitch-joined\n  Mono: Playback [on]\n"
                 "Simple mixer control 'IEC958',1\n  Capabilities: pswitch pswitch-joined\n  Mono: Playback [off]\n")
        self.assertEqual(c.parsear_amixer(texto), [("IEC958", "on"), ("IEC958 1", "off")])

    def test_la_tarjeta_de_sonido_sale_de_los_nodos(self):
        i = info(nodos=[("sound", "/dev/snd/controlC3"), ("sound", "/dev/snd/pcmC3D0c"), ("sound", "card3")])
        self.assertEqual(c.tarjetas_alsa(i), [3])

    def test_controles_v4l2(self):
        controles = [(0x980001, 6, b"User Controls", 0, 0, 0, 0, 0),                  # cabecera de clase: se salta
                     (0x980900, 1, b"Brightness", 1, 255, 1, 128, 0),
                     (0x980901, 1, b"Contrast", 1, 255, 1, 128, 1),                    # desactivado: se salta
                     (0x98090c, 2, b"White Balance, Automatic", 0, 1, 1, 1, 0)]
        pendientes = list(controles)
        valores = {0x980900: 140, 0x98090c: 1}

        def ioctl(fd, peticion, datos):
            if peticion == c.VIDIOC_QUERYCAP:
                return b"\0" * 88 + struct.pack("I", 1) + b"\0" * 12        # device_caps: captura de vídeo
            if peticion == c.VIDIOC_QUERYCTRL:
                if not pendientes:
                    raise OSError(errno.EINVAL, "no hay más")
                id_, tipo, nombre, mn, mx, paso, defecto, flags = pendientes.pop(0)
                return struct.pack("I I 32s i i i i I 8x", id_, tipo, nombre, mn, mx, paso, defecto, flags)
            if peticion == c.VIDIOC_G_CTRL:
                id_ = struct.unpack("I i", datos)[0]
                return struct.pack("I i", id_, valores[id_])
            raise AssertionError(peticion)

        with mock.patch.object(c.os, "open", return_value=99), mock.patch.object(c.os, "close"), \
                mock.patch.object(c.fcntl, "ioctl", ioctl):
            res = c.controles_v4l2("/dev/video0")
        self.assertEqual([(x.nombre, x.valor, x.minimo, x.maximo) for x in res],
                         [("Brightness", 140, 1, 255), ("White Balance, Automatic", 1, 0, 1)])

    def test_un_nodo_de_metadatos_no_es_una_camara(self):
        def ioctl(fd, peticion, datos):
            return b"\0" * 88 + struct.pack("I", 0x00800000) + b"\0" * 12           # solo META_CAPTURE
        with mock.patch.object(c.os, "open", return_value=99), mock.patch.object(c.os, "close"), \
                mock.patch.object(c.fcntl, "ioctl", ioctl):
            self.assertEqual(c.controles_v4l2("/dev/video1"), [])

    def test_sin_permiso_o_sin_nodo_no_falla(self):
        with mock.patch.object(c.os, "open", side_effect=PermissionError):
            self.assertEqual(c.controles_v4l2("/dev/video0"), [])


class PruebasPagina(Base):
    def informe(self, i, descriptores=(), ajustes=None, v4l2=(), alsa=()):
        with mock.patch.object(c, "descriptores_hid", return_value=hid(*descriptores)), \
                mock.patch.object(c, "libratbag_instalado", return_value={}), \
                mock.patch.object(c, "ajustes_sistema", return_value=ajustes or {}), \
                mock.patch.object(c, "controles_v4l2", return_value=list(v4l2)), \
                mock.patch.object(c, "controles_alsa", return_value=list(alsa)), \
                mock.patch.object(resolver, "pkg_states", return_value={}):
            return c.informe(i)

    def test_el_raton_gaming(self):
        ajustes = {"speed": "0.0", "accel-profile": "default", "left-handed": "false", "natural-scroll": "false"}
        inf = self.informe(info(interfaces=[(3, 1, 2), (3, 0, 1)]), (RATON_1, RATON_2), ajustes)
        self.assertEqual(inf.nivel, "posible")
        titulos = {g.title: g for g in inf.grupos}
        self.assertEqual(set(titulos), {"Current settings", "HID analysis", "Configuration tools"})
        valores = titulos["Current settings"].items[0]
        self.assertEqual(valores.title, "Mouse settings")
        for linea in ("Pointer speed: 0.0", "Acceleration profile: Default", "Left-handed: off", "Natural scrolling: off"):
            self.assertIn(linea, valores.desc)
        self.assertEqual(valores.actions[0].payload, ["gnome-control-center", "mouse"])
        analisis = " ".join(i.desc for i in titulos["HID analysis"].items)
        self.assertIn("#17 (324 B)", analisis)
        self.assertIn("Buttons: 5", analisis)
        herramientas = {i.title for i in titulos["Configuration tools"].items}
        self.assertEqual(herramientas, {"input-remapper", "Piper (libratbag)"})
        piper = next(i for i in titulos["Configuration tools"].items if i.title.startswith("Piper"))
        self.assertIn("093a:2533", piper.desc)
        self.assertEqual(piper.actions[0].kind, "url")
        self.assertIn("093a%3A2533", piper.actions[0].payload)

    def test_la_camara_muestra_sus_valores(self):
        controles = [c.Control("Brightness", 1, 128, 1, 255, 128), c.Control("White Balance, Automatic", 2, 1, 0, 1, 1)]
        inf = self.informe(info("05a3", "9331", "Camera", clases=(0x0E, 0x01), nodos=[("video4linux", "/dev/video0"),
                                                                                       ("sound", "/dev/snd/controlC0")]),
                           v4l2=controles, alsa=[("Mic", "100 % · on")])
        self.assertEqual(inf.nivel, "configurable")
        grupo = next(g for g in inf.grupos if g.title == "Current settings")
        camara = next(i for i in grupo.items if i.title == "Camera controls")
        self.assertEqual(camara.desc.splitlines(), ["Brightness: 128 (1–255)", "White Balance, Automatic: on"])
        audio = next(i for i in grupo.items if i.title == "Audio controls")
        self.assertEqual(audio.desc, "Mic: 100 % · on")

    def test_sin_nada_no_hay_paginas_vacias(self):
        self.assertEqual(self.informe(info("1111", "2222", "Cosa", clases=(0xFF,))).grupos, [])

    def test_el_volcado_en_texto(self):
        with mock.patch.object(c, "descriptores_hid", return_value=hid(RATON_1, RATON_2)), \
                mock.patch.object(c, "libratbag_instalado", return_value={}):
            lineas = c.texto(info())
        self.assertEqual(lineas[0], "== Configuration ==")
        self.assertEqual(lineas[1], "Can it be configured? Maybe configurable")
        self.assertTrue(lineas[2].startswith("* It has a manufacturer-specific HID channel"))

    def test_los_niveles_tienen_color_en_la_interfaz(self):
        from confusb.componentes import STATUS_CLASS
        self.assertIn("Configurable", STATUS_CLASS["ok"])
        self.assertIn("Maybe configurable", STATUS_CLASS["aviso"])
        self.assertEqual(set(c.NIVELES), set(c.ORDEN))

    def test_los_textos_se_traducen(self):
        i18n.activar("es")
        with mock.patch.object(c, "descriptores_hid", return_value=hid(RATON_1, RATON_2)), \
                mock.patch.object(c, "libratbag_instalado", return_value={}):
            lineas = c.texto(info())
        self.assertEqual(lineas[0], "== Configuración ==")
        self.assertIn("Quizá configurable", lineas[1])


if __name__ == "__main__":
    unittest.main()
