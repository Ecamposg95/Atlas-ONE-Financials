"""Vendoriza el XSD y la XSLT oficiales de CFDI 4.0 en ``app/services/cfdi/recursos_sat/``.

    python3 -I scripts/sat_recursos/actualizar.py

Baja ``cfdv40.xsd`` y ``cadenaoriginal_4_0.xslt`` del SAT con todo lo que
incluyen o importan, los guarda con la misma ruta que tienen en
www.sat.gob.mx (para que el resolvedor sin red de ``xml_sat.py`` los sirva) y
escribe ``manifest.json`` con URL, fecha de descarga y sha256 de cada archivo.
Lo que pesa más de 1 MB (``catCFDI.xsd``) se guarda en gzip determinista.

El propio SAT tiene inclusiones rotas (``divisas.xslt`` da 404). Sólo se
toleran en XSLT de complementos: se sustituyen por una hoja vacía y quedan en
``faltantes`` del manifiesto. Una XSD o la XSLT principal que falle aborta.

Los archivos bajados son datos no confiables: se parsean sin red ni entidades
y nunca se ejecutan fuera de lxml.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
DESTINO = REPO / "app" / "services" / "cfdi" / "recursos_sat"

RAICES = (
    "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd",
    "http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt",
)
LIMITE_SIN_GZIP = 1024 * 1024
XSL_NS = "http://www.w3.org/1999/XSL/Transform"
XS_NS = "http://www.w3.org/2001/XMLSchema"
HOJA_VACIA = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"/>\n'
)


def _bajar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "recursos-sat/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - URL del SAT
        return resp.read()


def _relativa(url: str) -> str:
    p = urlparse(url)
    return f"{p.netloc}{p.path}"


def _espejear(url: str, archivos: dict[str, dict], faltantes: list[dict]) -> None:
    if url in archivos:
        return
    try:
        datos = _bajar(url)
        estado = "ok"
    except urllib.error.HTTPError as exc:
        es_complemento = url.endswith(".xslt") and "utilerias" not in url and "cadenaoriginal" not in url
        if not es_complemento:
            raise
        print(f"AVISO: {url} respondió {exc.code}; se sustituye por una hoja vacía", file=sys.stderr)
        faltantes.append({"url": url, "http": exc.code})
        datos, estado = HOJA_VACIA, "sustituido_por_hoja_vacia"
    archivos[url] = {"datos": datos, "estado": estado}
    arbol = etree.fromstring(datos, etree.XMLParser(resolve_entities=False, no_network=True))
    refs = arbol.xpath(
        "//xsl:include/@href | //xsl:import/@href | //xs:import/@schemaLocation | //xs:include/@schemaLocation",
        namespaces={"xsl": XSL_NS, "xs": XS_NS},
    )
    for ref in refs:
        _espejear(urljoin(url, ref), archivos, faltantes)


def main() -> int:
    archivos: dict[str, dict] = {}
    faltantes: list[dict] = []
    for raiz in RAICES:
        _espejear(raiz, archivos, faltantes)

    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    manifiesto = {
        "descripcion": "XSD y XSLT oficiales de CFDI 4.0 del SAT. Generado por scripts/sat_recursos/actualizar.py; no editar a mano.",
        "fecha_descarga": dt.date.today().isoformat(),
        "archivos": {},
        "faltantes": faltantes,
    }
    for url in sorted(archivos):
        datos = archivos[url]["datos"]
        relativa = _relativa(url)
        guardado = relativa
        contenido = datos
        if len(datos) > LIMITE_SIN_GZIP:
            guardado = relativa + ".gz"
            contenido = gzip.compress(datos, compresslevel=9, mtime=0)
        destino = DESTINO / guardado
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        manifiesto["archivos"][url] = {
            "archivo": guardado,
            "sha256": hashlib.sha256(datos).hexdigest(),
            "bytes": len(datos),
            "estado": archivos[url]["estado"],
        }
    (DESTINO / "manifest.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"{len(archivos)} archivos en {DESTINO.relative_to(REPO)} ({len(faltantes)} sustituidos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
