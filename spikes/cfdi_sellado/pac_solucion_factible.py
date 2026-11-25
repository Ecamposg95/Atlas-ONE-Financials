"""Adaptador de Solución Factible (SFERP) por SOAP. Sólo ambiente de PRUEBAS.

Documentación: https://www.solucionfactible.com/sfic/capitulos/timbrado/ws-timbrado.jsp
publica la URL de pruebas y "Las credenciales que pueden ser usadas para
conectarse al Webservice de prueba"; se leen de ``SF_USUARIO`` y ``SF_CONTRASENA``.

- Timbrar: ``Timbrado.timbrar`` con el XML sellado en base64.
- Cancelar: ``Timbrado.enviarSolicitudCancelacion`` recibe la solicitud ya
  firmada, entera y en base64 (``ws-timbrado-enviarSolicitudCancelacion.jsp``).
  A diferencia de Formas Digitales, no la rearma.
- Estatus: Solución Factible no publica una consulta general de estatus ante el
  SAT; ``consultar_estatus`` delega en otro consultor (p. ej. el de Formas
  Digitales, que consulta al SAT sin importar quién timbró) o falla.
"""

from __future__ import annotations

import base64
from xml.sax.saxutils import escape

from proveedor_timbrado import (
    Estado,
    ProveedorTimbrado,
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

URL_TIMBRADO_PRUEBAS = "https://testing.solucionfactible.com/ws/services/Timbrado"
NS = "http://timbrado.ws.cfdi.solucionfactible.com"


class SolucionFactible:
    def __init__(
        self,
        usuario: str,
        contrasena: str,
        transporte: Transporte | None = None,
        consulta_estatus: ProveedorTimbrado | None = None,
    ):
        self._usuario = usuario
        self._contrasena = contrasena
        self._enviar = transporte or transporte_http()
        self._consulta = consulta_estatus

    def _sobre(self, operacion: str, campos: str) -> bytes:
        return (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:tim="{NS}"><soapenv:Header/><soapenv:Body><tim:{operacion}>'
            f"<tim:usuario>{escape(self._usuario)}</tim:usuario><tim:password>{escape(self._contrasena)}</tim:password>"
            f"{campos}</tim:{operacion}></soapenv:Body></soapenv:Envelope>"
        ).encode("utf-8")

    # --- timbrar -----------------------------------------------------------
    def sobre_timbrar(self, xml_sellado: bytes) -> bytes:
        return self._sobre("timbrar", f"<tim:cfdi>{base64.b64encode(xml_sellado).decode()}</tim:cfdi><tim:zip>false</tim:zip>")

    def timbrar(self, xml_sellado: bytes, id_idempotente: str) -> ResultadoTimbrado:
        # Sin identificador idempotente: reenviar el mismo XML devuelve 307 con
        # el timbre original (ver README).
        try:
            resp, seg = cronometrar(self._enviar, URL_TIMBRADO_PRUEBAS, "urn:timbrar", self.sobre_timbrar(xml_sellado))
        except SinRespuesta as e:
            return ResultadoTimbrado(Estado.INDETERMINADO, mensaje=str(e))
        return self.interpretar_timbrado(resp, seg)

    @staticmethod
    def interpretar_timbrado(resp: bytes, segundos: float = 0.0) -> ResultadoTimbrado:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoTimbrado(Estado.RECHAZADO, codigo_proveedor="SOAP", mensaje=f, segundos=segundos)
        resultados = raiz.xpath(".//*[local-name()='resultados']")
        if not resultados:
            return ResultadoTimbrado(
                Estado.RECHAZADO, codigo_proveedor=texto(raiz, "status"), mensaje=texto(raiz, "mensaje"), segundos=segundos
            )
        r = resultados[0]
        codigo, cfdi_b64 = texto(r, "status"), texto(r, "cfdiTimbrado")
        if cfdi_b64 and codigo in {"200", "307"}:  # 307: ya timbrado antes; devuelve el mismo timbre
            xml = base64.b64decode(cfdi_b64)
            uuid, rfc_pac, fecha = datos_timbre(xml)
            return ResultadoTimbrado(Estado.TIMBRADO, uuid, xml, rfc_pac, fecha, codigo, texto(r, "mensaje"), segundos)
        return ResultadoTimbrado(Estado.RECHAZADO, codigo_proveedor=codigo, mensaje=texto(r, "mensaje"), segundos=segundos)

    # --- cancelar ----------------------------------------------------------
    def sobre_cancelar(self, solicitud_firmada: bytes) -> bytes:
        return self._sobre(
            "enviarSolicitudCancelacion",
            f"<tim:solicitudCancelacion>{base64.b64encode(solicitud_firmada).decode()}</tim:solicitudCancelacion>",
        )

    def cancelar(self, solicitud_firmada: bytes) -> ResultadoCancelacion:
        try:
            resp, seg = cronometrar(
                self._enviar, URL_TIMBRADO_PRUEBAS, "urn:enviarSolicitudCancelacion", self.sobre_cancelar(solicitud_firmada)
            )
        except SinRespuesta as e:
            return ResultadoCancelacion(False, mensaje=f"Sin respuesta: {e}")
        return self.interpretar_cancelacion(resp, seg)

    @staticmethod
    def interpretar_cancelacion(resp: bytes, segundos: float = 0.0) -> ResultadoCancelacion:
        raiz = parsear(resp)
        if (f := fault(raiz)) is not None:
            return ResultadoCancelacion(False, codigo_proveedor="SOAP", mensaje=f, segundos=segundos)
        ret = raiz.xpath(".//*[local-name()='return']")
        ret = ret[0] if ret else raiz
        codigo = next((c.text for c in ret if c.tag.endswith("}status")), None)
        mensaje_general = next((c.text for c in ret if c.tag.endswith("}mensaje")), None)
        estatus, mensajes = {}, []
        for r in raiz.xpath(".//*[local-name()='resultados']"):
            uuid = texto(r, "uuid")
            if uuid:
                estatus[uuid.upper()] = texto(r, "statusUUID") or texto(r, "status")
                mensajes.append(texto(r, "mensaje") or "")
        # 211: "en proceso"; el desenlace se lee con consultar_estatus (ADR-018).
        aceptada = codigo == "200" and bool(estatus) and all(v in {"201", "202", "211"} for v in estatus.values())
        return ResultadoCancelacion(aceptada, codigo, estatus, "; ".join(mensajes) or mensaje_general, None, segundos)

    # --- consultar estatus -------------------------------------------------
    def consultar_estatus(
        self, uuid: str, rfc_emisor: str, rfc_receptor: str, total: str, sello: str | None = None
    ) -> ResultadoEstatus:
        if self._consulta is None:
            raise NotImplementedError("Solución Factible no publica consulta de estatus; inyecta otro consultor")
        return self._consulta.consultar_estatus(uuid, rfc_emisor, rfc_receptor, total, sello)
