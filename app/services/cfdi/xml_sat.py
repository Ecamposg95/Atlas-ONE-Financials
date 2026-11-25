"""Cadena original y validación XSD con los recursos OFICIALES del SAT, sin red.

Los XSD y la XSLT de CFDI 4.0 están vendorizados en ``recursos_sat/`` (los
escribe ``scripts/sat_recursos/actualizar.py``; ``manifest.json`` guarda URL y
sha256 de cada uno). Un resolvedor de lxml sirve las URL
``http://www.sat.gob.mx/...`` de las inclusiones desde esos archivos, y la
lectura revisa el sha256 contra el manifiesto: un archivo alterado no se usa.

Por qué la XSLT oficial con lxml y no ``satcfdi``: la cadena original es lo que
se firma, así que debe salir de la hoja que publica el SAT y no de una copia
de terceros. lxml (libxslt, XSLT 1.0 en modo compatible aunque la hoja diga
2.0) produce la misma cadena que ``satcfdi``; el spike ``spikes/cfdi_sellado``
lo comprobó con sellos idénticos. Aquí no se canonicaliza nada: el hallazgo de
C14N roto de lxml 6.1.3 / libxml2 2.14.6 sólo afecta la firma XML-DSig de la
cancelación, que no vive en este módulo.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from functools import cache
from pathlib import Path

from lxml import etree

DIR_RECURSOS = Path(__file__).resolve().parent / "recursos_sat"
URL_XSD_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
URL_XSLT_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt"
_SAT = ("http://www.sat.gob.mx/", "https://www.sat.gob.mx/")

_lock = threading.Lock()


class RecursoSatInvalido(RuntimeError):
    """Falta un XSD/XSLT vendorizado o no coincide con su sha256."""


@cache
def _manifiesto() -> dict:
    return json.loads((DIR_RECURSOS / "manifest.json").read_text(encoding="utf-8"))


def _normaliza(url: str) -> str:
    return "http://" + url.split("://", 1)[1] if url.startswith("https://") else url


@cache
def _bytes(url: str) -> bytes:
    entrada = _manifiesto()["archivos"].get(_normaliza(url))
    if entrada is None:
        raise RecursoSatInvalido(f"{url} no está vendorizado; corre scripts/sat_recursos/actualizar.py")
    crudo = (DIR_RECURSOS / entrada["archivo"]).read_bytes()
    if entrada["archivo"].endswith(".gz"):
        crudo = gzip.decompress(crudo)
    if hashlib.sha256(crudo).hexdigest() != entrada["sha256"]:
        raise RecursoSatInvalido(f"{entrada['archivo']} no coincide con manifest.json")
    return crudo


class _Resolvedor(etree.Resolver):
    def resolve(self, url, pubid, context):
        if url and url.startswith(_SAT):
            return self.resolve_string(_bytes(url), context, base_url=_normaliza(url))
        return None


def _parser() -> etree.XMLParser:
    parser = etree.XMLParser(no_network=True, resolve_entities=False)
    parser.resolvers.add(_Resolvedor())
    return parser


def _parse_url(url: str) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(_bytes(url), _parser(), base_url=url))


_xslt: etree.XSLT | None = None
_esquema: etree.XMLSchema | None = None


def _transformador() -> etree.XSLT:
    global _xslt
    with _lock:
        if _xslt is None:
            acceso = etree.XSLTAccessControl(
                read_file=False, write_file=False, create_dir=False, read_network=False, write_network=False
            )
            _xslt = etree.XSLT(_parse_url(URL_XSLT_40), access_control=acceso)
        return _xslt


def _schema() -> etree.XMLSchema:
    global _esquema
    with _lock:
        if _esquema is None:
            _esquema = etree.XMLSchema(_parse_url(URL_XSD_40))
        return _esquema


def _arbol(xml: bytes) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False)))


def cadena_original(xml: bytes) -> str:
    """Cadena original del CFDI 4.0 con la XSLT oficial del SAT."""
    arbol = _arbol(xml)
    transformador = _transformador()
    with _lock:  # un objeto XSLT de lxml no debe usarse desde dos hilos a la vez
        return str(transformador(arbol))


def errores_xsd(xml: bytes) -> list[str]:
    """Errores contra el ``cfdv40.xsd`` oficial; lista vacía si es válido."""
    arbol = _arbol(xml)
    esquema = _schema()
    with _lock:
        if esquema.validate(arbol):
            return []
        return [f"línea {e.line}: {e.message}" for e in esquema.error_log]


def faltantes() -> list[dict]:
    """XSLT de complementos que el SAT no sirvió y se sustituyeron por una hoja vacía."""
    return list(_manifiesto().get("faltantes", []))
