"""Interfaz ``ProveedorTimbrado`` del ADR-018 y lo común a los adaptadores.

Tres operaciones: ``timbrar`` (XML ya sellado), ``cancelar`` (solicitud ya
firmada por nosotros, nunca la llave) y ``consultar_estatus``. Cada proveedor
es un adaptador; el transporte HTTP se inyecta para poder probar con
respuestas grabadas.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, runtime_checkable

from lxml import etree


class Estado(str, Enum):
    TIMBRADO = "timbrado"
    RECHAZADO = "rechazado"
    INDETERMINADO = "indeterminado"  # sin respuesta: consultar antes de reintentar en otro proveedor


@dataclass
class ResultadoTimbrado:
    estado: Estado
    uuid: str | None = None
    xml_timbrado: bytes | None = None  # tal como llegó; nunca reconstruirlo
    rfc_prov_certif: str | None = None
    fecha_timbrado: str | None = None
    codigo_proveedor: str | None = None
    mensaje: str | None = None
    segundos: float = 0.0


@dataclass
class ResultadoCancelacion:
    aceptada: bool  # el proveedor (y el SAT, si lo reenvió) recibió la solicitud
    codigo_proveedor: str | None = None
    estatus_uuid: dict[str, str] = field(default_factory=dict)  # UUID -> código del SAT (201, 202, 302…)
    mensaje: str | None = None
    acuse: bytes | None = None
    segundos: float = 0.0


@dataclass
class ResultadoEstatus:
    estado: str | None  # Vigente, Cancelado, No Encontrado
    es_cancelable: str | None = None
    estatus_cancelacion: str | None = None
    codigo: str | None = None
    segundos: float = 0.0


@runtime_checkable
class ProveedorTimbrado(Protocol):
    def timbrar(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado: ...

    def cancelar(self, solicitud_firmada: bytes) -> ResultadoCancelacion: ...

    def consultar_estatus(
        self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None = None
    ) -> ResultadoEstatus: ...


class SinRespuesta(Exception):
    """Timeout, error de red o HTTP sin cuerpo SOAP: el resultado es indeterminado."""


# (url, SOAPAction, cuerpo) -> texto de la respuesta
Transporte = Callable[[str, str, bytes], bytes]


def transporte_http(timeout: float = 60.0) -> Transporte:
    def enviar(url: str, accion: str, cuerpo: bytes) -> bytes:
        req = urllib.request.Request(
            url, data=cuerpo, method="POST",
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
    return tfd[0].get("UUID"), tfd[0].get("RfcProvCertif"), tfd[0].get("FechaTimbrado")


def fault(raiz) -> str | None:
    f = raiz.xpath(".//*[local-name()='Fault']")
    if not f:
        return None
    return texto(f[0], "faultstring") or texto(f[0], "Text") or "SOAP Fault"
