"""Convierte los originales del SAT a los datos versionados del repo.

    pip install -r scripts/sat_catalogos/requirements.txt   # xlrd, sólo para convertir
    python3 -I scripts/sat_catalogos/convertir.py /ruta/de/originales

Lee los .xls/.xsd/.pdf que dejó ``descargar.py`` (y su ``descargas.json``) y
escribe ``app/services/cfdi/catalogos/data/``. Es determinista: con los mismos
originales produce los mismos bytes (gzip con mtime 0), así que un ``git diff``
muestra exactamente qué cambió el SAT.

Normalización:
- Claves: el SAT guarda claves numéricas como número ("1.0" por "01"). Se
  rellenan con ceros a la izquierda usando las enumeraciones del XSD oficial del
  catálogo, y se reporta toda clave que no cuadre con el XSD.
- Fechas: los seriales de Excel pasan a ISO (AAAA-MM-DD). Fin de vigencia vacío = null.
- Todo valor se guarda como texto (o null); nada de flotantes en los datos.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from decimal import Decimal
from pathlib import Path

import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fuentes import (  # noqa: E402
    ARCHIVOS,
    CATALOGOS,
    COMPRIMIDOS,
    MATRICES,
    MOTIVOS_CANCELACION,
    MOTIVOS_CANCELACION_ARCHIVO,
    OMITIDOS,
)

REPO = Path(__file__).resolve().parents[2]
# Catálogos cuya clave sólo es única junto con otra columna.
LLAVES = {"c_Municipio": ["c_estado", "clave"], "c_Localidad": ["c_estado", "clave"]}
DATA = REPO / "app" / "services" / "cfdi" / "catalogos" / "data"
XS = "{http://www.w3.org/2001/XMLSchema}"


# ---------------------------------------------------------------- utilidades


def slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def numero_a_texto(valor: float) -> str:
    if float(valor).is_integer():
        return str(int(valor))
    return format(Decimal(repr(valor)).normalize(), "f")


def fecha_excel(valor, datemode: int) -> str | None:
    if valor in ("", None) or valor == 0:
        return None
    if isinstance(valor, float):
        return xlrd.xldate_as_datetime(valor, datemode).date().isoformat()
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    return texto or None


def texto(valor) -> str | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, float):
        return numero_a_texto(valor)
    limpio = re.sub(r"\s+", " ", str(valor)).strip()
    return limpio or None


def enumeraciones(xsd: Path) -> dict[str, list[str]]:
    resultado: dict[str, list[str]] = {}
    for tipo in ET.parse(xsd).getroot().iter(f"{XS}simpleType"):
        valores = [e.get("value") for e in tipo.iter(f"{XS}enumeration")]
        if valores:
            resultado[tipo.get("name")] = valores
    return resultado


def escribir_json(ruta: Path, documento: dict, comprimir: bool) -> bytes:
    """JSON legible: metadatos indentados y un registro por línea (diffs limpios)."""
    registros = documento.pop("registros")
    cabeza = json.dumps(documento, ensure_ascii=False, indent=2)
    lineas = ",\n".join("    " + json.dumps(r, ensure_ascii=False) for r in registros)
    contenido = cabeza[:-2] + ',\n  "registros": [\n' + lineas + "\n  ]\n}\n"
    documento["registros"] = registros
    datos = contenido.encode("utf-8")
    if comprimir:
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as gz:
            gz.write(datos)
        datos = buffer.getvalue()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return datos


# ---------------------------------------------------------------- catálogos

_META = {
    "version cfdi": "version_cfdi",
    "version catalogo": "version",
    "version": "version",
    "revision catalogo": "revision",
    "revision": "revision",
    "fecha publicacion de catalogo": "fecha_publicacion",
    "fecha de publicacion": "fecha_publicacion",
    "fecha inicio de vigencia del catalogo": "vigencia_inicio",
    "fecha inicio de vigencia": "vigencia_inicio",
    "fecha fin de vigencia del catalogo": "vigencia_fin",
    "fecha fin de vigencia": "vigencia_fin",
}

_RENOMBRES = {
    "descripcion": "descripcion",
    "fisica": "persona_fisica",
    "moral": "persona_moral",
    "fechainiciovigencia": "vigencia_inicio",
    "fechafinvigencia": "vigencia_fin",
}


def columna(nombre: str) -> str:
    s = slug(nombre)
    if s in _RENOMBRES:
        return _RENOMBRES[s]
    if "vigencia" in s and "inicio" in s and "horario" not in s:
        return "vigencia_inicio"
    if "vigencia" in s and "fin" in s and "horario" not in s:
        return "vigencia_fin"
    return s


def es_encabezado(celda) -> bool:
    s = str(celda).strip().lower()
    return s.startswith("c_") or s == "rango o fijo"


def leer_hoja(sh, datemode: int) -> tuple[dict, str, list[str], list[list]]:
    """Regresa (metadatos del SAT, título, columnas, filas crudas) de una hoja de catálogo."""
    fila = lambda r: [sh.cell_value(r, c) for c in range(sh.ncols)]  # noqa: E731
    titulo = next((texto(fila(r)[0]) for r in range(4) if texto(fila(r)[0])), "") or ""

    # Siempre las mismas llaves; None si la hoja no trae el dato (las de nómina traen menos).
    meta: dict = dict.fromkeys(
        ["version_cfdi", "version", "revision", "fecha_publicacion", "vigencia_inicio", "vigencia_fin"]
    )
    r_meta = next(r for r in range(8) if any("versi" in str(v).lower() for v in fila(r)))
    for etiqueta, valor in zip(fila(r_meta), fila(r_meta + 1), strict=True):
        clave = _META.get(slug(etiqueta).replace("_", " "))
        if not clave:
            continue
        if clave in ("fecha_publicacion", "vigencia_inicio", "vigencia_fin"):
            meta[clave] = fecha_excel(valor, datemode)
        elif clave == "version_cfdi" and isinstance(valor, float):
            meta[clave] = f"{valor:.1f}"
        else:
            meta[clave] = texto(valor)

    r_enc = next(r for r in range(r_meta + 2, 12) if es_encabezado(fila(r)[0]))
    encabezado = fila(r_enc)
    padre = fila(r_enc - 1) if r_enc - 1 > r_meta + 1 else [""] * sh.ncols
    sub = fila(r_enc + 1)
    tiene_sub = not str(sub[0]).strip() and any(str(v).strip() for v in sub)
    nombres = []
    for c in range(sh.ncols):
        if tiene_sub and str(sub[c]).strip():
            nombre = sub[c]
        elif str(encabezado[c]).strip():
            nombre = encabezado[c]
        elif str(padre[c]).strip():
            nombre = padre[c]
        else:
            nombre = ""
        nombres.append(columna(nombre) if nombre else "")
    nombres[0] = "clave"
    vistos: dict[str, int] = {}
    for i, n in enumerate(nombres):
        if not n:
            continue
        vistos[n] = vistos.get(n, 0) + 1
        if vistos[n] > 1:
            nombres[i] = f"{n}_{vistos[n]}"
    inicio = r_enc + (2 if tiene_sub else 1)
    # Filas con clave y al menos un dato más (descarta notas como "Continúa en c_CodigoPostal_2").
    filas = [f for f in map(fila, range(inicio, sh.nrows)) if str(f[0]).strip() and any(str(v).strip() for v in f[1:])]
    return meta, titulo, nombres, filas


def normalizar_clave(valor, enums: set[str] | None, sin_ceros: dict[str, str]) -> str:
    clave = texto(valor) or ""
    if enums is None or clave in enums:
        return clave
    if (clave.lstrip("0") or "0") in sin_ceros:
        return sin_ceros[clave.lstrip("0") or "0"]
    return sin_ceros.get(clave.upper(), clave)  # p. ej. "Dx" en la hoja, "DX" en el XSD


def convertir_catalogo(origen: Path, grupo, nombre, archivo, hojas, xsd, fuentes, avisos) -> dict:
    wb = xlrd.open_workbook(origen / archivo, on_demand=True)
    lista = enumeraciones(origen / xsd).get(nombre) if xsd else None
    enums = set(lista) if lista is not None else None
    sin_ceros = {e.lstrip("0") or "0": e for e in (enums or [])}
    sin_ceros.update({e.upper(): e for e in (enums or []) if e.upper() not in enums})
    meta = titulo = columnas = None
    filas: list[list] = []
    for hoja in hojas:
        m, t, c, f = leer_hoja(wb.sheet_by_name(hoja), wb.datemode)
        if columnas is not None and c != columnas:
            raise SystemExit(f"{nombre}: las hojas {hojas} no tienen las mismas columnas")
        meta, titulo, columnas = meta or m, titulo or t, c
        filas += f
        wb.unload_sheet(hoja)

    usar = [i for i, c in enumerate(columnas) if c]
    columnas_finales = [columnas[i] for i in usar]
    fechas = {i for i in usar if columnas[i].startswith("vigencia_")}
    registros = []
    for f in filas:
        reg = []
        for i in usar:
            if i == 0 and nombre != "c_TasaOCuota":
                reg.append(normalizar_clave(f[i], enums, sin_ceros))
            elif i in fechas:
                reg.append(fecha_excel(f[i], wb.datemode))
            else:
                reg.append(texto(f[i]))
        registros.append(reg)

    llave = LLAVES.get(nombre, ["clave"])
    solo_xsd: list[str] = []
    if nombre == "c_TasaOCuota":
        # No tiene clave propia: la primera columna dice si el valor es Fijo o Rango.
        columnas_finales[0] = "rango_o_fijo"
    else:
        indices = [columnas_finales.index(c) for c in llave]
        conteo = Counter(tuple(r[i] for i in indices) for r in registros)
        repetidas = [k for k, n in conteo.items() if n > 1]
        if repetidas:
            raise SystemExit(f"{nombre}: llave {llave} repetida en el original {repetidas[:5]}")
        claves = {r[0] for r in registros}
        if enums is not None:
            fuera = sorted(claves - enums)
            if fuera:
                raise SystemExit(f"{nombre}: claves que no están en {xsd}: {fuera[:10]}")
            solo_xsd = sorted(enums - claves)
            if solo_xsd:
                avisos.append(
                    f"{nombre}: {len(solo_xsd)} claves del XSD no vienen en la hoja (sin descripción ni "
                    f"vigencia; no se cargan): {solo_xsd[:8]}"
                )

    return {
        "catalogo": nombre,
        "grupo": grupo,
        "titulo": titulo,
        "sat": meta,
        "origen": {**fuentes[archivo], "hojas": hojas},
        "llave": llave if nombre != "c_TasaOCuota" else [],
        "claves_solo_en_xsd": solo_xsd,
        "columnas": columnas_finales,
        "registros": registros,
    }


# ---------------------------------------------------------------- matrices


def convertir_matriz(origen: Path, nombre: str, archivo: str, fuentes) -> dict:
    wb = xlrd.open_workbook(origen / archivo)
    sh = wb.sheet_by_index(0)
    titulo = texto(sh.cell_value(0, 0))
    r_enc = next(r for r in range(6) if any(slug(v).startswith("codigo") for v in sh.row_values(r)))
    columnas = [columna(v) if str(v).strip() else "" for v in sh.row_values(r_enc)]
    columnas = [
        {"num": "num", "codigo_error": "codigo", "codigo_de_error": "codigo", "descripcion_de_codigo_de_error": "descripcion",
         "descripcion_del_error": "descripcion", "regla_de_validacion": "validacion"}.get(c, c)
        for c in columnas
    ]
    i_codigo = columnas.index("codigo")
    usar = [i for i, c in enumerate(columnas) if c]
    errores, seccion = [], None
    for r in range(r_enc + 1, sh.nrows):
        fila = sh.row_values(r)
        codigo = texto(fila[i_codigo])
        if not codigo:
            otros = [texto(v) for v in fila if texto(v)]
            if len(otros) == 1:
                seccion = otros[0]
            continue
        registro = {columnas[i]: texto(fila[i]) for i in usar}
        registro["seccion"] = seccion
        errores.append(registro)
    return {
        "matriz": nombre,
        "titulo": titulo,
        "origen": {**fuentes[archivo], "hoja": sh.name},
        "columnas": list(errores[0].keys()),
        "registros": [list(e.values()) for e in errores],
    }


# ---------------------------------------------------------------- cancelación


def convertir_motivos(origen: Path, fuentes, avisos) -> dict:
    pdf = origen / MOTIVOS_CANCELACION_ARCHIVO
    if shutil.which("pdftotext"):
        salida = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, check=True).stdout
        cuerpo = re.sub(r"\s+", " ", salida.decode("utf-8", "replace"))
        for clave, descripcion, _ in MOTIVOS_CANCELACION:
            if f"Clave {clave}" not in cuerpo or descripcion not in cuerpo:
                raise SystemExit(f"motivo {clave} '{descripcion}' no aparece en {pdf.name}")
    else:
        avisos.append("pdftotext no está instalado: no se cotejaron los motivos de cancelación con el PDF")
    return {
        "catalogo": "c_MotivoCancelacion",
        "grupo": "cancelacion",
        "titulo": "Motivos de cancelación de CFDI (art. 29-A CFF)",
        "sat": {"version": None, "revision": None, "fecha_publicacion": None, "vigencia_inicio": "2022-01-01",
                "vigencia_fin": None},
        "origen": {**fuentes[MOTIVOS_CANCELACION_ARCHIVO], "hojas": [],
                   "nota": "Transcrito del PDF y cotejado textualmente por convertir.py"},
        "llave": ["clave"],
        "claves_solo_en_xsd": [],
        "columnas": ["clave", "descripcion", "vigencia_inicio", "vigencia_fin"],
        "registros": [[c, d, i, None] for c, d, i in MOTIVOS_CANCELACION],
    }


# ---------------------------------------------------------------- principal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("origen", type=Path, help="directorio con los originales y descargas.json")
    args = parser.parse_args()
    origen: Path = args.origen.resolve()

    descargas = {d["archivo"]: d for d in json.loads((origen / "descargas.json").read_text())}
    fuentes = {}
    for archivo, info in ARCHIVOS.items():
        d = descargas[archivo]
        sha = hashlib.sha256((origen / archivo).read_bytes()).hexdigest()
        if sha != d["sha256"]:
            raise SystemExit(f"{archivo}: el sha256 no coincide con descargas.json")
        fuentes[archivo] = {
            "archivo": archivo,
            "url": d["url"],
            "version_archivo": info["version_archivo"] or None,
            "fecha_descarga": d["fecha_descarga"],
            "sha256": sha,
        }

    if DATA.exists():
        shutil.rmtree(DATA)
    avisos: list[str] = []
    manifiesto: dict = {
        "descripcion": "Catálogos del SAT para CFDI 4.0, Nómina 1.2, Pagos 2.0 y cancelación. "
        "Generado por scripts/sat_catalogos/convertir.py; no editar a mano.",
        "fuentes": fuentes,
        "omitidos": OMITIDOS,
        "catalogos": {},
        "matrices": {},
    }

    documentos = [convertir_catalogo(origen, *c, fuentes, avisos) for c in CATALOGOS]
    documentos.append(convertir_motivos(origen, fuentes, avisos))
    for doc in documentos:
        nombre = doc["catalogo"]
        if nombre in manifiesto["catalogos"]:
            raise SystemExit(f"catálogo duplicado: {nombre}")
        comprimir = nombre in COMPRIMIDOS
        relativa = f"{doc['grupo']}/{nombre}.json" + (".gz" if comprimir else "")
        datos = escribir_json(DATA / relativa, doc, comprimir)
        manifiesto["catalogos"][nombre] = {
            "archivo": relativa,
            "grupo": doc["grupo"],
            "titulo": doc["titulo"],
            "registros": len(doc["registros"]),
            "llave": doc["llave"],
            "claves_solo_en_xsd": len(doc["claves_solo_en_xsd"]),
            "sat": doc["sat"],
            "fuente": doc["origen"]["archivo"],
            "sha256": hashlib.sha256(datos).hexdigest(),
        }
        print(f"{relativa:45} {len(doc['registros']):>7} registros {len(datos):>10,} bytes")

    for nombre, archivo in MATRICES:
        doc = convertir_matriz(origen, nombre, archivo, fuentes)
        relativa = f"matrices/{nombre}.json"
        datos = escribir_json(DATA / relativa, doc, False)
        manifiesto["matrices"][nombre] = {
            "archivo": relativa,
            "titulo": doc["titulo"],
            "registros": len(doc["registros"]),
            "fuente": archivo,
            "sha256": hashlib.sha256(datos).hexdigest(),
        }
        print(f"{relativa:45} {len(doc['registros']):>7} errores   {len(datos):>10,} bytes")

    manifiesto["avisos_conversion"] = avisos
    (DATA / "manifest.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n")
    for aviso in avisos:
        print("AVISO:", aviso)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
