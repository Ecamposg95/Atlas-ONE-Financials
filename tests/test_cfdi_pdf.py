"""Representación impresa (PDF) del CFDI 4.0, armada desde el XML.

Lo que se prueba: el total con letra, el formato del QR de verificación del
SAT, que el PDF sale del XML para un borrador y para uno timbrado (con un
``TimbreFiscalDigital`` de prueba), y la ruta con sus encabezados y el
aislamiento entre empresas.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import re
import zlib
from decimal import Decimal as D

import pytest
from lxml import etree

from app.models.fiscal_document import FiscalDocumentXml
from app.services.cfdi import pdf as cfdi_pdf
from app.services.cfdi.armado import Operacion, armar
from app.services.cfdi.comprobante import NS_CFDI, Comprobante, Emisor, Receptor, resumir, xml_sin_sellar
from app.services.cfdi.pdf import (
    cadena_original_tfd,
    formato_total_qr,
    leer_cfdi,
    render_pdf,
    total_con_letra,
    url_verificacion,
)
from tests.test_cfdi_documento_fiscal import _cliente, _crear, _empresa, _ingreso

UUID = "5803EB8D-81CD-4557-8719-26632D2FA434"
SELLO = "QmFzZTY0U2VsbG9EZWxFbWlzb3JEZVBydWViYQ" * 8 + "rH8/bw=="
SELLO_SAT = "U2VsbG9EZWxTQVREZVBydWViYQ" * 12 + "Zz0aQ=="
NO_CERT = "30001000000500003416"
NO_CERT_SAT = "30001000000500003456"


# ---------------------------------------------------------------- total con letra


@pytest.mark.parametrize(
    ("total", "esperado"),
    [
        ("0.50", "CERO PESOS 50/100 M.N."),
        ("1", "UN PESO 00/100 M.N."),
        ("21", "VEINTIÚN PESOS 00/100 M.N."),
        ("100", "CIEN PESOS 00/100 M.N."),
        ("1001234.56", "UN MILLÓN MIL DOSCIENTOS TREINTA Y CUATRO PESOS 56/100 M.N."),
        ("1000000", "UN MILLÓN DE PESOS 00/100 M.N."),
        ("1160.00", "MIL CIENTO SESENTA PESOS 00/100 M.N."),
        ("101", "CIENTO UN PESOS 00/100 M.N."),
        ("21000", "VEINTIÚN MIL PESOS 00/100 M.N."),
        ("31531", "TREINTA Y UN MIL QUINIENTOS TREINTA Y UN PESOS 00/100 M.N."),
        ("2000000000", "DOS MIL MILLONES DE PESOS 00/100 M.N."),
        ("16.995", "DIECISIETE PESOS 00/100 M.N."),  # se redondea al centavo, mitad hacia arriba
    ],
)
def test_total_con_letra(total, esperado):
    assert total_con_letra(D(total)) == esperado


def test_total_con_letra_en_otra_moneda_y_errores():
    assert total_con_letra("1250.10", "USD") == "MIL DOSCIENTOS CINCUENTA DÓLAR AMERICANO 10/100 USD"
    with pytest.raises(ValueError):
        total_con_letra("-1")


# ---------------------------------------------------------------- QR


@pytest.mark.parametrize(
    ("total", "tt"),
    [
        ("1160.00", "1160.0"),
        ("1160.50", "1160.5"),
        ("0.123456", "0.123456"),
        ("1001234.56", "1001234.56"),
        ("0", "0.0"),
    ],
)
def test_formato_total_del_qr(total, tt):
    assert formato_total_qr(D(total)) == tt


def test_url_de_verificacion():
    url = url_verificacion(UUID, "EKU9003173C9", "XEXX010101000", D("1000.00"), SELLO)
    assert url == (
        "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
        f"?id={UUID}&re=EKU9003173C9&rr=XEXX010101000&tt=1000.0&fe=rH8/bw=="
    )
    # Un RFC con '&' va como entidad XML.
    assert "&re=A&amp;B010101AAA&" in url_verificacion(UUID, "A&B010101AAA", "X", "1", SELLO)


# ---------------------------------------------------------------- fixtures de XML


def _xml_borrador() -> bytes:
    armado = armar(Operacion("Servicio de contabilidad noviembre", D("1000.00"), D("160.00"), D("1160.00"), D("0.16")))
    r = resumir(armado.conceptos)
    comp = Comprobante(
        serie="A",
        folio="7",
        fecha=dt.datetime(2026, 11, 25, 10, 0, 0),
        lugar_expedicion="64000",
        emisor=Emisor("EKU9003173C9", "ESCUELA KEMPER URGATE", "601"),
        receptor=Receptor("URE180429TM6", "UNIVERSIDAD ROBOTICA ESPAÑOLA", "86991", "601", "G03"),
        conceptos=armado.conceptos,
        subtotal=r.subtotal,
        total=r.total,
        descuento=r.descuento,
        total_impuestos_trasladados=r.total_trasladados,
        total_impuestos_retenidos=r.total_retenidos,
        forma_pago="03",
        metodo_pago="PUE",
    )
    return xml_sin_sellar(comp, leyenda="BORRADOR")


def _xml_timbrado() -> bytes:
    """El borrador con sello, certificado y un TimbreFiscalDigital de prueba (no son de un PAC real)."""
    raiz = etree.fromstring(_xml_borrador(), etree.XMLParser(remove_comments=True))
    raiz.set("Sello", SELLO)
    raiz.set("NoCertificado", NO_CERT)
    raiz.set("Certificado", "TUlJRm9EQ0NBK0FnQXdJQkFnSVVNekF3TURFd01EQXdNREExTURBd01ETTBNVFl3RFFZSktvWklodmNOQVFFTEJRQXc=")
    ns_tfd = "http://www.sat.gob.mx/TimbreFiscalDigital"
    complemento = etree.SubElement(raiz, f"{{{NS_CFDI}}}Complemento")
    tfd = etree.SubElement(complemento, f"{{{ns_tfd}}}TimbreFiscalDigital", nsmap={"tfd": ns_tfd})
    for nombre, valor in (
        ("Version", "1.1"),
        ("UUID", UUID),
        ("FechaTimbrado", "2026-11-25T10:01:02"),
        ("RfcProvCertif", "SPR190613I52"),
        ("SelloCFD", SELLO),
        ("NoCertificadoSAT", NO_CERT_SAT),
        ("SelloSAT", SELLO_SAT),
    ):
        tfd.set(nombre, valor)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


def _texto_pdf(contenido: bytes) -> str:
    """Texto crudo de los flujos de contenido (Helvetica, WinAnsi): basta para buscar cadenas ASCII."""
    partes = []
    for flujo in re.findall(rb"stream\r?\n(.*?)\s*endstream", contenido, re.S):
        datos = flujo.strip()
        if datos.endswith(b"~>"):  # reportlab: /ASCII85Decode /FlateDecode
            datos = base64.a85decode(datos[:-2])
        try:
            partes.append(zlib.decompress(datos).decode("latin-1"))
        except zlib.error:
            partes.append(datos.decode("latin-1"))
    return "\n".join(partes)


# ---------------------------------------------------------------- lectura y render


def test_lee_el_xml_con_catalogos():
    datos = leer_cfdi(_xml_timbrado())
    assert (datos.serie_folio, datos.total, datos.timbrado, datos.sellado) == ("A-7", "1160.00", True, True)
    assert datos.timbre.uuid == UUID and datos.conceptos[0].impuestos[0].importe == "160.00"
    assert cfdi_pdf._clave("c_RegimenFiscal", "601") == "601 - General de Ley Personas Morales"
    assert cfdi_pdf._clave("c_UsoCFDI", "G03") == "G03 - Gastos en general"
    assert cadena_original_tfd(datos.timbre) == (
        f"||1.1|{UUID}|2026-11-25T10:01:02|SPR190613I52|{SELLO}|{NO_CERT_SAT}||"
    )
    borrador = leer_cfdi(_xml_borrador())
    assert (borrador.timbrado, borrador.sellado) == (False, False)


def test_pdf_de_borrador_lleva_la_marca_y_no_el_qr():
    contenido = render_pdf(_xml_borrador())
    assert contenido.startswith(b"%PDF-")
    texto = _texto_pdf(contenido)
    assert "SIN VALIDEZ FISCAL" in texto and "BORRADOR" in texto
    assert "MIL CIENTO SESENTA PESOS 00/100 M.N." in texto
    assert "601 - General de Ley Personas Morales" in texto
    assert "TIMBRE FISCAL DIGITAL" not in texto


def test_pdf_timbrado_lleva_uuid_sellos_y_qr():
    contenido = render_pdf(_xml_timbrado())
    texto = _texto_pdf(contenido)
    assert UUID in texto and NO_CERT_SAT in texto and NO_CERT in texto
    assert "TIMBRE FISCAL DIGITAL" in texto and "SIN VALIDEZ FISCAL" not in texto
    assert "representaci" in texto  # leyenda del pie
    # Un QR dibuja muchos módulos como rectángulos rellenos ("re" ... "f").
    assert texto.count(" re") > 200


def test_xml_que_no_es_cfdi():
    with pytest.raises(cfdi_pdf.CfdiIlegible):
        render_pdf(b"<x/>")
    with pytest.raises(cfdi_pdf.CfdiIlegible):
        render_pdf(b"no es xml")


# ---------------------------------------------------------------- API


def test_api_pdf_borrador_timbrado_y_aislamiento(client, db):
    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    ruta = f"/api/fiscal-mx/documents/{doc['id']}/pdf"

    response = client.get(ruta, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="A-1.pdf"' in response.headers["content-disposition"]
    assert "ninguna" in response.headers["x-validez-fiscal"]
    assert response.content.startswith(b"%PDF-")
    assert "SIN VALIDEZ FISCAL" in _texto_pdf(response.content)

    otra = _empresa(client, email="otra@example.com")
    assert client.get(ruta, headers=otra).status_code == 404
    assert client.get("/api/fiscal-mx/documents/no-existe/pdf", headers=headers).status_code == 404

    # Con un XML timbrado guardado, el PDF sale de ese XML y no de las filas.
    xml = _xml_timbrado()
    db.add(
        FiscalDocumentXml(
            organization_id=headers["X-Organization-ID"],
            documento_id=doc["id"],
            tipo="TIMBRADO",
            contenido=xml,
            sha256=hashlib.sha256(xml).hexdigest(),
            bytes=len(xml),
        )
    )
    db.commit()
    timbrado = client.get(ruta, headers=headers)
    assert timbrado.status_code == 200
    assert 'filename="A-7.pdf"' in timbrado.headers["content-disposition"]
    assert "x-validez-fiscal" not in timbrado.headers
    assert UUID in _texto_pdf(timbrado.content)
    assert client.get(ruta, headers=otra).status_code == 404
