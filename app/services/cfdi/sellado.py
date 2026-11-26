"""Sellado del CFDI 4.0 con un ``Firmante`` (ADR-017), sin ``satcfdi``.

Recibe el XML sin sellar que arma ``comprobante.xml_sin_sellar``, pone
``NoCertificado`` y ``Certificado`` (el primero entra en la cadena original;
el segundo y el ``Sello`` no), calcula la cadena original con la XSLT oficial
del SAT (``xml_sat``) y pone el ``Sello``. Antes de devolver, verifica el
sello con la llave pública del certificado: si el firmante devolvió otra
cosa, falla aquí y no con el proveedor.

El spike ``spikes/cfdi_sellado`` comprobó que este camino da el mismo sello
que ``satcfdi`` y que Formas Digitales y Solución Factible lo timbran.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass

from lxml import etree

from app.services.cfdi import xml_sat
from app.services.cfdi.firmante import (
    ErrorFirmante,
    Firmante,
    certificado_der,
    numero_certificado,
    rfc_del_certificado,
    verificar_firma,
)

_PARSER = etree.XMLParser(no_network=True, resolve_entities=False, remove_comments=True)


class ErrorSellado(Exception):
    """El comprobante no se pudo sellar; mensaje en español."""


@dataclass(frozen=True)
class Sellado:
    xml: bytes
    cadena_original: str
    sha256_cadena: str  # hex; va a la bitácora (nunca la llave)
    no_certificado: str
    sello: str


def revisar_certificado(firmante: Firmante, rfc_emisor: str | None, fecha_utc: dt.datetime) -> None:
    """El certificado debe ser del RFC emisor y estar vigente en la fecha del comprobante."""
    cert = firmante.certificado()
    rfc = rfc_del_certificado(cert)
    if not rfc_emisor or rfc != rfc_emisor.upper():
        raise ErrorSellado(
            f"El certificado de sello es del RFC {rfc or 'desconocido'} y la factura la emite {rfc_emisor or 'un RFC vacío'}."
        )
    if fecha_utc.tzinfo is None:
        fecha_utc = fecha_utc.replace(tzinfo=dt.timezone.utc)
    if not (cert.not_valid_before_utc <= fecha_utc <= cert.not_valid_after_utc):
        raise ErrorSellado(
            "El certificado de sello no está vigente en la fecha de la factura "
            f"(vigencia {cert.not_valid_before_utc:%Y-%m-%d} a {cert.not_valid_after_utc:%Y-%m-%d})."
        )


def sellar(xml_sin_sellar: bytes, firmante: Firmante) -> Sellado:
    raiz = etree.fromstring(xml_sin_sellar, _PARSER)
    cert = firmante.certificado()
    try:
        no_certificado = numero_certificado(cert)
    except ErrorFirmante as exc:
        raise ErrorSellado(str(exc)) from exc
    raiz.set("NoCertificado", no_certificado)
    raiz.set("Certificado", base64.b64encode(certificado_der(cert)).decode("ascii"))
    raiz.set("Sello", "")
    sin_sello = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
    cadena = xml_sat.cadena_original(sin_sello)
    datos = cadena.encode("utf-8")
    firma = firmante.firmar(datos)
    if not verificar_firma(cert, firma, datos):
        raise ErrorSellado("La firma devuelta por el servicio de llaves no corresponde al certificado.")
    sello = base64.b64encode(firma).decode("ascii")
    raiz.set("Sello", sello)
    xml = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
    return Sellado(
        xml=xml,
        cadena_original=cadena,
        sha256_cadena=hashlib.sha256(datos).hexdigest(),
        no_certificado=no_certificado,
        sello=sello,
    )


def verificar_sello(xml_sellado: bytes) -> bool:
    """Regenera la cadena con la XSLT oficial y verifica el sello con el certificado embebido."""
    from app.services.cfdi.firmante import cargar_certificado  # noqa: PLC0415

    raiz = etree.fromstring(xml_sellado, _PARSER)
    sello, cert_b64 = raiz.get("Sello"), raiz.get("Certificado")
    if not sello or not cert_b64:
        return False
    cert = cargar_certificado(base64.b64decode(cert_b64))
    cadena = xml_sat.cadena_original(etree.tostring(raiz, xml_declaration=True, encoding="UTF-8"))
    return verificar_firma(cert, base64.b64decode(sello), cadena.encode("utf-8"))
