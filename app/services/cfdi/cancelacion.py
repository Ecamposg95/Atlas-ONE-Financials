"""Solicitud de cancelación de CFDI firmada por nosotros (XML-DSig enveloped).

El proveedor sólo recibe la solicitud ya firmada: nunca la llave ni un PFX
(ADR-017, ``firmar_cancelacion``). Es el ``Cancelacion`` del servicio del SAT
(``http://cancelacfd.sat.gob.mx``), con la misma firma que arma ``satcfdi``:
C14N 1.0 inclusiva, *enveloped-signature*, ``Reference URI=""`` y ``KeyInfo``
con ``X509IssuerSerial`` y el certificado.

Promovido de ``spikes/cfdi_sellado/cancelacion.py``. Hallazgos del spike que
este módulo respeta:

- ``algoritmo``: SHA-256 por omisión, que es lo único que firma AWS KMS con
  RSA. El SAT de pruebas lo aceptó vía Formas Digitales; Solución Factible
  sólo acepta SHA-1 (``firmar_sha1``, que sólo tiene la llave local).
- ``folio_sustitucion_vacio``: Formas Digitales rearma la solicitud con
  ``FolioSustitucion=""`` aunque el motivo no sea 01; si no se firma así, el
  SAT responde 302.
- ``c14n``: con lxml 6.1.3 / libxml2 2.14.6 canonicalizar un subárbol inventa
  ``xmlns=""`` en los nietos; se canonicaliza ``SignedInfo`` como documento
  aparte.
"""

from __future__ import annotations

import base64
import copy
import hashlib
from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from app.services.cfdi.firmante import Firmante, certificado_der

NS_CANCELACION = "http://cancelacfd.sat.gob.mx"
NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"
NS_XSD = "http://www.w3.org/2001/XMLSchema"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

# algoritmo -> (función de resumen, SignatureMethod, DigestMethod)
ALGORITMOS = {
    "sha1": (hashlib.sha1, "http://www.w3.org/2000/09/xmldsig#rsa-sha1", "http://www.w3.org/2000/09/xmldsig#sha1"),
    "sha256": (
        hashlib.sha256,
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "http://www.w3.org/2001/04/xmlenc#sha256",
    ),
}

MOTIVOS = {
    "01": "Comprobante emitido con errores con relación",
    "02": "Comprobante emitido con errores sin relación",
    "03": "No se llevó a cabo la operación",
    "04": "Operación nominativa relacionada en una factura global",
}

# Nombres cortos de OpenSSL, para que ``X509IssuerName`` salga igual que en satcfdi.
_NOMBRES_OPENSSL = {
    "2.5.4.3": "CN",
    "2.5.4.4": "SN",
    "2.5.4.5": "serialNumber",
    "2.5.4.6": "C",
    "2.5.4.7": "L",
    "2.5.4.8": "ST",
    "2.5.4.9": "street",
    "2.5.4.10": "O",
    "2.5.4.11": "OU",
    "2.5.4.17": "postalCode",
    "2.5.4.41": "name",
    "2.5.4.45": "x500UniqueIdentifier",
    "1.2.840.113549.1.9.1": "emailAddress",
    "1.2.840.113549.1.9.2": "unstructuredName",
}


class ErrorCancelacion(ValueError):
    """Solicitud inválida; mensaje en español."""


class AlgoritmoNoSoportado(ErrorCancelacion):
    """El firmante no sabe firmar con el algoritmo pedido (p. ej. KMS y SHA-1)."""


@dataclass(frozen=True)
class FolioCancelacion:
    uuid: str
    motivo: str
    folio_sustitucion: str | None = None

    def __post_init__(self):
        if self.motivo not in MOTIVOS:
            raise ErrorCancelacion(f"El motivo de cancelación {self.motivo!r} no existe; usa 01, 02, 03 o 04.")
        if self.motivo == "01" and not self.folio_sustitucion:
            raise ErrorCancelacion("El motivo 01 exige el folio fiscal (UUID) de la factura que sustituye a ésta.")
        if self.motivo != "01" and self.folio_sustitucion:
            raise ErrorCancelacion("Sólo el motivo 01 lleva folio de sustitución.")


def firmar_con(firmante: Firmante, datos: bytes, algoritmo: str) -> bytes:
    if algoritmo == "sha256":
        return firmante.firmar(datos)
    if algoritmo == "sha1":
        firmar_sha1 = getattr(firmante, "firmar_sha1", None)
        if firmar_sha1 is None:
            raise AlgoritmoNoSoportado(f"El firmante {firmante.tipo} no firma con RSA-SHA1.")
        return firmar_sha1(datos)
    raise AlgoritmoNoSoportado(f"Algoritmo de firma desconocido: {algoritmo}.")


def nombre_emisor(cert) -> str:
    """``X509IssuerName`` como lo arma satcfdi: componentes en orden inverso, ``k=v`` con nombres de OpenSSL."""
    partes = []
    for attr in reversed(list(cert.issuer)):
        clave = _NOMBRES_OPENSSL.get(attr.oid.dotted_string, attr.oid.dotted_string)
        valor = attr.value.decode("utf-8", "replace") if isinstance(attr.value, bytes) else attr.value
        partes.append(f"{clave}={valor}")
    return ",".join(partes)


def c14n(elemento) -> bytes:
    """C14N 1.0 inclusiva de un elemento como documento aparte (ver docstring del módulo)."""
    if elemento.getparent() is None:
        return etree.tostring(elemento, method="c14n")
    raiz = etree.Element(elemento.tag, dict(elemento.attrib), nsmap=elemento.nsmap)
    raiz.text = elemento.text
    for hijo in elemento:
        raiz.append(copy.deepcopy(hijo))
    return etree.tostring(etree.fromstring(etree.tostring(raiz)), method="c14n")


def _sub(padre, ns: str, nombre: str, texto: str | None = None, **attrs):
    e = etree.SubElement(padre, f"{{{ns}}}{nombre}", {k: v for k, v in attrs.items() if v is not None})
    if texto is not None:
        e.text = texto
    return e


def armar_solicitud(
    firmante: Firmante,
    rfc_emisor: str,
    folios: list[FolioCancelacion],
    fecha: datetime,
    algoritmo: str = "sha256",
    folio_sustitucion_vacio: bool = False,
) -> bytes:
    """Arma y firma la solicitud. Devuelve el XML en UTF-8, listo para el proveedor."""
    if algoritmo not in ALGORITMOS:
        raise AlgoritmoNoSoportado(f"Algoritmo de firma desconocido: {algoritmo}.")
    resumen, metodo_firma, metodo_resumen = ALGORITMOS[algoritmo]
    raiz = etree.Element(f"{{{NS_CANCELACION}}}Cancelacion", nsmap={None: NS_CANCELACION, "xsd": NS_XSD, "xsi": NS_XSI})
    raiz.set("RfcEmisor", rfc_emisor)
    raiz.set("Fecha", fecha.strftime("%Y-%m-%dT%H:%M:%S"))
    nodo_folios = _sub(raiz, NS_CANCELACION, "Folios")
    for f in folios:
        sustituto = f.folio_sustitucion or ("" if folio_sustitucion_vacio else None)
        _sub(nodo_folios, NS_CANCELACION, "Folio", UUID=f.uuid, Motivo=f.motivo, FolioSustitucion=sustituto)

    # Enveloped: el resumen es del documento sin la firma.
    valor_resumen = base64.b64encode(resumen(etree.tostring(raiz, method="c14n")).digest()).decode()

    firma = etree.SubElement(raiz, f"{{{NS_DSIG}}}Signature", nsmap={None: NS_DSIG, "xsd": NS_XSD, "xsi": NS_XSI})
    info = _sub(firma, NS_DSIG, "SignedInfo")
    _sub(info, NS_DSIG, "CanonicalizationMethod", Algorithm=C14N)
    _sub(info, NS_DSIG, "SignatureMethod", Algorithm=metodo_firma)
    ref = _sub(info, NS_DSIG, "Reference", URI="")
    _sub(_sub(ref, NS_DSIG, "Transforms"), NS_DSIG, "Transform", Algorithm=ENVELOPED)
    _sub(ref, NS_DSIG, "DigestMethod", Algorithm=metodo_resumen)
    _sub(ref, NS_DSIG, "DigestValue", valor_resumen)

    valor_firma = firmar_con(firmante, c14n(info), algoritmo)
    _sub(firma, NS_DSIG, "SignatureValue", base64.b64encode(valor_firma).decode())

    cert = firmante.certificado()
    x509 = _sub(_sub(firma, NS_DSIG, "KeyInfo"), NS_DSIG, "X509Data")
    serial = _sub(x509, NS_DSIG, "X509IssuerSerial")
    _sub(serial, NS_DSIG, "X509IssuerName", nombre_emisor(cert))
    _sub(serial, NS_DSIG, "X509SerialNumber", str(cert.serial_number))
    _sub(x509, NS_DSIG, "X509Certificate", base64.b64encode(certificado_der(cert)).decode("ascii"))
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


def verificar_solicitud(xml: bytes) -> bool:
    """Verifica la firma como lo haría quien la recibe (sólo lo que arma ``armar_solicitud``)."""
    from cryptography import x509 as cx509  # noqa: PLC0415
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import padding  # noqa: PLC0415

    raiz = etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False))
    ns = {"ds": NS_DSIG}
    firma = raiz.find("ds:Signature", ns)
    info = firma.find("ds:SignedInfo", ns)
    metodo = info.find("ds:SignatureMethod", ns).get("Algorithm")
    algoritmo = next(k for k, v in ALGORITMOS.items() if v[1] == metodo)
    resumen = ALGORITMOS[algoritmo][0]
    info_c14n = c14n(info)
    valor_firma = base64.b64decode(firma.findtext("ds:SignatureValue", namespaces=ns))
    cert = cx509.load_der_x509_certificate(
        base64.b64decode(firma.findtext("ds:KeyInfo/ds:X509Data/ds:X509Certificate", namespaces=ns))
    )
    digest_esperado = info.findtext("ds:Reference/ds:DigestValue", namespaces=ns)
    raiz.remove(firma)
    if base64.b64encode(resumen(etree.tostring(raiz, method="c14n")).digest()).decode() != digest_esperado:
        return False
    hash_cls = hashes.SHA1() if algoritmo == "sha1" else hashes.SHA256()  # noqa: S303
    try:
        cert.public_key().verify(valor_firma, info_c14n, padding.PKCS1v15(), hash_cls)
    except InvalidSignature:
        return False
    return True
