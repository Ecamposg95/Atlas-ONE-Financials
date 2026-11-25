"""Cargador de solo lectura de los catálogos del SAT versionados en ``data/``.

Los datos los genera ``scripts/sat_catalogos/convertir.py`` a partir de los
originales del SAT; aquí sólo se leen. Sin dependencias fuera de la biblioteca
estándar. Cada catálogo se carga la primera vez que se pide y queda en memoria.

La vigencia es por registro: una clave vale en ``fecha`` si
``vigencia_inicio <= fecha`` y (no tiene fin o ``fecha <= vigencia_fin``).
La fecha que importa es la de emisión del comprobante, no la de hoy, por eso
las consultas de vigencia la piden explícitamente.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import cache
from pathlib import Path
from types import MappingProxyType

DATA = Path(__file__).resolve().parent / "data"

_lock = threading.Lock()


class EstadoClave(str, Enum):
    VIGENTE = "vigente"
    NO_VIGENTE = "no_vigente"
    INEXISTENTE = "inexistente"


class CatalogoNoEncontrado(KeyError):
    """Se pidió un catálogo que no está en el manifiesto."""


class ClaveNoValida(ValueError):
    """La clave no existe en el catálogo o no está vigente en la fecha pedida."""

    def __init__(self, catalogo: str, clave: str, estado: EstadoClave, fecha: dt.date):
        self.catalogo, self.clave, self.estado, self.fecha = catalogo, clave, estado, fecha
        if estado is EstadoClave.INEXISTENTE:
            mensaje = f"La clave {clave!r} no existe en el catálogo {catalogo} del SAT."
        else:
            mensaje = f"La clave {clave!r} del catálogo {catalogo} no está vigente el {fecha.isoformat()}."
        super().__init__(mensaje)


def _fecha(valor: str | None) -> dt.date | None:
    return dt.date.fromisoformat(valor) if valor else None


def _solo_fecha(fecha: dt.date | dt.datetime) -> dt.date:
    return fecha.date() if isinstance(fecha, dt.datetime) else fecha


@dataclass(frozen=True)
class Registro:
    """Un renglón del catálogo. ``datos`` trae todas las columnas tal como vienen del SAT (texto o None)."""

    clave: str
    descripcion: str | None
    vigencia_inicio: dt.date | None
    vigencia_fin: dt.date | None
    datos: Mapping[str, str | None] = field(repr=False)

    def vigente_en(self, fecha: dt.date | dt.datetime) -> bool:
        dia = _solo_fecha(fecha)
        if self.vigencia_inicio and dia < self.vigencia_inicio:
            return False
        return not (self.vigencia_fin and dia > self.vigencia_fin)

    def __getitem__(self, columna: str) -> str | None:
        return self.datos[columna]

    def get(self, columna: str, default: str | None = None) -> str | None:
        return self.datos.get(columna, default)


class Catalogo:
    """Catálogo del SAT en memoria, indexado por su llave."""

    def __init__(self, documento: dict):
        self.nombre: str = documento["catalogo"]
        self.grupo: str = documento["grupo"]
        self.titulo: str = documento["titulo"]
        self.sat: Mapping = MappingProxyType(documento["sat"])
        self.origen: Mapping = MappingProxyType(documento["origen"])
        self.columnas: tuple[str, ...] = tuple(documento["columnas"])
        self.llave: tuple[str, ...] = tuple(documento["llave"])
        self.claves_solo_en_xsd: frozenset[str] = frozenset(documento.get("claves_solo_en_xsd", []))
        self._registros: list[Registro] = []
        self._indice: dict[str | tuple[str, ...], Registro] = {}
        for fila in documento["registros"]:
            datos = MappingProxyType(dict(zip(self.columnas, fila, strict=True)))
            registro = Registro(
                clave=datos.get("clave") or "",
                descripcion=datos.get("descripcion"),
                vigencia_inicio=_fecha(datos.get("vigencia_inicio")),
                vigencia_fin=_fecha(datos.get("vigencia_fin")),
                datos=datos,
            )
            self._registros.append(registro)
            if self.llave:
                self._indice[self._llave_de(datos)] = registro

    def _llave_de(self, datos: Mapping) -> str | tuple[str, ...]:
        if len(self.llave) == 1:
            return datos[self.llave[0]]
        return tuple(datos[c] for c in self.llave)

    def __len__(self) -> int:
        return len(self._registros)

    def __iter__(self) -> Iterator[Registro]:
        return iter(self._registros)

    def __contains__(self, clave: object) -> bool:
        return clave in self._indice

    def __repr__(self) -> str:
        return f"<Catalogo {self.nombre} v{self.sat.get('version')} rev{self.sat.get('revision')}: {len(self)}>"

    def obtener(self, clave: str | tuple[str, ...]) -> Registro | None:
        """Registro por llave, sin importar vigencia. En catálogos de llave compuesta
        (``c_Municipio``, ``c_Localidad``) la llave es una tupla ``(c_estado, clave)``."""
        return self._indice.get(clave)

    def estado(self, clave: str | tuple[str, ...], fecha: dt.date | dt.datetime) -> EstadoClave:
        registro = self.obtener(clave)
        if registro is None:
            return EstadoClave.INEXISTENTE
        return EstadoClave.VIGENTE if registro.vigente_en(fecha) else EstadoClave.NO_VIGENTE

    def es_valida(self, clave: str | tuple[str, ...], fecha: dt.date | dt.datetime) -> bool:
        return self.estado(clave, fecha) is EstadoClave.VIGENTE

    def validar(self, clave: str | tuple[str, ...], fecha: dt.date | dt.datetime) -> Registro:
        """Regresa el registro si la clave existe y está vigente; si no, lanza ``ClaveNoValida``."""
        estado = self.estado(clave, fecha)
        if estado is not EstadoClave.VIGENTE:
            texto = "|".join(clave) if isinstance(clave, tuple) else clave
            raise ClaveNoValida(self.nombre, texto, estado, _solo_fecha(fecha))
        return self._indice[clave]

    def vigentes(self, fecha: dt.date | dt.datetime) -> list[Registro]:
        return [r for r in self._registros if r.vigente_en(fecha)]


@dataclass(frozen=True)
class ErrorSat:
    """Un renglón de una matriz de errores del SAT."""

    matriz: str
    codigo: str
    descripcion: str | None
    validacion: str | None
    elemento: str | None
    atributo: str | None
    seccion: str | None
    aclaraciones: str | None


# ---------------------------------------------------------------- lectura de archivos


def _leer(relativa: str, sha256: str) -> dict:
    ruta = DATA / relativa
    crudo = ruta.read_bytes()
    if hashlib.sha256(crudo).hexdigest() != sha256:
        raise RuntimeError(f"{relativa} no coincide con manifest.json: regenera con scripts/sat_catalogos/convertir.py")
    if relativa.endswith(".gz"):
        crudo = gzip.decompress(crudo)
    return json.loads(crudo.decode("utf-8"))


@cache
def manifiesto() -> Mapping:
    """Índice de catálogos y matrices con versión del SAT, fuente, fecha de descarga y sha256."""
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def catalogos_disponibles() -> list[str]:
    return sorted(manifiesto()["catalogos"])


_catalogos: dict[str, Catalogo] = {}


def catalogo(nombre: str) -> Catalogo:
    """Catálogo por nombre del SAT, p. ej. ``catalogo("c_FormaPago")``."""
    if nombre in _catalogos:
        return _catalogos[nombre]
    entrada = manifiesto()["catalogos"].get(nombre)
    if entrada is None:
        raise CatalogoNoEncontrado(f"No existe el catálogo {nombre!r}. Disponibles: {', '.join(catalogos_disponibles())}")
    with _lock:
        if nombre not in _catalogos:
            _catalogos[nombre] = Catalogo(_leer(entrada["archivo"], entrada["sha256"]))
    return _catalogos[nombre]


@cache
def _errores() -> dict[str, tuple[ErrorSat, ...]]:
    indice: dict[str, list[ErrorSat]] = {}
    for nombre, entrada in manifiesto()["matrices"].items():
        doc = _leer(entrada["archivo"], entrada["sha256"])
        for fila in doc["registros"]:
            datos = dict(zip(doc["columnas"], fila, strict=True))
            error = ErrorSat(
                matriz=nombre,
                codigo=datos["codigo"],
                descripcion=datos.get("descripcion"),
                validacion=datos.get("validacion"),
                elemento=datos.get("elemento"),
                atributo=datos.get("atributo"),
                seccion=datos.get("seccion"),
                aclaraciones=datos.get("aclaraciones"),
            )
            indice.setdefault(error.codigo, []).append(error)
    return {codigo: tuple(errores) for codigo, errores in indice.items()}


def errores_sat(codigo: str) -> tuple[ErrorSat, ...]:
    """Renglones de las matrices de errores (CFDI 4.0, Nómina 1.2, Pagos 2.0) para un código,
    p. ej. ``CFDI40104``, ``NOM1`` o ``CRP20101``. Tupla vacía si no existe."""
    return _errores().get(codigo.strip(), ())


# ---------------------------------------------------------------- reglas que viven en los catálogos


def _si(valor: str | None) -> bool:
    return bool(valor) and valor.strip().lower().startswith("s")


def tasa_o_cuota_valida(
    impuesto: str,
    tipo_factor: str,
    valor: Decimal | str,
    *,
    traslado: bool,
    fecha: dt.date | dt.datetime,
) -> bool:
    """¿El valor de ``TasaOCuota`` está permitido para ese impuesto y factor según ``c_TasaOCuota``?

    ``impuesto`` es la clave de ``c_Impuesto`` (``"001"`` ISR, ``"002"`` IVA, ``"003"`` IEPS);
    ``traslado`` distingue traslado (True) de retención (False). Los renglones "Fijo"
    exigen el valor exacto; los "Rango", que caiga entre mínimo y máximo.
    """
    nombre = catalogo("c_Impuesto").obtener(impuesto)
    if nombre is None or not nombre.descripcion:
        return False
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return False
    for registro in catalogo("c_TasaOCuota"):
        if not (registro["impuesto"] or "").startswith(nombre.descripcion):
            continue  # "IVA Crédito aplicado del 50%" cuenta como IVA (estímulo de la franja fronteriza)
        if registro["factor"] != tipo_factor or not registro.vigente_en(fecha):
            continue
        if not _si(registro["traslado"] if traslado else registro["retencion"]):
            continue
        maximo = Decimal(registro["valor_maximo"] or "0")
        if registro["rango_o_fijo"] == "Fijo" and numero == maximo:
            return True
        if registro["rango_o_fijo"] == "Rango" and Decimal(registro["valor_minimo"] or "0") <= numero <= maximo:
            return True
    return False


def uso_cfdi_permitido(
    uso_cfdi: str,
    regimen_fiscal_receptor: str,
    *,
    persona_moral: bool,
    fecha: dt.date | dt.datetime,
) -> bool:
    """¿El ``UsoCFDI`` corresponde al tipo de persona y al régimen del receptor según ``c_UsoCFDI``?"""
    registro = catalogo("c_UsoCFDI").obtener(uso_cfdi)
    if registro is None or not registro.vigente_en(fecha):
        return False
    if not _si(registro["persona_moral"] if persona_moral else registro["persona_fisica"]):
        return False
    regimenes = {r.strip() for r in (registro["regimen_fiscal_receptor"] or "").split(",")}
    return regimen_fiscal_receptor in regimenes
