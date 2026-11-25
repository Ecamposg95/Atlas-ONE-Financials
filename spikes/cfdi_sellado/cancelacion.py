"""Solicitud de cancelación de CFDI firmada por nosotros (XML-DSig enveloped).

El proveedor sólo recibe la solicitud ya firmada: nunca la llave ni el PFX
(ADR-017, ``firmar_cancelacion``). El documento es el ``Cancelacion`` del
servicio del SAT (``http://cancelacfd.sat.gob.mx``):

.. code-block:: xml

    <Cancelacion xmlns="http://cancelacfd.sat.gob.mx" Fecha="…" RfcEmisor="…">
      <Folios><Folio UUID="…" Motivo="02"/></Folios>
      <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">…</Signature>
    </Cancelacion>

La firma es la misma que arma ``satcfdi.create.cancela.Cancelacion``:
canonicalización C14N 1.0 inclusiva, transformación *enveloped-signature*,
``Reference URI=""`` y ``KeyInfo`` con ``X509IssuerSerial`` y el certificado.
``satcfdi`` sólo sabe firmar con **RSA-SHA1**; aquí el algoritmo es un
parámetro para poder probar también **RSA-SHA256**, que es lo único que firma
AWS KMS con RSA (``RSASSA_PKCS1_V1_5_SHA_256``).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import warnings
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives import serialization
from lxml import etree
from OpenSSL import crypto

from firmante import Firmante

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

MOTIVOS = {"01", "02", "03", "04"}


class AlgoritmoNoSoportado(Exception):
    """El firmante no sabe firmar con el algoritmo pedido (p. ej. AWS KMS y SHA-1)."""


@dataclass(frozen=True)
class FolioCancelacion:
    uuid: str
    motivo: str
    folio_sustitucion: str | None = None

    def __post_init__(self):
        if self.motivo not in MOTIVOS:
            raise ValueError(f"Motivo de cancelación inválido: {self.motivo}")
        if self.motivo == "01" and not self.folio_sustitucion:
            raise ValueError("El motivo 01 exige el UUID que sustituye al cancelado")
        if self.motivo != "01" and self.folio_sustitucion:
            raise ValueError("Sólo el motivo 01 lleva folio de sustitución")


def firmar_con(firmante: Firmante, datos: bytes, algoritmo: str) -> bytes:
    """RSASSA-PKCS1-v1_5 con el resumen pedido, delegado al firmante.

    ``Firmante.firmar`` es SHA-256 (el sello del CFDI). SHA-1 sólo existe si el
    firmante expone ``firmar_sha1``: ``FirmanteLocal`` sí; ``FirmanteAwsKms`` no,
    porque KMS no ofrece SHA-1 para RSA.
    """
    if algoritmo == "sha256":
        return firmante.firmar(datos)
    if algoritmo == "sha1":
        firmar_sha1 = getattr(firmante, "firmar_sha1", None)
        if firmar_sha1 is None:
            raise AlgoritmoNoSoportado(f"{type(firmante).__name__} no firma con RSA-SHA1")
        return firmar_sha1(datos)
    raise AlgoritmoNoSoportado(algoritmo)


def _emisor_x509(firmante: Firmante) -> tuple[str, int, str]:
    cert = firmante.certificado()
    # Mismo formato de IssuerName que satcfdi (componentes OpenSSL en orden inverso).
    with warnings.catch_warnings():  # pyOpenSSL marca get_issuer como obsoleto
        warnings.simplefilter("ignore", DeprecationWarning)
        componentes = crypto.X509.from_cryptography(cert).get_issuer().get_components()
    emisor = ",".join(f"{k.decode()}={v.decode()}" for k, v in reversed(componentes))
    der = cert.public_bytes(serialization.Encoding.DER)
    return emisor, cert.serial_number, base64.b64encode(der).decode("ascii")


def c14n(elemento) -> bytes:
    """C14N 1.0 inclusiva de un elemento, con los namespaces que tiene en alcance.

    No se usa ``etree.tostring(elemento, method="c14n")`` sobre un subárbol:
    con lxml 6.1.3 / libxml2 2.14.6 los nietos del elemento salen con
    ``xmlns=""`` (se comprobó con un XML mínimo) y la firma deja de verificar
    en el SAT. Se copia el elemento como raíz de un documento nuevo, declarando
    los namespaces en alcance, que es lo que la C14N inclusiva emite.
    """
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
    algoritmo: str = "sha1",
    folio_sustitucion_vacio: bool = False,
) -> bytes:
    """Arma y firma la solicitud. Devuelve el XML en UTF-8, listo para el proveedor.

    ``folio_sustitucion_vacio``: pone ``FolioSustitucion=""`` cuando no hay
    sustituto. Formas Digitales no recibe el XML sino sus campos y rearma el
    documento siempre con ese atributo; si lo firmamos sin él, el resumen no
    coincide y el SAT responde 302 (ver README).
    """
    resumen, metodo_firma, metodo_resumen = ALGORITMOS[algoritmo]
    nsmap = {None: NS_CANCELACION, "xsd": NS_XSD, "xsi": NS_XSI}
    raiz = etree.Element(f"{{{NS_CANCELACION}}}Cancelacion", nsmap=nsmap)
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

    # SignedInfo se canonicaliza ya dentro del documento (hereda los namespaces).
    valor_firma = firmar_con(firmante, c14n(info), algoritmo)
    _sub(firma, NS_DSIG, "SignatureValue", base64.b64encode(valor_firma).decode())

    emisor, serie, cert_b64 = _emisor_x509(firmante)
    x509 = _sub(_sub(firma, NS_DSIG, "KeyInfo"), NS_DSIG, "X509Data")
    serial = _sub(x509, NS_DSIG, "X509IssuerSerial")
    _sub(serial, NS_DSIG, "X509IssuerName", emisor)
    _sub(serial, NS_DSIG, "X509SerialNumber", str(serie))
    _sub(x509, NS_DSIG, "X509Certificate", cert_b64)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


def verificar_solicitud(xml: bytes) -> bool:
    """Verifica la firma de una solicitud como lo haría quien la recibe.

    Recalcula el resumen del documento sin ``Signature`` y verifica
    ``SignatureValue`` sobre ``SignedInfo`` canonicalizado con la llave pública
    del ``X509Certificate`` embebido. Sólo soporta lo que arma ``armar_solicitud``.
    """
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
    hash_cls = hashes.SHA1() if algoritmo == "sha1" else hashes.SHA256()
    try:
        cert.public_key().verify(valor_firma, info_c14n, padding.PKCS1v15(), hash_cls)
    except InvalidSignature:
        return False
    return True
