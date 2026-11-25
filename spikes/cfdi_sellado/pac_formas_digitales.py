"""Adaptador de Formas Digitales (Forsedi) por SOAP. Sólo ambiente de PRUEBAS.

Documentación: https://forsedi.facturacfdi.mx/developers/ (secciones
"Webservice › Timbrado › SOAP" y "Webservice › Cancelación › SOAP"). Ahí mismo,
en "Datos de acceso (Pruebas)", publican el usuario y la contraseña del
ambiente de pruebas; se leen de ``FD_USUARIO`` y ``FD_CONTRASENA``.

- Timbrar: ``TimbrarCFDI`` recibe el XML ya sellado (``TimbrarCFDIV2`` es el que
  sella con un CSD cargado en su plataforma: no se usa).
- Cancelar: ``Cancelacion40_2`` recibe RFC, fecha, folios y la ``Signature``
  que firmamos nosotros (``Cancelacion40_1`` pide ``.cer``, ``.key`` y
  contraseña; ``Cancelacion40_3`` usa un CSD guardado en su plataforma: ninguno
  de los dos cumple ADR-017). El servicio no recibe el XML de la solicitud
  entero, así que el adaptador lo desarma en sus campos.
- Estatus: ``ConsultarEstatusCFDI_2`` (consulta al SAT con UUID, RFC, total y sello).
"""

from __future__ import annotations

import base64
import copy
from xml.sax.saxutils import escape

from lxml import etree

from cancelacion import NS_CANCELACION, NS_DSIG
from proveedor_timbrado import (
    Estado,
    ResultadoCancelacion,
    ResultadoEstatus,
    ResultadoTimbrado,
    SinRespuesta,
    Transporte,
    cronometrar,
    datos_timbre,
    fault,
    parsear,
    texto,
    transporte_http,
)

URL_TIMBRADO_PRUEBAS = "https://dev33.facturacfdi.mx/WSTimbradoCFDIService"
URL_CANCELACION_PRUEBAS = "https://dev-cancelacion.facturacfdi.mx/WSCancelacion40Service"
URL_CONSULTA_PRUEBAS = "https://dev-cancelacion.facturacfdi.mx/WSCancelacionService"

SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
WSER = "http://wservicios/"


class FormasDigitales:
    def __init__(
        self,
        usuario: str,
        contrasena: str,
        transporte: Transporte | None = None,
        certificado_doble_base64: bool = False,
    ):
        self._usuario = usuario
        self._contrasena = contrasena
        self._enviar = transporte or transporte_http()
        # Su ejemplo público de Cancelacion40_2 manda X509Certificate codificado
        # dos veces en base64; ver README (se probaron las dos formas).
        self._doble_b64 = certificado_doble_base64

    def _accesos(self) -> str:
        return (
            f"<accesos><password>{escape(self._contrasena)}</password>"
            f"<usuario>{escape(self._usuario)}</usuario></accesos>"
        )

    def _sobre(self, cuerpo: str) -> bytes:
        return (
            f'<soapenv:Envelope xmlns:soapenv="{SOAPENV}" xmlns:wser="{WSER}">'
            f"<soapenv:Header/><soapenv:Body>{cuerpo}</soapenv:Body></soapenv:Envelope>"
        ).encode("utf-8")

    # --- timbrar -----------------------------------------------------------
    def sobre_timbrar(self, xml_sellado: bytes) -> bytes:
        return self._sobre(
            f"<wser:TimbrarCFDI>{self._accesos()}"
            f"<comprobante>{escape(xml_sellado.decode('utf-8'))}</comprobante></wser:TimbrarCFDI>"
        )

    def timbrar(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado:
        # Formas Digitales no recibe un identificador idempotente: el
        # "previamente timbrado" lo decide por el sello (ver README).
        try:
            resp, seg = cronometrar(self._enviar, URL_TIMBRADO_PRUEBAS, '""', self.sobre_timbrar(xml_sellado))
        except SinRespuesta as e:
            return ResultadoTimbrado(Estado.INDETERMINADO, mensaje=str(e))
        return self.interpretar_timbrado(resp, seg)

    @staticmethod
    def interpretar_timbrado(resp: bytes, segundos: float = 0.0) -> ResultadoTimbrado:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoTimbrado(Estado.RECHAZADO, codigo_proveedor="SOAP", mensaje=f, segundos=segundos)
        xml = texto(raiz, "xmlTimbrado")
        if xml:
            xml_b = xml.encode("utf-8")
            uuid, rfc_pac, fecha = datos_timbre(xml_b)
            return ResultadoTimbrado(Estado.TIMBRADO, uuid, xml_b, rfc_pac, fecha, segundos=segundos)
        return ResultadoTimbrado(
            Estado.RECHAZADO,
            codigo_proveedor=texto(raiz, "codigoError"),
            mensaje=texto(raiz, "error"),
            segundos=segundos,
        )

    # --- cancelar ----------------------------------------------------------
    def sobre_cancelar(self, solicitud_firmada: bytes) -> bytes:
        sol = parsear(solicitud_firmada)
        if sol.tag != f"{{{NS_CANCELACION}}}Cancelacion":
            raise ValueError("La solicitud no es un Cancelacion del SAT")
        folios = []
        for f in sol.iterfind(f"{{{NS_CANCELACION}}}Folios/{{{NS_CANCELACION}}}Folio"):
            folios.append(
                "<folios><folio>"
                f"<folioSustitucion>{escape(f.get('FolioSustitucion') or '')}</folioSustitucion>"
                f"<motivo>{escape(f.get('Motivo'))}</motivo><uuid>{escape(f.get('UUID'))}</uuid>"
                "</folio></folios>"
            )
        firma = sol.find(f"{{{NS_DSIG}}}Signature")
        partes = []
        for hijo in firma:
            h = copy.deepcopy(hijo)
            if self._doble_b64:
                for c in h.iter(f"{{{NS_DSIG}}}X509Certificate"):
                    c.text = base64.b64encode(c.text.encode("ascii")).decode("ascii")
            partes.append(etree.tostring(h, encoding="unicode"))
        return self._sobre(
            f'<wser:Cancelacion40_2 xmlns:xd="{NS_DSIG}">'
            f"<rfcEmisor>{escape(sol.get('RfcEmisor'))}</rfcEmisor><fecha>{escape(sol.get('Fecha'))}</fecha>"
            f"{''.join(folios)}<signatureType>{''.join(partes)}</signatureType>{self._accesos()}"
            "</wser:Cancelacion40_2>"
        )

    def cancelar(self, solicitud_firmada: bytes) -> ResultadoCancelacion:
        try:
            resp, seg = cronometrar(self._enviar, URL_CANCELACION_PRUEBAS, '""', self.sobre_cancelar(solicitud_firmada))
        except SinRespuesta as e:
            return ResultadoCancelacion(False, mensaje=f"Sin respuesta: {e}")
        return self.interpretar_cancelacion(resp, seg)

    @staticmethod
    def interpretar_cancelacion(resp: bytes, segundos: float = 0.0) -> ResultadoCancelacion:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoCancelacion(False, codigo_proveedor="SOAP", mensaje=f, segundos=segundos)
        codigo = texto(raiz, "codEstatus")
        estatus, mensajes = {}, []
        for folio in raiz.xpath(".//*[local-name()='folio']"):
            uuid = texto(folio, "uuid")
            if uuid:
                estatus[uuid.upper()] = texto(folio, "estatusUUID")
                mensajes.append(texto(folio, "mensaje") or "")
        acuse = texto(raiz, "acuse")
        mensaje = texto(raiz, "mensaje") if not mensajes else "; ".join(mensajes)
        aceptada = codigo == "0" and bool(estatus) and all(v in {"201", "202"} for v in estatus.values())
        return ResultadoCancelacion(
            aceptada, codigo, estatus, mensaje, acuse.encode("utf-8") if acuse else None, segundos
        )

    # --- consultar estatus -------------------------------------------------
    def sobre_estatus(self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None) -> bytes:
        return self._sobre(
            "<wser:ConsultarEstatusCFDI_2>"
            f"<rfcEmisor>{escape(rfc_emisor)}</rfcEmisor><rfcReceptor>{escape(rfc_receptor)}</rfcReceptor>"
            f"<totalCFDI>{escape(total)}</totalCFDI><uuid>{escape(uuid)}</uuid>"
            f"<selloCFDI>{escape(sello or '')}</selloCFDI>{self._accesos()}"
            "</wser:ConsultarEstatusCFDI_2>"
        )

    def consultar_estatus(
        self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None = None
    ) -> ResultadoEstatus:
        try:
            resp, seg = cronometrar(
                self._enviar, URL_CONSULTA_PRUEBAS, '""', self.sobre_estatus(uuid, rfc_emisor, rfc_receptor, total, sello)
            )
        except SinRespuesta as e:
            return ResultadoEstatus(None, codigo=f"Sin respuesta: {e}")
        return self.interpretar_estatus(resp, seg)

    @staticmethod
    def interpretar_estatus(resp: bytes, segundos: float = 0.0) -> ResultadoEstatus:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoEstatus(None, codigo=f"SOAP: {f}", segundos=segundos)
        return ResultadoEstatus(
            texto(raiz, "estado"),
            texto(raiz, "esCancelable"),
            texto(raiz, "estatusCancelacion"),
            texto(raiz, "codigoEstatus"),
            segundos,
        )
