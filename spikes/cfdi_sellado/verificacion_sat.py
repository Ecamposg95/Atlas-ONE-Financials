"""Cadena original, XSD y verificación del sello con los recursos OFICIALES del SAT.

No usa las copias que trae ``satcfdi``: lee lo que bajó ``descargar_recursos_sat.py``
en ``recursos_sat/`` y resuelve las URLs ``http://www.sat.gob.mx/...`` de las
inclusiones a esos archivos locales, sin red (``no_network`` y
``XSLTAccessControl`` sin lectura de red).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from firmante import numero_certificado

DIR_RECURSOS = Path(__file__).resolve().parent / "recursos_sat"
URL_XSLT_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt"
URL_XSD_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
NS_CFDI = "http://www.sat.gob.mx/cfd/4"


class RecursosFaltantes(RuntimeError):
    pass


def _local(url: str) -> Path:
    p = urlparse(url)
    return DIR_RECURSOS / p.netloc / p.path.lstrip("/")


class _ResolvedorSat(etree.Resolver):
    def resolve(self, url, pubid, context):
        if url and url.startswith(("http://www.sat.gob.mx/", "https://www.sat.gob.mx/")):
            ruta = _local(url)
            if not ruta.exists():
                raise RecursosFaltantes(f"Falta {ruta}; corre descargar_recursos_sat.py")
            return self.resolve_filename(str(ruta), context)
        return None


def _parser() -> etree.XMLParser:
    p = etree.XMLParser(no_network=True, resolve_entities=False)
    p.resolvers.add(_ResolvedorSat())
    return p


def _parse_url(url: str) -> etree._ElementTree:
    ruta = _local(url)
    if not ruta.exists():
        raise RecursosFaltantes(f"Falta {ruta}; corre descargar_recursos_sat.py")
    # base_url = la URL original, para que las inclusiones relativas también se resuelvan.
    return etree.parse(str(ruta), _parser(), base_url=url)


@lru_cache(maxsize=1)
def _xslt_cadena() -> etree.XSLT:
    acceso = etree.XSLTAccessControl(read_network=False, write_file=False, create_dir=False, write_network=False)
    return etree.XSLT(_parse_url(URL_XSLT_40), access_control=acceso)


@lru_cache(maxsize=1)
def _esquema() -> etree.XMLSchema:
    return etree.XMLSchema(_parse_url(URL_XSD_40))


def recursos_disponibles() -> bool:
    return _local(URL_XSLT_40).exists() and _local(URL_XSD_40).exists()


def _arbol(xml: bytes) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False)))


def cadena_original(xml: bytes) -> str:
    """Cadena original del CFDI 4.0 con la XSLT oficial del SAT."""
    return str(_xslt_cadena()(_arbol(xml)))


def errores_xsd(xml: bytes) -> list[str]:
    """Errores de validación contra cfdv40.xsd oficial (lista vacía = válido)."""
    esquema = _esquema()
    if esquema.validate(_arbol(xml)):
        return []
    return [f"línea {e.line}: {e.message}" for e in esquema.error_log]


def verificar_sello(xml: bytes) -> None:
    """Verifica el sello como lo describe la matriz de errores del SAT.

    Toma el certificado del atributo ``Certificado``, comprueba que
    ``NoCertificado`` corresponde a su serial, regenera la cadena original con
    la XSLT oficial y verifica RSASSA-PKCS1-v1_5/SHA-256. Lanza ``ValueError``
    si algo no cuadra.
    """
    raiz = etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False))
    if raiz.tag != f"{{{NS_CFDI}}}Comprobante":
        raise ValueError("No es un CFDI 4.0")
    cert = x509.load_der_x509_certificate(base64.b64decode(raiz.get("Certificado", "")))
    if raiz.get("NoCertificado") != numero_certificado(cert):
        raise ValueError("NoCertificado no corresponde al certificado incluido")
    firma = base64.b64decode(raiz.get("Sello", ""))
    try:
        cert.public_key().verify(firma, cadena_original(xml).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise ValueError("El sello no verifica con el certificado") from e
