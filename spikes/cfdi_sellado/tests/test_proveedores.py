"""Adaptadores de proveedor con respuestas grabadas de sus ambientes de pruebas (sin red).

Las respuestas en ``tests/grabadas/`` se capturaron el 2026-11-25 contra
``dev33.facturacfdi.mx`` / ``dev-cancelacion.facturacfdi.mx`` (Formas Digitales)
y ``testing.solucionfactible.com`` (Solución Factible). Son respuestas, no
peticiones: no contienen credenciales (hay una prueba que lo revisa).
"""

import base64
import os
from datetime import datetime
from pathlib import Path

import pytest
from lxml import etree

from cancelacion import NS_DSIG, FolioCancelacion, armar_solicitud
from pac_formas_digitales import URL_CANCELACION_PRUEBAS, URL_TIMBRADO_PRUEBAS, FormasDigitales
from pac_solucion_factible import SolucionFactible
from proveedor_timbrado import Estado, ProveedorTimbrado, SinRespuesta
from verificacion_sat import verificar_sello

GRABADAS = Path(__file__).parent / "grabadas"
UUID_FD = "8C8D31A9-21B1-4604-9EE0-DF8349849ED5"


def grabada(nombre: str) -> bytes:
    return (GRABADAS / nombre).read_bytes()


class TransporteGrabado:
    """Devuelve respuestas grabadas en orden y registra lo que se envió."""

    def __init__(self, *respuestas: str):
        self._respuestas = list(respuestas)
        self.enviados: list[tuple[str, str, bytes]] = []

    def __call__(self, url, accion, cuerpo):
        self.enviados.append((url, accion, cuerpo))
        r = self._respuestas.pop(0)
        if r == "timeout":
            raise SinRespuesta("timed out")
        return grabada(r)


def test_grabadas_sin_credenciales():
    # Los valores reales sólo se revisan si están en el entorno: no se escriben aquí.
    secretos = [os.environ[v].encode() for v in ("FD_USUARIO", "FD_CONTRASENA", "SF_USUARIO", "SF_CONTRASENA") if os.environ.get(v)]
    secretos += [b"password>", b"usuario>", b"PRIVATE KEY"]
    for f in GRABADAS.iterdir():
        contenido = f.read_bytes()
        for secreto in secretos:
            assert secreto not in contenido, f"{f.name} contiene una credencial o una etiqueta de acceso"


def test_los_adaptadores_cumplen_la_interfaz():
    assert isinstance(FormasDigitales("u", "p", TransporteGrabado()), ProveedorTimbrado)
    assert isinstance(SolucionFactible("u", "p", TransporteGrabado()), ProveedorTimbrado)


# ------------------------------------------------------------ Formas Digitales


def test_fd_timbrado_ok_y_el_sello_sigue_valido():
    t = TransporteGrabado("fd_timbrar_ok.xml")
    r = FormasDigitales("u", "p", t).timbrar(b"<cfdi:Comprobante/>", "doc-1")
    assert r.estado is Estado.TIMBRADO
    assert (r.uuid, r.rfc_prov_certif, r.fecha_timbrado) == (UUID_FD, "SPR190613I52", "2026-11-25T12:42:24")
    verificar_sello(r.xml_timbrado)  # lanza si el proveedor tocó nuestro sello
    url, _, cuerpo = t.enviados[0]
    assert url == URL_TIMBRADO_PRUEBAS and b"TimbrarCFDI>" in cuerpo


def test_fd_reenviar_el_mismo_xml_devuelve_el_mismo_uuid():
    r = FormasDigitales.interpretar_timbrado(grabada("fd_timbrar_duplicado.xml"))
    assert r.estado is Estado.TIMBRADO and r.uuid == UUID_FD


@pytest.mark.parametrize(
    ("archivo", "codigo"),
    [
        ("fd_timbrar_cfdi40102.xml", "CFDI40102"),  # sello no corresponde a la cadena
        ("fd_timbrar_401.xml", "401"),  # fecha fuera de las 72 horas
        ("fd_timbrar_cfdi40147.xml", "CFDI40147"),  # receptor fuera de la lista de RFC
        ("fd_timbrar_credenciales.xml", "CFDI40999"),  # usuario o contraseña
    ],
)
def test_fd_rechazos(archivo, codigo):
    r = FormasDigitales.interpretar_timbrado(grabada(archivo))
    assert r.estado is Estado.RECHAZADO and r.codigo_proveedor == codigo and r.mensaje


def test_fd_sin_respuesta_es_indeterminado():
    r = FormasDigitales("u", "p", TransporteGrabado("timeout")).timbrar(b"<x/>", "doc-1")
    assert r.estado is Estado.INDETERMINADO


def test_fd_cancelacion_desarma_la_solicitud_firmada(firmante_local):
    sol = armar_solicitud(
        firmante_local, "EKU9003173C9", [FolioCancelacion("87CC3E45-05A9-45C3-936C-F5ABC784DC4F", "02")],
        datetime(2026, 11, 25, 12, 42, 49), "sha256", folio_sustitucion_vacio=True,
    )
    t = TransporteGrabado("fd_cancelar_201.xml")
    r = FormasDigitales("u", "p", t).cancelar(sol)
    assert r.aceptada and r.estatus_uuid == {"87CC3E45-05A9-45C3-936C-F5ABC784DC4F": "201"}
    url, _, cuerpo = t.enviados[0]
    assert url == URL_CANCELACION_PRUEBAS
    env = etree.fromstring(cuerpo)
    op = env.find(".//{http://wservicios/}Cancelacion40_2")
    assert op.findtext("rfcEmisor") == "EKU9003173C9"
    assert op.findtext("fecha") == "2026-11-25T12:42:49"
    assert op.findtext("folios/folio/motivo") == "02"
    firma_enviada = op.find("signatureType")
    firma = etree.fromstring(sol).find(f"{{{NS_DSIG}}}Signature")
    assert [c.tag for c in firma_enviada] == [c.tag for c in firma]
    assert firma_enviada.findtext(f"{{{NS_DSIG}}}SignatureValue") == firma.findtext(f"{{{NS_DSIG}}}SignatureValue")
    assert b"privateKey" not in cuerpo and b"publicKey" not in cuerpo


def test_fd_certificado_doble_base64_como_su_ejemplo(firmante_local):
    sol = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_FD, "02")], datetime(2026, 11, 25))
    cuerpo = FormasDigitales("u", "p", certificado_doble_base64=True).sobre_cancelar(sol)
    cert = etree.fromstring(cuerpo).findtext(f".//{{{NS_DSIG}}}X509Certificate")
    assert base64.b64decode(cert).startswith(b"MII")


@pytest.mark.parametrize(
    ("archivo", "aceptada", "codigo", "estatus"),
    [
        ("fd_cancelar_201.xml", True, "0", "201"),
        ("fd_cancelar_202.xml", True, "0", "202"),  # ya estaba cancelado
        ("fd_cancelar_205.xml", False, "0", "205"),  # el SAT aún no conoce el UUID
        ("fd_cancelar_302.xml", False, "302", None),  # firma inválida
    ],
)
def test_fd_respuestas_de_cancelacion(archivo, aceptada, codigo, estatus):
    r = FormasDigitales.interpretar_cancelacion(grabada(archivo))
    assert r.aceptada is aceptada and r.codigo_proveedor == codigo
    assert list(r.estatus_uuid.values()) == ([estatus] if estatus else [])
    assert r.acuse and b"CancelaCFDResponse" in r.acuse  # acuse firmado por el SAT de pruebas


@pytest.mark.parametrize(
    ("archivo", "estado", "cancelacion"),
    [
        ("fd_estatus_vigente.xml", "Vigente", None),
        ("fd_estatus_en_proceso.xml", "Vigente", "En proceso"),
        ("fd_estatus_no_encontrado.xml", "No Encontrado", None),
    ],
)
def test_fd_estatus(archivo, estado, cancelacion):
    r = FormasDigitales.interpretar_estatus(grabada(archivo))
    assert r.estado == estado and r.estatus_cancelacion == cancelacion


# ------------------------------------------------------------ Solución Factible


def test_sf_timbrado_ok():
    t = TransporteGrabado("sf_timbrar_ok.xml")
    r = SolucionFactible("u", "p", t).timbrar(b"<x/>", "doc-1")
    assert r.estado is Estado.TIMBRADO and r.uuid == "ED6F9F9A-FA7F-4FF1-ABD8-12A1B42AFE29"
    assert r.rfc_prov_certif == "SFE0807172W7"  # RFC de pruebas de su servidor, no el SAT
    verificar_sello(r.xml_timbrado)
    cuerpo = t.enviados[0][2]
    assert base64.b64encode(b"<x/>") in cuerpo


def test_sf_reenvio_devuelve_307_con_el_timbre_original():
    r = SolucionFactible.interpretar_timbrado(grabada("sf_timbrar_307.xml"))
    assert r.estado is Estado.TIMBRADO and r.codigo_proveedor == "307"
    assert r.uuid == "C5E45D99-A858-4FA4-893A-9323B84DEF59"


def test_sf_envia_la_solicitud_entera(firmante_local):
    sol = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_FD, "02")], datetime(2026, 11, 25))
    cuerpo = SolucionFactible("u", "p").sobre_cancelar(sol)
    enviado = etree.fromstring(cuerpo).findtext(".//{http://timbrado.ws.cfdi.solucionfactible.com}solicitudCancelacion")
    assert base64.b64decode(enviado) == sol


@pytest.mark.parametrize(
    ("archivo", "aceptada", "codigo"),
    [
        ("sf_cancelar_211.xml", True, "200"),  # RSA-SHA1: en proceso
        ("sf_cancelar_1801_sha256.xml", False, "1801"),  # RSA-SHA256: "cannot find validation key"
        ("sf_cancelar_1802.xml", False, "1802"),  # firma alterada
    ],
)
def test_sf_respuestas_de_cancelacion(archivo, aceptada, codigo):
    r = SolucionFactible.interpretar_cancelacion(grabada(archivo))
    assert r.aceptada is aceptada and r.codigo_proveedor == codigo


def test_sf_estatus_se_delega():
    with pytest.raises(NotImplementedError):
        SolucionFactible("u", "p").consultar_estatus(UUID_FD, "EKU9003173C9", "EWE1709045U0", "3480.00")
    fd = FormasDigitales("u", "p", TransporteGrabado("fd_estatus_vigente.xml"))
    r = SolucionFactible("u", "p", consulta_estatus=fd).consultar_estatus(UUID_FD, "EKU9003173C9", "EWE1709045U0", "3480.00")
    assert r.estado == "Vigente"
