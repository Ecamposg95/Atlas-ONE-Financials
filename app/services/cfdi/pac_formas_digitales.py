"""Adaptador de Formas Digitales (Forsedi) por SOAP. **Sólo ambiente de PRUEBAS.**

Proveedor de contingencia del ADR-018. Promovido de
``spikes/cfdi_sellado/pac_formas_digitales.py``, que timbró y canceló en su
ambiente de pruebas el 2026-11-25 con XML sellado por nosotros.

Apagado por omisión: se usa sólo con ``CFDI_PROVEEDOR=formas_digitales_pruebas``
y las credenciales de prueba que ellos publican en
https://forsedi.facturacfdi.mx/developers/ ("Datos de acceso (Pruebas)") en
``FD_USUARIO`` y ``FD_CONTRASENA``. Con ``ENV=production`` no se construye:
las URL de aquí son las de pruebas (producción es ``v33.facturacfdi.mx`` y
llegará con su contrato).

- Timbrar: ``TimbrarCFDI`` recibe el XML ya sellado (``TimbrarCFDIV2`` sella
  con un CSD guardado en su plataforma: no se usa).
- Consultar un timbrado indeterminado: Formas Digitales no recibe un
  identificador idempotente; el doble timbrado lo evita por el sello. Reenviar
  **el mismo XML sellado, byte por byte**, devuelve el mismo UUID (visto en el
  spike, ``fd_timbrar_duplicado.xml``). Por eso ``consultar_timbrado`` reenvía
  el XML guardado, que es su forma de consulta.
- Cancelar: ``Cancelacion40_2`` recibe RFC, fecha, folios y la ``Signature``
  que firmamos nosotros (``Cancelacion40_1`` pide ``.cer``, ``.key`` y
  contraseña, contra ADR-017). Acepta firma RSA-SHA256.
- Estatus: ``ConsultarEstatusCFDI_2``.
"""

from __future__ import annotations

import base64
import copy
from xml.sax.saxutils import escape

from lxml import etree

from app.services.cfdi.cancelacion import NS_CANCELACION, NS_DSIG
from app.services.cfdi.proveedor_timbrado import (
    Categoria,
    Estado,
    EstadoCancelacion,
    ResultadoCancelacion,
    ResultadoEstatus,
    ResultadoTimbrado,
    SinRespuesta,
    Transporte,
    cronometrar,
    datos_timbre,
    fault,
    normalizar_error,
    parsear,
    sin_respuesta,
    texto,
    transporte_http,
)

URL_TIMBRADO_PRUEBAS = "https://dev33.facturacfdi.mx/WSTimbradoCFDIService"
URL_CANCELACION_PRUEBAS = "https://dev-cancelacion.facturacfdi.mx/WSCancelacion40Service"
URL_CONSULTA_PRUEBAS = "https://dev-cancelacion.facturacfdi.mx/WSCancelacionService"

SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
WSER = "http://wservicios/"


def _error_fd(codigo: str | None, mensaje: str | None):
    """CFDI40999 es "no clasificado": Formas Digitales lo usa también para credenciales."""
    if codigo == "CFDI40999" and mensaje and ("contraseña" in mensaje.lower() or "usuario" in mensaje.lower()):
        return normalizar_error("CREDENCIALES", mensaje, codigo_proveedor=codigo)
    if mensaje and "saldo" in mensaje.lower():
        return normalizar_error("SALDO", mensaje, codigo_proveedor=codigo)
    return normalizar_error(codigo, mensaje)


class FormasDigitalesPruebas:
    nombre = "formas_digitales_pruebas"
    algoritmo_cancelacion = "sha256"
    folio_sustitucion_vacio = True  # rearman la solicitud con FolioSustitucion=""

    def __init__(
        self,
        usuario: str,
        contrasena: str,
        transporte: Transporte | None = None,
        *,
        entorno: str | None = None,
        certificado_doble_base64: bool = False,
    ):
        if entorno is None:
            from app.config import get_settings  # noqa: PLC0415

            entorno = get_settings().env
        if entorno == "production":
            raise ValueError("El adaptador de Formas Digitales de este módulo sólo habla con su ambiente de pruebas.")
        if not usuario or not contrasena:
            raise ValueError("Faltan FD_USUARIO y FD_CONTRASENA (credenciales de pruebas de Formas Digitales).")
        self._usuario = usuario
        self._contrasena = contrasena
        self._enviar = transporte or transporte_http()
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
        try:
            resp, seg = cronometrar(self._enviar, URL_TIMBRADO_PRUEBAS, '""', self.sobre_timbrar(xml_sellado))
        except SinRespuesta as e:
            return ResultadoTimbrado(Estado.INDETERMINADO, error=sin_respuesta(str(e)))
        return self.interpretar_timbrado(resp, seg)

    def consultar_timbrado(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado:
        # Ver docstring del módulo: el reenvío del mismo XML sellado es su consulta.
        return self.timbrar(xml_sellado, id_idempotente)

    @staticmethod
    def interpretar_timbrado(resp: bytes, segundos: float = 0.0) -> ResultadoTimbrado:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoTimbrado(
                Estado.RECHAZADO, error=normalizar_error("SOAP", f, categoria=Categoria.SERVICIO), segundos=segundos
            )
        xml = texto(raiz, "xmlTimbrado")
        if xml:
            xml_b = xml.encode("utf-8")
            uuid, rfc_pac, fecha = datos_timbre(xml_b)
            return ResultadoTimbrado(Estado.TIMBRADO, uuid, xml_b, rfc_pac, fecha, segundos=segundos)
        return ResultadoTimbrado(
            Estado.RECHAZADO, error=_error_fd(texto(raiz, "codigoError"), texto(raiz, "error")), segundos=segundos
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
            return ResultadoCancelacion(EstadoCancelacion.INDETERMINADA, error=sin_respuesta(str(e)))
        return self.interpretar_cancelacion(resp, seg)

    @staticmethod
    def interpretar_cancelacion(resp: bytes, segundos: float = 0.0) -> ResultadoCancelacion:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoCancelacion(
                EstadoCancelacion.RECHAZADA,
                error=normalizar_error("SOAP", f, categoria=Categoria.SERVICIO),
                segundos=segundos,
            )
        codigo = texto(raiz, "codEstatus")
        estatus, mensajes = {}, []
        for folio in raiz.xpath(".//*[local-name()='folio']"):
            uuid = texto(folio, "uuid")
            if uuid:
                estatus[uuid.upper()] = texto(folio, "estatusUUID")
                mensajes.append(texto(folio, "mensaje") or "")
        acuse_txt = texto(raiz, "acuse")
        acuse = acuse_txt.encode("utf-8") if acuse_txt else None
        if codigo == "0" and estatus and all(v in {"201", "202"} for v in estatus.values()):
            return ResultadoCancelacion(EstadoCancelacion.ACEPTADA, estatus, acuse, segundos=segundos)
        # Rechazo: el código del SAT del folio si lo hay (205, 302…), si no el del proveedor.
        codigo_folio = next((v for v in estatus.values() if v and v not in {"201", "202"}), None)
        mensaje = "; ".join(m for m in mensajes if m) or texto(raiz, "mensaje")
        return ResultadoCancelacion(
            EstadoCancelacion.RECHAZADA,
            estatus,
            acuse,
            error=_error_fd(codigo_folio or codigo, mensaje),
            segundos=segundos,
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
                self._enviar,
                URL_CONSULTA_PRUEBAS,
                '""',
                self.sobre_estatus(uuid, rfc_emisor, rfc_receptor, total, sello),
            )
        except SinRespuesta as e:
            return ResultadoEstatus(None, error=sin_respuesta(str(e)))
        return self.interpretar_estatus(resp, seg)

    @staticmethod
    def interpretar_estatus(resp: bytes, segundos: float = 0.0) -> ResultadoEstatus:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoEstatus(
                None, error=normalizar_error("SOAP", f, categoria=Categoria.SERVICIO), segundos=segundos
            )
        return ResultadoEstatus(
            texto(raiz, "estado"),
            texto(raiz, "esCancelable"),
            texto(raiz, "estatusCancelacion"),
            texto(raiz, "codigoEstatus"),
            segundos=segundos,
        )
