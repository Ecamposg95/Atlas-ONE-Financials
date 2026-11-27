"""Sellar, timbrar, cancelar y consultar un documento fiscal (ADR-017 y ADR-018).

Escribe sólo en ``documentos_fiscales*``: nunca crea pólizas, mueve saldos ni
cambia la operación. Timbrar no es cobrar y cancelar el CFDI no cancela el
ingreso (eso, si procede, lo hace la persona en la operación).

Reglas que este módulo cuida:

- **Guardar antes de enviar.** El XML sellado se guarda (inmutable) y se hace
  commit antes de llamar al proveedor; también la marca ``timbrado_enviado_at``.
  El XML timbrado se guarda tal como llegó.
- **Nunca timbrar dos veces.** Un reintento después de una respuesta
  indeterminada primero llama a ``consultar_timbrado`` con el mismo XML e
  identificador; sólo reenvía si el proveedor dice que no lo tiene. Un envío
  sin respuesta registrada y reciente se trata como "en curso". Un documento
  enviado a un proveedor sin respuesta no se manda a otro.
- **Bitácora de cada firma** (sello y solicitud de cancelación): usuario,
  documento, número de certificado y SHA-256 de lo firmado; y de cada respuesta
  del proveedor.
- El estado final de una cancelación lo da ``consultar_estatus``, no un plazo.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.fiscal_mx import documentos as docs
from app.domains.fiscal_mx.documentos import DocumentoError
from app.models.fiscal_document import (
    BITACORA_CANCELACION,
    BITACORA_CONSULTA_TIMBRADO,
    BITACORA_ESTATUS,
    BITACORA_FIRMA_CANCELACION,
    BITACORA_SELLO,
    BITACORA_TIMBRADO,
    FD_BORRADOR,
    FD_CANCELACION_EN_PROCESO,
    FD_CANCELACION_RECHAZADA,
    FD_CANCELADO,
    FD_CON_UUID,
    FD_LISTO,
    FD_SELLADO,
    FD_TIMBRADO,
    XML_ACUSE_CANCELACION,
    XML_SELLADO,
    XML_TIMBRADO,
    FiscalDocument,
    FiscalDocumentXml,
    FiscalSignatureLog,
)
from app.services.cfdi import xml_sat
from app.services.cfdi.cancelacion import MOTIVOS, ErrorCancelacion, FolioCancelacion, armar_solicitud
from app.services.cfdi.comprobante import xml_sin_sellar
from app.services.cfdi.configuracion import ServiciosTimbrado
from app.services.cfdi.firmante import ErrorFirmante, Firmante, FirmanteNoDisponible, numero_certificado
from app.services.cfdi.proveedor_timbrado import (
    CATEGORIAS_REENVIABLES,
    Categoria,
    ErrorProveedor,
    Estado,
    EstadoCancelacion,
    ResultadoTimbrado,
    datos_timbre,
    normalizar_error,
    parsear,
)
from app.services.cfdi.sellado import ErrorSellado, revisar_certificado, sellar
from app.services.cfdi.zona_horaria import CodigoPostalSinHuso, hora_local

# Un envío sin respuesta registrada y más joven que esto se considera en curso.
ENVIO_EN_CURSO = dt.timedelta(minutes=3)
_UUID = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


class ProveedorSinRespuesta(DocumentoError):
    def __init__(self, mensaje: str):
        super().__init__(mensaje, 504)


# ---------------------------------------------------------------- utilidades


def _ahora() -> dt.datetime:
    return docs._ahora()


def _utc(valor: dt.datetime | None) -> dt.datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=dt.timezone.utc)


def _bloquear(db: Session, org_id: str, documento_id: str) -> FiscalDocument:
    doc = (
        db.query(FiscalDocument)
        .filter(FiscalDocument.id == documento_id, FiscalDocument.organization_id == org_id)
        .with_for_update()
        .first()
    )
    if doc is None:
        raise DocumentoError("La factura no existe.", 404)
    return doc


def _xml(db: Session, doc: FiscalDocument, tipo: str) -> FiscalDocumentXml | None:
    """El XML vigente de ese tipo (el de secuencia mayor)."""
    return (
        db.query(FiscalDocumentXml)
        .filter(FiscalDocumentXml.documento_id == doc.id, FiscalDocumentXml.tipo == tipo)
        .order_by(FiscalDocumentXml.secuencia.desc())
        .first()
    )


def _guardar_xml(db: Session, doc: FiscalDocument, tipo: str, contenido: bytes) -> FiscalDocumentXml:
    ultima = (
        db.query(func.max(FiscalDocumentXml.secuencia))
        .filter(FiscalDocumentXml.documento_id == doc.id, FiscalDocumentXml.tipo == tipo)
        .scalar()
    )
    fila = FiscalDocumentXml(
        organization_id=doc.organization_id,
        documento_id=doc.id,
        tipo=tipo,
        secuencia=(ultima or 0) + 1,
        contenido=contenido,
        sha256=hashlib.sha256(contenido).hexdigest(),
        bytes=len(contenido),
    )
    db.add(fila)
    db.flush()
    return fila


def _bitacora(db: Session, doc: FiscalDocument, evento: str, user_id: str | None, **campos) -> None:
    mensaje = campos.pop("mensaje", None)
    db.add(
        FiscalSignatureLog(
            organization_id=doc.organization_id,
            documento_id=doc.id,
            evento=evento,
            user_id=user_id,
            mensaje=mensaje[:500] if mensaje else None,
            **campos,
        )
    )


def _error_dict(error: ErrorProveedor | None) -> dict | None:
    if error is None:
        return None
    return {**error.como_dict(), "at": _ahora().isoformat()}


def _firmante(servicios: ServiciosTimbrado, doc: FiscalDocument) -> Firmante:
    try:
        return servicios.firmante_para(doc.organization_id, doc.emisor_rfc)
    except FirmanteNoDisponible as exc:
        raise DocumentoError(str(exc), 503) from exc
    except ErrorFirmante as exc:
        raise DocumentoError(str(exc), 409) from exc


def _fecha_local(doc: FiscalDocument) -> dt.datetime:
    ahora = _ahora()
    try:
        if not doc.lugar_expedicion:
            raise CodigoPostalSinHuso("sin código postal")
        return hora_local(doc.lugar_expedicion, ahora).local
    except CodigoPostalSinHuso:
        return (ahora.astimezone(dt.timezone.utc) + dt.timedelta(hours=-6)).replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------- sellar


def _sellar(db: Session, doc: FiscalDocument, user_id: str | None, servicios: ServiciosTimbrado) -> None:
    """LISTO_PARA_TIMBRAR → SELLADO, con el XML sellado guardado y la firma en bitácora."""
    firmante = _firmante(servicios, doc)
    try:
        revisar_certificado(firmante, doc.emisor_rfc, _utc(doc.fecha_emision_utc))
        sellado = sellar(xml_sin_sellar(docs.comprobante(doc)), firmante)
    except (ErrorSellado, ErrorFirmante) as exc:
        raise DocumentoError(str(exc), 409) from exc
    errores = xml_sat.errores_xsd(sellado.xml)
    if errores:  # no debería pasar: la validación previa ya revisó el XSD
        raise DocumentoError(f"El XML sellado no pasa el esquema del SAT: {errores[0]}", 422)
    fila = _guardar_xml(db, doc, XML_SELLADO, sellado.xml)
    _bitacora(
        db,
        doc,
        BITACORA_SELLO,
        user_id,
        no_certificado=sellado.no_certificado,
        sha256=sellado.sha256_cadena,
        firmante=firmante.tipo,
        resultado="firmado",
    )
    doc.no_certificado = sellado.no_certificado
    doc.id_idempotente = f"{doc.id}:{fila.secuencia}"
    doc.timbrado_enviado_at = None
    doc.ultimo_error = None
    doc.estado = FD_SELLADO
    db.commit()


# ---------------------------------------------------------------- timbrar


def _registrar_timbre(
    db: Session, doc: FiscalDocument, r: ResultadoTimbrado, xml_sellado: bytes, user_id: str | None, nombre: str
) -> FiscalDocument:
    if not r.xml_timbrado:
        raise DocumentoError("El proveedor dijo que timbró pero no devolvió el XML. Avisa a soporte.", 502)
    uuid, rfc_pac, fecha = datos_timbre(r.xml_timbrado)
    uuid = uuid or (r.uuid.upper() if r.uuid else None)
    if not uuid:
        raise DocumentoError("El XML timbrado no trae folio fiscal (UUID). Avisa a soporte.", 502)
    nuestro_sello = parsear(xml_sellado).get("Sello")
    mismo_sello = parsear(r.xml_timbrado).get("Sello") == nuestro_sello
    _guardar_xml(db, doc, XML_TIMBRADO, r.xml_timbrado)
    _bitacora(
        db,
        doc,
        BITACORA_TIMBRADO,
        user_id,
        proveedor=nombre,
        uuid_fiscal=uuid,
        resultado="timbrado",
        sha256=hashlib.sha256(r.xml_timbrado).hexdigest(),
        mensaje=None if mismo_sello else "ALERTA: el sello del XML timbrado no es el que enviamos.",
        segundos=r.segundos,
    )
    doc.uuid_fiscal = uuid
    doc.rfc_prov_certif = rfc_pac or r.rfc_prov_certif
    fecha = fecha or r.fecha_timbrado
    try:  # FechaTimbrado es hora del centro sin zona (Anexo 20); se guarda tal cual
        doc.fecha_timbrado = dt.datetime.fromisoformat(fecha).replace(tzinfo=None) if fecha else None
    except ValueError:
        doc.fecha_timbrado = None
    doc.proveedor_timbrado = nombre
    doc.estado = FD_TIMBRADO
    doc.ultimo_error = None
    db.commit()
    db.refresh(doc)
    return doc


def _rechazo(db: Session, doc: FiscalDocument, error: ErrorProveedor) -> DocumentoError:
    """Rechazo definitivo: no hay UUID. Por datos vuelve a borrador; por causas ajenas sigue sellado."""
    doc.ultimo_error = _error_dict(error)
    doc.timbrado_enviado_at = None
    if error.categoria not in CATEGORIAS_REENVIABLES:
        doc.estado = FD_BORRADOR
        doc.validado_at = None
    db.commit()
    codigo = f" ({error.codigo_sat or error.codigo_proveedor})" if (error.codigo_sat or error.codigo_proveedor) else ""
    status = 502 if error.categoria in CATEGORIAS_REENVIABLES else 422
    return DocumentoError(f"No se timbró{codigo}: {error.mensaje}", status)


def timbrar(
    db: Session, org_id: str, documento_id: str, servicios: ServiciosTimbrado, *, user_id: str | None = None
) -> FiscalDocument:
    """Sella (si hace falta) y timbra. Idempotente: un documento timbrado se devuelve tal cual."""
    doc = docs.obtener(db, org_id, documento_id)
    if doc.estado == FD_TIMBRADO:
        return doc
    if doc.estado in FD_CON_UUID:
        raise DocumentoError("Esta factura ya está timbrada y tiene una cancelación en curso o terminada.", 409)
    if doc.estado == FD_BORRADOR:
        raise DocumentoError("Valida la factura antes de timbrarla.", 409)
    if doc.estado == FD_LISTO:
        # La validación pudo envejecer (ventana de 72 horas, catálogos): se repite justo antes de sellar.
        _doc, resultado = docs.validar(db, org_id, documento_id)
        if not resultado.listo:
            primero = resultado.problemas[0]
            raise DocumentoError(f"La factura ya no pasa la validación previa: {primero.mensaje}", 422)

    doc = _bloquear(db, org_id, documento_id)
    if doc.estado == FD_TIMBRADO:
        return doc
    if doc.estado == FD_LISTO:
        _sellar(db, doc, user_id, servicios)
        doc = _bloquear(db, org_id, documento_id)
    if doc.estado != FD_SELLADO:
        raise DocumentoError("La factura cambió mientras se timbraba; vuelve a abrirla.", 409)

    proveedor = servicios.proveedor
    nombre = servicios.nombre_proveedor
    sellado = _xml(db, doc, XML_SELLADO)
    if sellado is None:  # no debería pasar: SELLADO sin XML
        raise DocumentoError("Falta el XML sellado de esta factura. Avisa a soporte.", 500)
    xml_sellado = bytes(sellado.contenido)

    if doc.timbrado_enviado_at is not None:
        # Hubo un envío sin desenlace conocido: consultar antes de reenviar.
        if doc.proveedor_timbrado and doc.proveedor_timbrado != nombre:
            raise DocumentoError(
                f"Esta factura se envió a {doc.proveedor_timbrado} y no supimos el resultado. "
                "Hay que consultarlo con ese proveedor antes de usar otro, para no timbrarla dos veces.",
                409,
            )
        sin_desenlace = doc.ultimo_error is None
        if sin_desenlace and _ahora() - _utc(doc.timbrado_enviado_at) < ENVIO_EN_CURSO:
            raise DocumentoError("Esta factura se está timbrando en este momento. Espera unos segundos.", 409)
        r = proveedor.consultar_timbrado(xml_sellado, doc.id_idempotente)
        _bitacora(
            db,
            doc,
            BITACORA_CONSULTA_TIMBRADO,
            user_id,
            proveedor=nombre,
            uuid_fiscal=r.uuid,
            resultado=r.estado.value,
            codigo=r.error.codigo_proveedor if r.error else None,
            mensaje=r.error.mensaje_proveedor if r.error else None,
            segundos=r.segundos,
        )
        if r.estado == Estado.TIMBRADO:
            return _registrar_timbre(db, doc, r, xml_sellado, user_id, nombre)
        if r.estado == Estado.INDETERMINADO:
            doc.ultimo_error = _error_dict(r.error)
            db.commit()
            raise ProveedorSinRespuesta(
                "El proveedor sigue sin responder. La factura quedó sellada y no se reenviará hasta saber si ya se timbró. "
                "Intenta de nuevo en unos minutos."
            )
        if r.estado == Estado.RECHAZADO:
            raise _rechazo(db, doc, r.error or normalizar_error(None))
        # NO_ENCONTRADO: nunca llegó; se puede enviar.

    # Guardar antes de enviar: la marca de envío queda en la base antes de la llamada.
    doc.timbrado_enviado_at = _ahora()
    doc.timbrado_intentos = (doc.timbrado_intentos or 0) + 1
    doc.proveedor_timbrado = nombre
    doc.ultimo_error = None
    db.commit()

    r = proveedor.timbrar(xml_sellado, doc.id_idempotente)
    doc = _bloquear(db, org_id, documento_id)
    if r.estado == Estado.TIMBRADO:
        return _registrar_timbre(db, doc, r, xml_sellado, user_id, nombre)
    _bitacora(
        db,
        doc,
        BITACORA_TIMBRADO,
        user_id,
        proveedor=nombre,
        resultado=r.estado.value,
        codigo=r.error.codigo_proveedor if r.error else None,
        mensaje=r.error.mensaje_proveedor if r.error else None,
        segundos=r.segundos,
    )
    if r.estado == Estado.RECHAZADO:
        raise _rechazo(db, doc, r.error or normalizar_error(None))
    doc.ultimo_error = _error_dict(r.error)
    db.commit()
    raise ProveedorSinRespuesta(
        "El proveedor no respondió. La factura quedó sellada; al reintentar primero consultaremos si ya se timbró, "
        "para no timbrarla dos veces."
    )


# ---------------------------------------------------------------- cancelar


def _validar_sustitucion(db: Session, doc: FiscalDocument, motivo: str, folio: str | None) -> str | None:
    if motivo != "01":
        if folio:
            raise DocumentoError("Sólo el motivo 01 lleva la factura que sustituye a ésta.", 422)
        return None
    if not folio:
        raise DocumentoError(
            "El motivo 01 exige el folio fiscal (UUID) de la factura que sustituye a ésta. Timbra primero la nueva.",
            422,
        )
    folio = folio.strip().upper()
    if not _UUID.match(folio):
        raise DocumentoError("El folio fiscal de la factura que sustituye no tiene formato de UUID.", 422)
    if folio == (doc.uuid_fiscal or "").upper():
        raise DocumentoError("Una factura no se sustituye a sí misma.", 422)
    sustituta = (
        db.query(FiscalDocument)
        .filter(FiscalDocument.organization_id == doc.organization_id, FiscalDocument.uuid_fiscal == folio)
        .first()
    )
    if sustituta is None or sustituta.estado != FD_TIMBRADO:
        raise DocumentoError(
            "La factura que sustituye debe estar timbrada en Atlas Financials y vigente. Timbra primero la nueva.",
            422,
        )
    return folio


def cancelar(
    db: Session,
    org_id: str,
    documento_id: str,
    motivo: str,
    folio_sustitucion: str | None,
    servicios: ServiciosTimbrado,
    *,
    user_id: str | None = None,
) -> FiscalDocument:
    doc = _bloquear(db, org_id, documento_id)
    reintento = (
        doc.estado == FD_CANCELACION_EN_PROCESO
        and (doc.ultimo_error or {}).get("categoria") == Categoria.SIN_RESPUESTA.value
    )
    if doc.estado == FD_CANCELADO:
        raise DocumentoError("Esta factura ya está cancelada ante el SAT.", 409)
    if doc.estado == FD_CANCELACION_EN_PROCESO and not reintento:
        raise DocumentoError("Ya hay una solicitud de cancelación en proceso. Consulta el estatus.", 409)
    if doc.estado not in (FD_TIMBRADO, FD_CANCELACION_RECHAZADA, FD_CANCELACION_EN_PROCESO):
        raise DocumentoError("Sólo se cancela una factura timbrada.", 409)
    if motivo not in MOTIVOS:
        raise DocumentoError("El motivo de cancelación debe ser 01, 02, 03 o 04.", 422)
    folio = _validar_sustitucion(db, doc, motivo, folio_sustitucion)

    proveedor = servicios.proveedor
    firmante = _firmante(servicios, doc)
    try:
        revisar_certificado(firmante, doc.emisor_rfc, _ahora())
        solicitud = armar_solicitud(
            firmante,
            doc.emisor_rfc,
            [FolioCancelacion(doc.uuid_fiscal, motivo, folio)],
            _fecha_local(doc),
            algoritmo=proveedor.algoritmo_cancelacion,
            folio_sustitucion_vacio=proveedor.folio_sustitucion_vacio,
        )
    except (ErrorCancelacion, ErrorSellado, ErrorFirmante) as exc:
        raise DocumentoError(str(exc), 409) from exc

    _bitacora(
        db,
        doc,
        BITACORA_FIRMA_CANCELACION,
        user_id,
        no_certificado=numero_certificado(firmante.certificado()),
        sha256=hashlib.sha256(solicitud).hexdigest(),
        firmante=firmante.tipo,
        uuid_fiscal=doc.uuid_fiscal,
        resultado="firmado",
        codigo=motivo,
    )
    estado_previo = FD_TIMBRADO if doc.estado == FD_CANCELACION_EN_PROCESO else doc.estado
    doc.cancelacion_motivo = motivo
    doc.cancelacion_folio_sustitucion = folio
    doc.cancelacion_solicitada_at = _ahora()
    doc.cancellation_reason = MOTIVOS[motivo]
    doc.estado = FD_CANCELACION_EN_PROCESO
    doc.ultimo_error = None
    db.commit()

    r = proveedor.cancelar(solicitud)
    doc = _bloquear(db, org_id, documento_id)
    _bitacora(
        db,
        doc,
        BITACORA_CANCELACION,
        user_id,
        proveedor=proveedor.nombre,
        uuid_fiscal=doc.uuid_fiscal,
        resultado=r.estado.value,
        codigo=(r.error.codigo_proveedor if r.error else ",".join(sorted(set(r.estatus_uuid.values()))) or None),
        mensaje=r.error.mensaje_proveedor if r.error else None,
        segundos=r.segundos,
    )
    if r.acuse:
        _guardar_xml(db, doc, XML_ACUSE_CANCELACION, r.acuse)
    if r.estado == EstadoCancelacion.ACEPTADA:
        doc.estatus_cancelacion_sat = "Solicitud recibida"
        db.commit()
        db.refresh(doc)
        return doc
    if r.estado == EstadoCancelacion.RECHAZADA:
        doc.estado = estado_previo
        doc.ultimo_error = _error_dict(r.error)
        db.commit()
        codigo = f" ({r.error.codigo_sat or r.error.codigo_proveedor})" if r.error and r.error.codigo_proveedor else ""
        raise DocumentoError(f"No se pudo solicitar la cancelación{codigo}: {r.error.mensaje if r.error else ''}", 422)
    doc.ultimo_error = _error_dict(r.error)
    db.commit()
    raise ProveedorSinRespuesta(
        "El proveedor no respondió a la solicitud de cancelación. Consulta el estatus en unos minutos; "
        "si no llegó, puedes volver a pedirla."
    )


# ---------------------------------------------------------------- estatus


def consultar_estatus(
    db: Session,
    org_id: str,
    documento_id: str,
    servicios: ServiciosTimbrado | None,
    *,
    user_id: str | None = None,
) -> FiscalDocument:
    """Consulta el estatus ante el SAT (si hay UUID y proveedor) y actualiza la cancelación."""
    doc = docs.obtener(db, org_id, documento_id)
    if servicios is None or doc.estado not in FD_CON_UUID or doc.estado == FD_CANCELADO:
        return doc
    doc = _bloquear(db, org_id, documento_id)
    r = servicios.proveedor.consultar_estatus(
        doc.uuid_fiscal,
        doc.emisor_rfc or "",
        doc.receptor_rfc or "",
        f"{doc.total:.2f}",
        _sello(db, doc),
    )
    _bitacora(
        db,
        doc,
        BITACORA_ESTATUS,
        user_id,
        proveedor=servicios.nombre_proveedor,
        uuid_fiscal=doc.uuid_fiscal,
        resultado=(r.estado or "sin_respuesta")[:30],
        codigo=(r.codigo or "")[:40] or None,
        mensaje=r.estatus_cancelacion,
        segundos=r.segundos,
    )
    if r.estado is None:
        db.commit()
        db.refresh(doc)
        return doc
    doc.estatus_sat = r.estado
    doc.es_cancelable = r.es_cancelable
    doc.estatus_cancelacion_sat = r.estatus_cancelacion
    doc.estatus_consultado_at = _ahora()
    estado_sat = (r.estado or "").lower()
    cancelacion = (r.estatus_cancelacion or "").lower()
    if estado_sat == "cancelado":
        doc.estado = FD_CANCELADO
        doc.cancelled_at = doc.cancelled_at or _ahora()
    elif doc.estado == FD_CANCELACION_EN_PROCESO and "rechazada" in cancelacion:
        doc.estado = FD_CANCELACION_RECHAZADA
    db.commit()
    db.refresh(doc)
    return doc


def _sello(db: Session, doc: FiscalDocument) -> str | None:
    timbrado = _xml(db, doc, XML_TIMBRADO)
    if timbrado is None:
        return None
    return parsear(bytes(timbrado.contenido)).get("Sello")


def xml_timbrado(db: Session, org_id: str, documento_id: str) -> tuple[FiscalDocument, bytes]:
    doc = docs.obtener(db, org_id, documento_id)
    fila = _xml(db, doc, XML_TIMBRADO)
    if fila is None:
        raise DocumentoError("Esta factura aún no está timbrada.", 404)
    return doc, bytes(fila.contenido)
