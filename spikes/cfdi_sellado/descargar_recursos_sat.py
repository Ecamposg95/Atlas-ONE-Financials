"""Descarga los recursos públicos del SAT que usa el spike.

1. XSD de CFDI 4.0 (cfdv40.xsd y los esquemas que importa) y la XSLT oficial de
   cadena original 4.0 con todas sus inclusiones. Se guardan en
   ``recursos_sat/`` (ignorada por git) con la misma ruta que tienen en
   www.sat.gob.mx, para que un resolvedor de lxml las sirva sin red.
2. El zip de certificados de PRUEBA del SAT ("Certificados_de_Prueba.zip",
   enlazado desde la página de Certificado de Sello Digital del SAT). Se guarda
   FUERA del repo (por defecto ``~/.cache/atlas-financials-spike-csd``) porque
   trae llaves privadas, aunque sean de prueba.

Uso:  .venv/bin/python descargar_recursos_sat.py

Sólo usa la biblioteca estándar. No contacta a ningún proveedor de timbrado.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

from lxml import etree

AQUI = Path(__file__).resolve().parent
DIR_RECURSOS = AQUI / "recursos_sat"
DIR_CSD = Path(os.environ.get("SPIKE_CSD_DIR", Path.home() / ".cache" / "atlas-financials-spike-csd"))

XSLT_CADENA_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt"
XSD_CFDI_40 = "http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
ZIP_CSD_PRUEBA = "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Certificados_de_Prueba.zip"
# Huella del zip descargado el 2026-11-25 (archivo fechado 2023-06-23 dentro del zip).
# Si el SAT lo reemplaza la huella cambiará: se avisa, no se aborta.
SHA256_ZIP_CONOCIDO = "23563077528c1fefcf5d57ad5e2eed9fa51956fe821c97a5d4c54f32f2ebeb8a"

XSL_NS = "http://www.w3.org/1999/XSL/Transform"
XS_NS = "http://www.w3.org/2001/XMLSchema"
HOJA_VACIA = b'<?xml version="1.0" encoding="UTF-8"?>\n<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"/>\n'


def ruta_local(url: str) -> Path:
    p = urlparse(url)
    return DIR_RECURSOS / p.netloc / p.path.lstrip("/")


def bajar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "spike-cfdi-sellado/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def espejear(url: str, vistos: set[str]) -> None:
    """Baja ``url`` y, recursivamente, sus xsl:include/xsl:import/xs:import/xs:include."""
    if url in vistos:
        return
    vistos.add(url)
    destino = ruta_local(url)
    if not destino.exists():
        print(f"  bajando {url}")
        try:
            datos = bajar(url)
        except urllib.error.HTTPError as e:
            # El propio SAT tiene inclusiones rotas (p. ej. divisas.xslt da 404).
            # Sólo toleramos XSLT de complementos, que este spike no usa: se
            # sustituyen por una hoja vacía y se anotan en FALTANTES.txt.
            es_complemento = url.endswith(".xslt") and "utilerias" not in url and "cadenaoriginal" not in url
            if not es_complemento:
                raise
            print(f"  AVISO: {url} respondió {e.code}; se usa una hoja vacía (complemento no usado)")
            datos = HOJA_VACIA
            with open(DIR_RECURSOS / "FALTANTES.txt", "a", encoding="utf-8") as f:
                f.write(f"{url}\t{e.code}\n")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    arbol = etree.parse(str(destino), etree.XMLParser(resolve_entities=False, no_network=True))
    refs = arbol.xpath(
        "//xsl:include/@href | //xsl:import/@href | //xs:import/@schemaLocation | //xs:include/@schemaLocation",
        namespaces={"xsl": XSL_NS, "xs": XS_NS},
    )
    for ref in refs:
        espejear(urljoin(url, ref), vistos)


def bajar_csd_prueba() -> None:
    DIR_CSD.mkdir(parents=True, exist_ok=True)
    zip_path = DIR_CSD / "Certificados_de_Prueba.zip"
    if not zip_path.exists():
        print(f"  bajando {ZIP_CSD_PRUEBA}")
        zip_path.write_bytes(bajar(ZIP_CSD_PRUEBA))
    huella = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if huella != SHA256_ZIP_CONOCIDO:
        print(f"  AVISO: la huella del zip cambió ({huella}); revisar su contenido.")
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            nombre = info.filename
            # Sólo el CSD (no la e.firma) de la persona moral EKU9003173C9.
            if "EKU9003173C9" in nombre and "/CSD_" in nombre and nombre.endswith((".cer", ".key")):
                destino = DIR_CSD / Path(nombre).name
                destino.write_bytes(z.read(info))
                print(f"  extraído {destino}")


def main() -> int:
    print(f"Recursos del SAT en {DIR_RECURSOS}")
    vistos: set[str] = set()
    espejear(XSD_CFDI_40, vistos)
    espejear(XSLT_CADENA_40, vistos)
    print(f"  {len(vistos)} archivos XSD/XSLT listos")
    print(f"CSD de prueba en {DIR_CSD} (fuera del repo)")
    bajar_csd_prueba()
    return 0


if __name__ == "__main__":
    sys.exit(main())
