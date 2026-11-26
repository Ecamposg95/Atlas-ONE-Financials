"""``ProveedorSimulado``: un PAC en memoria para pruebas y desarrollo. **Sin validez fiscal.**

Imita lo que el spike vio en los ambientes de pruebas reales:

- timbrar el mismo XML sellado dos veces devuelve el mismo timbre (como
  Formas Digitales), así que un reenvío nunca crea un segundo UUID;
- ``consultar_timbrado`` busca por identificador idempotente o por sello;
- la cancelación queda "En proceso" hasta que la prueba decide el desenlace.

Se le puede ordenar rechazar con un código, no responder (antes o después de
timbrar) o rechazar la cancelación. El timbre trae ``RfcProvCertif``
``AAA010101AAA`` (RFC genérico de pruebas del SAT), ``NoCertificadoSAT`` en
ceros y ``SelloSAT`` que dice SIMULADO.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuidlib
from dataclasses import dataclass, field

from lxml import etree

from app.services.cfdi.proveedor_timbrado import (
    Estado,
    EstadoCancelacion,
    ResultadoCancelacion,
    ResultadoEstatus,
    ResultadoTimbrado,
    normalizar_error,
    parsear,
    sin_respuesta,
)

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
XSD_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital http://www.sat.gob.mx/sitio_internet/cfd/TimbreFiscalDigital/TimbreFiscalDigitalv11.xsd"
RFC_SIMULADO = "AAA010101AAA"
NS_CANCELACION = "http://cancelacfd.sat.gob.mx"


@dataclass
class _Timbre:
    uuid: str
    xml: bytes
    fecha: str
    estado_sat: str = "Vigente"
    estatus_cancelacion: str | None = None


@dataclass
class ProveedorSimulado:
    nombre: str = "simulado"
    algoritmo_cancelacion: str = "sha256"
    folio_sustitucion_vacio: bool = False

    # Órdenes para la siguiente llamada (se consumen al usarse).
    rechazar_con: tuple[str, str] | None = None  # (código, mensaje del proveedor)
    sin_respuesta_antes: bool = False  # no llega al proveedor
    sin_respuesta_despues: bool = False  # timbra pero la respuesta se pierde
    rechazar_cancelacion_con: tuple[str, str] | None = None
    cancelacion_sin_respuesta: bool = False
    consulta_sin_respuesta: bool = False

    envios: int = 0
    timbres: dict[str, _Timbre] = field(default_factory=dict)  # sello -> timbre
    por_id: dict[str, str] = field(default_factory=dict)  # id idempotente -> sello
    cancelaciones: list[bytes] = field(default_factory=list)

    # ------------------------------------------------------------ timbrar

    @staticmethod
    def _sello(xml_sellado: bytes) -> str:
        return parsear(xml_sellado).get("Sello") or ""

    def _timbrar(self, xml_sellado: bytes) -> _Timbre:
        raiz = parsear(xml_sellado)
        fecha = dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).replace(microsecond=0, tzinfo=None)
        complemento = raiz.find(f"{{{NS_CFDI}}}Complemento")
        if complemento is None:
            complemento = etree.SubElement(raiz, f"{{{NS_CFDI}}}Complemento")
        uuid = str(uuidlib.uuid4()).upper()
        tfd = etree.SubElement(complemento, f"{{{NS_TFD}}}TimbreFiscalDigital", nsmap={"tfd": NS_TFD})
        tfd.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", XSD_TFD)
        tfd.set("Version", "1.1")
        tfd.set("UUID", uuid)
        tfd.set("FechaTimbrado", fecha.isoformat())
        tfd.set("RfcProvCertif", RFC_SIMULADO)
        tfd.set("SelloCFD", raiz.get("Sello") or "")
        tfd.set("NoCertificadoSAT", "0" * 20)
        tfd.set("SelloSAT", "SIMULADO-SIN-VALIDEZ-FISCAL")
        return _Timbre(uuid=uuid, xml=etree.tostring(raiz, xml_declaration=True, encoding="UTF-8"), fecha=fecha.isoformat())

    def _resultado(self, t: _Timbre) -> ResultadoTimbrado:
        return ResultadoTimbrado(Estado.TIMBRADO, t.uuid, t.xml, RFC_SIMULADO, t.fecha)

    def timbrar(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado:
        if self.sin_respuesta_antes:
            self.sin_respuesta_antes = False
            return ResultadoTimbrado(Estado.INDETERMINADO, error=sin_respuesta("timed out"))
        if self.rechazar_con:
            codigo, mensaje = self.rechazar_con
            self.rechazar_con = None
            return ResultadoTimbrado(Estado.RECHAZADO, error=normalizar_error(codigo, mensaje))
        sello = self._sello(xml_sellado)
        existente = self.timbres.get(sello)
        if existente is None:
            self.envios += 1
            existente = self.timbres[sello] = self._timbrar(xml_sellado)
        self.por_id[id_idempotente] = sello
        if self.sin_respuesta_despues:
            self.sin_respuesta_despues = False
            return ResultadoTimbrado(Estado.INDETERMINADO, error=sin_respuesta("timed out"))
        return self._resultado(existente)

    def consultar_timbrado(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado:
        if self.consulta_sin_respuesta:
            self.consulta_sin_respuesta = False
            return ResultadoTimbrado(Estado.INDETERMINADO, error=sin_respuesta("timed out"))
        sello = self.por_id.get(id_idempotente) or self._sello(xml_sellado)
        t = self.timbres.get(sello)
        return self._resultado(t) if t else ResultadoTimbrado(Estado.NO_ENCONTRADO)

    # ------------------------------------------------------------ cancelar y estatus

    def _por_uuid(self, uuid: str) -> _Timbre | None:
        return next((t for t in self.timbres.values() if t.uuid == uuid.upper()), None)

    def cancelar(self, solicitud_firmada: bytes) -> ResultadoCancelacion:
        self.cancelaciones.append(solicitud_firmada)
        if self.cancelacion_sin_respuesta:
            self.cancelacion_sin_respuesta = False
            return ResultadoCancelacion(EstadoCancelacion.INDETERMINADA, error=sin_respuesta("timed out"))
        if self.rechazar_cancelacion_con:
            codigo, mensaje = self.rechazar_cancelacion_con
            self.rechazar_cancelacion_con = None
            return ResultadoCancelacion(EstadoCancelacion.RECHAZADA, error=normalizar_error(codigo, mensaje))
        estatus = {}
        for folio in parsear(solicitud_firmada).iter(f"{{{NS_CANCELACION}}}Folio"):
            t = self._por_uuid(folio.get("UUID"))
            if t is None:
                return ResultadoCancelacion(
                    EstadoCancelacion.RECHAZADA, error=normalizar_error("205", "UUID no existe")
                )
            if t.estado_sat == "Cancelado":
                estatus[t.uuid] = "202"
            else:
                t.estatus_cancelacion = "En proceso"
                estatus[t.uuid] = "201"
        acuse = f'<Acuse xmlns="{NS_CANCELACION}" Simulado="si"/>'.encode()
        return ResultadoCancelacion(EstadoCancelacion.ACEPTADA, estatus, acuse)

    def resolver_cancelacion(self, uuid: str, *, aceptada: bool = True) -> None:
        """Lo que haría el receptor (o el plazo) en el SAT."""
        t = self._por_uuid(uuid)
        if aceptada:
            t.estado_sat, t.estatus_cancelacion = "Cancelado", "Cancelado con aceptación"
        else:
            t.estatus_cancelacion = "Solicitud rechazada"

    def consultar_estatus(
        self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None = None
    ) -> ResultadoEstatus:
        if self.consulta_sin_respuesta:
            self.consulta_sin_respuesta = False
            return ResultadoEstatus(None, error=sin_respuesta("timed out"))
        t = self._por_uuid(uuid)
        if t is None:
            return ResultadoEstatus("No Encontrado", codigo="N - 602")
        return ResultadoEstatus(t.estado_sat, "Cancelable con aceptación", t.estatus_cancelacion, "S - Comprobante obtenido satisfactoriamente.")

