"""Interfaz ``ProveedorTimbrado`` (ADR-018) y resultados normalizados.

Cada proveedor autorizado (PAC) es un adaptador con cuatro operaciones:

- ``timbrar(xml_sellado, id_idempotente)``: el XML ya sellado por nosotros.
- ``consultar_timbrado(xml_sellado, id_idempotente)``: después de un
  resultado indeterminado (timeout), **antes de reenviar**: ¿lo timbró? Cada
  adaptador dice cómo lo averigua sin poder timbrar dos veces.
- ``cancelar(solicitud_firmada)``: la solicitud ya firmada por nosotros; nunca la llave.
- ``consultar_estatus(uuid, rfc_emisor, rfc_receptor, total, sello)``: estado ante el SAT.

Los errores del proveedor se traducen a ``ErrorProveedor``: código del
proveedor, código del SAT cuando lo hay, una categoría que decide qué hace el
documento y un mensaje en español para la pantalla.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from lxml import etree

from app.services.cfdi.catalogos import cargador


class Estado(str, Enum):
    TIMBRADO = "timbrado"
    RECHAZADO = "rechazado"
    INDETERMINADO = "indeterminado"  # sin respuesta: consultar antes de reenviar
    NO_ENCONTRADO = "no_encontrado"  # sólo de consultar_timbrado: nunca llegó, se puede enviar


class EstadoCancelacion(str, Enum):
    ACEPTADA = "aceptada"  # el proveedor (y el SAT) recibió la solicitud; el desenlace se consulta
    RECHAZADA = "rechazada"
    INDETERMINADA = "indeterminada"


class Categoria(str, Enum):
    """Qué hacer con el documento ante un rechazo."""

    DATOS = "DATOS"  # datos del comprobante: volver a borrador y corregir
    DATOS_RECEPTOR = "DATOS_RECEPTOR"  # RFC, nombre, CP o régimen del cliente contra el padrón
    FECHA = "FECHA"  # fuera de la ventana de 72 horas: volver a preparar
    CERTIFICADO = "CERTIFICADO"  # sello, certificado vencido, revocado o restringido
    CREDENCIALES = "CREDENCIALES"  # configuración de Atlas con el proveedor
    SALDO = "SALDO"  # timbres agotados
    SERVICIO = "SERVICIO"  # falla del proveedor o del SAT: reintentar más tarde
    REINTENTAR = "REINTENTAR"  # el SAT aún no conoce el UUID (cancelación)
    SIN_RESPUESTA = "SIN_RESPUESTA"


# Rechazos que NO dependen del contenido: el XML sellado se puede reenviar tal cual.
CATEGORIAS_REENVIABLES = (Categoria.CREDENCIALES, Categoria.SALDO, Categoria.SERVICIO)


@dataclass(frozen=True)
class ErrorProveedor:
    categoria: Categoria
    mensaje: str  # español, para la pantalla
    codigo_proveedor: str | None = None
    codigo_sat: str | None = None
    mensaje_proveedor: str | None = None  # texto original, para soporte

    def como_dict(self) -> dict:
        return {
            "categoria": self.categoria.value,
            "mensaje": self.mensaje,
            "codigo_proveedor": self.codigo_proveedor,
            "codigo_sat": self.codigo_sat,
            "mensaje_proveedor": self.mensaje_proveedor,
        }


@dataclass
class ResultadoTimbrado:
    estado: Estado
    uuid: str | None = None
    xml_timbrado: bytes | None = None  # tal como llegó; nunca reconstruirlo
    rfc_prov_certif: str | None = None
    fecha_timbrado: str | None = None
    error: ErrorProveedor | None = None
    segundos: float = 0.0


@dataclass
class ResultadoCancelacion:
    estado: EstadoCancelacion
    estatus_uuid: dict[str, str] = field(default_factory=dict)  # UUID -> código del SAT (201, 202…)
    acuse: bytes | None = None
    error: ErrorProveedor | None = None
    segundos: float = 0.0


@dataclass
class ResultadoEstatus:
    estado: str | None  # Vigente, Cancelado, No Encontrado; None si no hubo respuesta
    es_cancelable: str | None = None
    estatus_cancelacion: str | None = None  # En proceso, Cancelado sin aceptación, Solicitud rechazada…
    codigo: str | None = None
    error: ErrorProveedor | None = None
    segundos: float = 0.0


@runtime_checkable
class ProveedorTimbrado(Protocol):
    #: Nombre corto que se guarda en el documento y en la bitácora.
    nombre: str
    #: Algoritmo con que el proveedor acepta la solicitud de cancelación ("sha256" o "sha1").
    algoritmo_cancelacion: str
    #: El proveedor rearma la solicitud con ``FolioSustitucion=""`` (Formas Digitales).
    folio_sustitucion_vacio: bool

    def timbrar(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado: ...

    def consultar_timbrado(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado: ...

    def cancelar(self, solicitud_firmada: bytes) -> ResultadoCancelacion: ...

    def consultar_estatus(
        self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None = None
    ) -> ResultadoEstatus: ...


# ---------------------------------------------------------------- errores en español

_MENSAJES: dict[str, tuple[Categoria, str]] = {
    "401": (
        Categoria.FECHA,
        "La fecha de la factura tiene más de 72 horas o es futura. Vuelve a prepararla para fecharla de nuevo.",
    ),
    "CFDI40102": (
        Categoria.CERTIFICADO,
        "El sello de la factura no corresponde a su contenido. Es un error nuestro: avisa a soporte.",
    ),
    "302": (Categoria.CERTIFICADO, "El SAT considera el sello mal formado o inválido."),
    "303": (Categoria.CERTIFICADO, "El sello no corresponde al RFC que emite la factura."),
    "304": (Categoria.CERTIFICADO, "El certificado de sello está revocado o vencido. Tramita uno nuevo en el SAT."),
    "305": (Categoria.CERTIFICADO, "La fecha de la factura no está dentro de la vigencia del certificado de sello."),
    "306": (Categoria.CERTIFICADO, "El certificado no es de sello digital (¿es la e.firma?)."),
    "205": (Categoria.REINTENTAR, "El SAT todavía no registra esta factura. Intenta de nuevo en unos minutos."),
    "SALDO": (Categoria.SALDO, "Se agotaron los timbres con el proveedor. Ya avisamos a Atlas para recargarlos."),
    "CREDENCIALES": (
        Categoria.CREDENCIALES,
        "El proveedor de timbrado rechazó la conexión de Atlas. No es un problema de tu factura; intenta más tarde.",
    ),
    "SOAP": (Categoria.SERVICIO, "El proveedor de timbrado tuvo una falla. Intenta de nuevo en unos minutos."),
}


def normalizar_error(
    codigo: str | None,
    mensaje_proveedor: str | None = None,
    *,
    codigo_proveedor: str | None = None,
    categoria: Categoria | None = None,
) -> ErrorProveedor:
    """Traduce un código (del SAT o del proveedor) a categoría y mensaje en español.

    Usa la matriz de errores del SAT (``catalogos/data/matrices``) para los
    ``CFDI40xxx`` que no están en la tabla propia.
    """
    codigo = (codigo or "").strip() or None
    codigo_sat = codigo if codigo and (codigo.startswith("CFDI") or codigo.isdigit()) else None
    if codigo in _MENSAJES:
        cat, mensaje = _MENSAJES[codigo]
    else:
        filas = cargador.errores_sat(codigo) if codigo else ()
        if filas and codigo != "CFDI40999":
            fila = filas[0]
            receptor = (fila.elemento or "").endswith("Receptor")
            cat = Categoria.DATOS_RECEPTOR if receptor else Categoria.DATOS
            prefijo = "Los datos fiscales del cliente no coinciden con el SAT: " if receptor else ""
            mensaje = f"{prefijo}{fila.descripcion}"
        else:
            cat = Categoria.DATOS
            mensaje = "El proveedor de timbrado rechazó la factura" + (f": {mensaje_proveedor}" if mensaje_proveedor else ".")
    return ErrorProveedor(
        categoria=categoria or cat,
        mensaje=mensaje,
        codigo_proveedor=codigo_proveedor or codigo,
        codigo_sat=codigo_sat,
        mensaje_proveedor=mensaje_proveedor,
    )


def sin_respuesta(detalle: str | None = None) -> ErrorProveedor:
    return ErrorProveedor(
        categoria=Categoria.SIN_RESPUESTA,
        mensaje="El proveedor de timbrado no respondió. No reenviamos nada sin antes consultar si ya quedó timbrada.",
        mensaje_proveedor=detalle,
    )


# ---------------------------------------------------------------- transporte y XML


class SinRespuesta(Exception):
    """Timeout, error de red o HTTP sin cuerpo SOAP: el resultado es indeterminado."""


# (url, SOAPAction, cuerpo) -> bytes de la respuesta
Transporte = Callable[[str, str, bytes], bytes]


def transporte_http(timeout: float = 60.0) -> Transporte:
    def enviar(url: str, accion: str, cuerpo: bytes) -> bytes:
        req = urllib.request.Request(
            url,
            data=cuerpo,
            method="POST",
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": accion},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — URL fija del adaptador
                return r.read()
        except urllib.error.HTTPError as e:  # un SOAP Fault llega como 500 con cuerpo
            cuerpo_error = e.read()
            if b"Envelope" in cuerpo_error:
                return cuerpo_error
            raise SinRespuesta(f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SinRespuesta(str(e)) from e

    return enviar


def cronometrar(fn, *args):
    t = time.monotonic()
    r = fn(*args)
    return r, round(time.monotonic() - t, 3)


PARSER = etree.XMLParser(no_network=True, resolve_entities=False, huge_tree=True)


def parsear(xml: bytes) -> etree._Element:
    return etree.fromstring(xml, PARSER)


def texto(nodo, nombre_local: str) -> str | None:
    """Primer descendiente con ese nombre local, sin importar el namespace."""
    hallado = nodo.xpath(f".//*[local-name()='{nombre_local}']")
    return hallado[0].text if hallado else None


def datos_timbre(xml_timbrado: bytes) -> tuple[str | None, str | None, str | None]:
    """UUID, RfcProvCertif y FechaTimbrado del TimbreFiscalDigital."""
    tfd = parsear(xml_timbrado).xpath(".//*[local-name()='TimbreFiscalDigital']")
    if not tfd:
        return None, None, None
    uuid = tfd[0].get("UUID")
    return (uuid.upper() if uuid else None), tfd[0].get("RfcProvCertif"), tfd[0].get("FechaTimbrado")


def fault(raiz) -> str | None:
    f = raiz.xpath(".//*[local-name()='Fault']")
    if not f:
        return None
    return texto(f[0], "faultstring") or texto(f[0], "Text") or "SOAP Fault"
