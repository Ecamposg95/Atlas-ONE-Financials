"""Documentos fiscales: borrador de CFDI 4.0 de ingreso desde un ingreso o una cuenta por cobrar.

Capa de localización (ADR-013): lee la operación, el cliente, la empresa y el
contribuyente; escribe sólo en las tablas ``documentos_fiscales*``. No llama a
``post_journal_entry`` ni a ``record_transaction`` y no cambia la operación:
facturar no es reconocer ingreso ni cobrar.

Sin sellado ni timbrado: eso depende del servicio de llaves (ADR-017) y del
proveedor (ADR-018) y llega en el siguiente paso.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.contact import Customer
from app.models.fiscal_document import (
    FD_ACTIVOS,
    FD_BORRADOR,
    FD_EDITABLES,
    FD_LISTO,
    FD_SELLADO,
    IMPUESTO_RETENCION,
    IMPUESTO_TRASLADO,
    ORIGEN_CXC,
    ORIGEN_INGRESO,
    FiscalDocument,
    FiscalDocumentConcept,
    FiscalDocumentConceptTax,
    FiscalSeries,
)
from app.models.fiscal_entity import FiscalEntity
from app.models.income import Income
from app.models.organization import Organization
from app.models.receivable import Receivable
from app.services.cfdi import datos_fiscales as df
from app.services.cfdi import validacion as val
from app.services.cfdi.armado import ErrorArmado, Operacion, Renglon, armar
from app.services.cfdi.comprobante import (
    RETENCION,
    TRASLADO,
    Comprobante,
    Concepto,
    Emisor,
    Impuesto,
    Receptor,
    resumir,
    xml_sin_sellar,
)
from app.services.cfdi.zona_horaria import CodigoPostalSinHuso, hora_local

LEYENDA_BORRADOR = (
    "BORRADOR SIN SELLO NI TIMBRE - NO TIENE VALIDEZ FISCAL. Generado por Atlas ONE Financials para revision; "
    "NoCertificado, Sello y Certificado van vacios."
)
SERIE_DEFECTO = "A"
# Sin código postal no hay huso: se usa el del centro y la validación pide el código postal.
_DIFERENCIA_CENTRO = -6


class DocumentoError(Exception):
    def __init__(self, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.status = status


@dataclass(frozen=True)
class OpcionesArmado:
    serie: str = SERIE_DEFECTO
    tratamiento_iva: str | None = None
    clave_prod_serv: str | None = None
    clave_unidad: str | None = None
    renglones: tuple[Renglon, ...] = ()


def _ahora() -> dt.datetime:
    """Punto único para la hora actual (las pruebas lo sustituyen)."""
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- lectura


def _operacion(db: Session, org_id: str, origen_tipo: str, origen_id: str) -> Income | Receivable:
    modelo = {ORIGEN_INGRESO: Income, ORIGEN_CXC: Receivable}.get(origen_tipo)
    if modelo is None:
        raise DocumentoError("Sólo se factura desde un ingreso o una cuenta por cobrar.")
    operacion = db.query(modelo).filter(modelo.id == origen_id, modelo.organization_id == org_id).first()
    if operacion is None:
        que = "El ingreso" if origen_tipo == ORIGEN_INGRESO else "La cuenta por cobrar"
        raise DocumentoError(f"{que} no existe.", 404)
    return operacion


def obtener(db: Session, org_id: str, documento_id: str) -> FiscalDocument:
    doc = (
        db.query(FiscalDocument)
        .filter(FiscalDocument.id == documento_id, FiscalDocument.organization_id == org_id)
        .first()
    )
    if doc is None:
        raise DocumentoError("La factura no existe.", 404)
    return doc


def listar(
    db: Session,
    org_id: str,
    *,
    origen_tipo: str | None = None,
    origen_id: str | None = None,
    estado: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FiscalDocument], int]:
    query = db.query(FiscalDocument).filter(FiscalDocument.organization_id == org_id)
    if origen_tipo:
        query = query.filter(FiscalDocument.origen_tipo == origen_tipo)
    if origen_id:
        query = query.filter(FiscalDocument.origen_id == origen_id)
    if estado:
        query = query.filter(FiscalDocument.estado == estado)
    total = query.count()
    filas = query.order_by(FiscalDocument.created_at.desc(), FiscalDocument.id).offset(offset).limit(limit).all()
    return filas, total


# ---------------------------------------------------------------- folio


def _siguiente_folio(db: Session, org_id: str, emisor_clave: str, serie: str) -> str:
    def _bloquear():
        return (
            db.query(FiscalSeries)
            .filter(
                FiscalSeries.organization_id == org_id,
                FiscalSeries.emisor_clave == emisor_clave,
                FiscalSeries.serie == serie,
            )
            .with_for_update()
            .first()
        )

    contador = _bloquear()
    if contador is None:
        try:
            with db.begin_nested():
                contador = FiscalSeries(organization_id=org_id, emisor_clave=emisor_clave, serie=serie, siguiente_folio=1)
                db.add(contador)
                db.flush()
        except IntegrityError:
            contador = _bloquear()
    numero = contador.siguiente_folio
    contador.siguiente_folio = numero + 1
    db.flush()
    return str(numero)


# ---------------------------------------------------------------- armado


def _emisor(db: Session, org_id: str, operacion) -> tuple[str | None, str, Emisor, str | None]:
    """(fiscal_entity_id, emisor_clave, datos del emisor, código postal de expedición)."""
    if operacion.fiscal_entity_id:
        entidad = (
            db.query(FiscalEntity)
            .filter(FiscalEntity.id == operacion.fiscal_entity_id, FiscalEntity.organization_id == org_id)
            .first()
        )
        if entidad is not None:
            emisor = Emisor(
                rfc=df.normalizar_rfc(entidad.tax_id), nombre=entidad.legal_name, regimen_fiscal=entidad.fiscal_regime
            )
            return entidad.id, entidad.id, emisor, entidad.fiscal_postal_code
    org = db.get(Organization, org_id)
    emisor = Emisor(rfc=df.normalizar_rfc(org.tax_id), nombre=org.legal_name, regimen_fiscal=org.fiscal_regime)
    return None, org_id, emisor, org.fiscal_postal_code


def _fecha(lugar: str | None, supuestos: list[str]) -> tuple[dt.datetime, dt.datetime, str | None]:
    ahora = _ahora()
    try:
        if not lugar:
            raise CodigoPostalSinHuso("sin código postal")
        hora = hora_local(lugar, ahora)
        return hora.local, hora.utc, hora.huso
    except CodigoPostalSinHuso:
        supuestos.append("Sin código postal de expedición válido la fecha se calculó con la hora del centro (UTC−6).")
        utc = ahora.astimezone(dt.timezone.utc).replace(microsecond=0)
        return (utc + dt.timedelta(hours=_DIFERENCIA_CENTRO)).replace(tzinfo=None), utc, None


def _operacion_numeros(operacion) -> Operacion:
    return Operacion(
        descripcion=operacion.description,
        subtotal=Decimal(operacion.subtotal),
        impuesto=Decimal(operacion.tax_amount),
        total=Decimal(operacion.amount),
        tasa=Decimal(operacion.tax_rate).normalize() if Decimal(operacion.tax_rate) else Decimal("0"),
    )


def _llenar(db: Session, org_id: str, doc: FiscalDocument, operacion, opciones: OpcionesArmado) -> None:
    if operacion.status == "CANCELLED":
        raise DocumentoError("La operación está cancelada: no se puede facturar.", 409)
    if not operacion.customer_id:
        raise DocumentoError(
            "La operación no tiene cliente. Asígnale uno (puede ser con RFC genérico XAXX010101000) antes de preparar la factura."
        )
    customer = (
        db.query(Customer).filter(Customer.id == operacion.customer_id, Customer.organization_id == org_id).first()
    )
    if customer is None:
        raise DocumentoError("El cliente de la operación no existe.", 404)

    try:
        armado = armar(
            _operacion_numeros(operacion),
            tratamiento=opciones.tratamiento_iva,
            renglones=list(opciones.renglones) or None,
            clave_prod_serv=opciones.clave_prod_serv,
            clave_unidad=opciones.clave_unidad,
        )
    except ErrorArmado as exc:
        raise DocumentoError(str(exc), 422) from exc

    supuestos = list(armado.supuestos)
    entidad_id, emisor_clave, emisor, lugar = _emisor(db, org_id, operacion)
    rfc_receptor = df.normalizar_rfc(customer.tax_id)
    domicilio = customer.fiscal_postal_code
    if df.es_generico(rfc_receptor):
        domicilio = lugar
        supuestos.append("Con RFC genérico el código postal del cliente es el del lugar de expedición (regla CFDI40149).")
    uso = operacion.cfdi_use or customer.default_cfdi_use
    if not operacion.cfdi_use and customer.default_cfdi_use:
        supuestos.append(f"Uso de CFDI {customer.default_cfdi_use}: el que tiene el cliente por omisión.")
    fecha_local, fecha_utc, huso = _fecha(lugar, supuestos)

    resumen = resumir(armado.conceptos)
    doc.income_id = operacion.id if isinstance(operacion, Income) else None
    doc.receivable_id = operacion.id if isinstance(operacion, Receivable) else None
    doc.emisor_fiscal_entity_id = entidad_id
    doc.emisor_clave = emisor_clave
    doc.emisor_rfc, doc.emisor_nombre, doc.emisor_regimen = emisor.rfc, emisor.nombre, emisor.regimen_fiscal
    doc.receptor_customer_id = customer.id
    doc.receptor_rfc = rfc_receptor
    doc.receptor_nombre = customer.legal_name
    doc.receptor_regimen = customer.fiscal_regime
    doc.receptor_domicilio_fiscal = domicilio
    doc.receptor_uso_cfdi = uso
    doc.fecha_emision, doc.fecha_emision_utc, doc.huso_horario = fecha_local, fecha_utc, huso
    doc.lugar_expedicion = lugar
    doc.moneda = "MXN"
    doc.tipo_cambio = None
    doc.exportacion = "01"
    doc.forma_pago = operacion.cfdi_payment_form
    doc.metodo_pago = operacion.cfdi_payment_method
    doc.subtotal = resumen.subtotal
    doc.descuento = resumen.descuento
    doc.total_impuestos_trasladados = resumen.total_trasladados
    doc.total_impuestos_retenidos = resumen.total_retenidos
    doc.total = resumen.total
    doc.supuestos = supuestos
    doc.estado = FD_BORRADOR
    doc.validado_at = None
    doc.validacion = None

    doc.conceptos.clear()
    db.flush()
    for orden, c in enumerate(armado.conceptos, start=1):
        concepto = FiscalDocumentConcept(
            organization_id=org_id,
            orden=orden,
            clave_prod_serv=c.clave_prod_serv,
            no_identificacion=c.no_identificacion,
            cantidad=c.cantidad,
            clave_unidad=c.clave_unidad,
            unidad=c.unidad,
            descripcion=c.descripcion,
            valor_unitario=c.valor_unitario,
            importe=c.importe,
            descuento=c.descuento,
            objeto_imp=c.objeto_imp,
        )
        for i, imp in enumerate(c.impuestos):
            concepto.impuestos.append(
                FiscalDocumentConceptTax(
                    organization_id=org_id,
                    orden=i,
                    tipo=IMPUESTO_TRASLADO if imp.tipo == TRASLADO else IMPUESTO_RETENCION,
                    impuesto=imp.impuesto,
                    tipo_factor=imp.tipo_factor,
                    tasa_o_cuota=imp.tasa_o_cuota,
                    base=imp.base,
                    importe=imp.importe,
                )
            )
        doc.conceptos.append(concepto)


def crear_borrador(
    db: Session, org_id: str, origen_tipo: str, origen_id: str, opciones: OpcionesArmado, *, user_id: str | None = None
) -> FiscalDocument:
    operacion = _operacion(db, org_id, origen_tipo, origen_id)
    existente = (
        db.query(FiscalDocument)
        .filter(
            FiscalDocument.organization_id == org_id,
            FiscalDocument.origen_tipo == origen_tipo,
            FiscalDocument.origen_id == origen_id,
            FiscalDocument.estado.in_(FD_ACTIVOS),
        )
        .first()
    )
    if existente is not None:
        raise DocumentoError(
            f"Esta operación ya tiene la factura {existente.serie}-{existente.folio} en estado "
            f"{existente.estado.replace('_', ' ').lower()}; ábrela o vuelve a prepararla.",
            409,
        )
    doc = FiscalDocument(organization_id=org_id, origen_tipo=origen_tipo, origen_id=origen_id, created_by=user_id)
    _llenar(db, org_id, doc, operacion, opciones)
    doc.serie = opciones.serie
    doc.folio = _siguiente_folio(db, org_id, doc.emisor_clave, opciones.serie)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def rearmar(db: Session, org_id: str, documento_id: str, opciones: OpcionesArmado) -> FiscalDocument:
    """Vuelve a tomar los datos de la operación, el cliente y el emisor; refecha. Conserva serie y folio."""
    doc = obtener(db, org_id, documento_id)
    if doc.estado not in FD_EDITABLES:
        raise DocumentoError("Sólo un borrador se puede volver a preparar.", 409)
    operacion = _operacion(db, org_id, doc.origen_tipo, doc.origen_id)
    emisor_antes = doc.emisor_clave
    _llenar(db, org_id, doc, operacion, opciones)
    if doc.emisor_clave != emisor_antes:
        # Cambió el contribuyente que emite: el folio es por emisor.
        doc.folio = _siguiente_folio(db, org_id, doc.emisor_clave, doc.serie)
    db.commit()
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------- comprobante, validación y XML


def comprobante(doc: FiscalDocument) -> Comprobante:
    conceptos = [
        Concepto(
            clave_prod_serv=c.clave_prod_serv,
            cantidad=Decimal(c.cantidad),
            clave_unidad=c.clave_unidad,
            descripcion=c.descripcion,
            valor_unitario=Decimal(c.valor_unitario),
            importe=Decimal(c.importe),
            objeto_imp=c.objeto_imp,
            descuento=None if c.descuento is None else Decimal(c.descuento),
            unidad=c.unidad,
            no_identificacion=c.no_identificacion,
            impuestos=[
                Impuesto(
                    tipo=TRASLADO if i.tipo == IMPUESTO_TRASLADO else RETENCION,
                    impuesto=i.impuesto,
                    tipo_factor=i.tipo_factor,
                    tasa_o_cuota=None if i.tasa_o_cuota is None else Decimal(i.tasa_o_cuota),
                    base=Decimal(i.base),
                    importe=None if i.importe is None else Decimal(i.importe),
                )
                for i in c.impuestos
            ],
        )
        for c in doc.conceptos
    ]
    _dec = lambda v: None if v is None else Decimal(v)  # noqa: E731
    return Comprobante(
        serie=doc.serie,
        folio=doc.folio,
        fecha=doc.fecha_emision,
        lugar_expedicion=doc.lugar_expedicion,
        emisor=Emisor(rfc=doc.emisor_rfc, nombre=doc.emisor_nombre, regimen_fiscal=doc.emisor_regimen),
        receptor=Receptor(
            rfc=doc.receptor_rfc,
            nombre=doc.receptor_nombre,
            domicilio_fiscal=doc.receptor_domicilio_fiscal,
            regimen_fiscal=doc.receptor_regimen,
            uso_cfdi=doc.receptor_uso_cfdi,
        ),
        conceptos=conceptos,
        subtotal=Decimal(doc.subtotal),
        total=Decimal(doc.total),
        descuento=_dec(doc.descuento),
        total_impuestos_trasladados=_dec(doc.total_impuestos_trasladados),
        total_impuestos_retenidos=_dec(doc.total_impuestos_retenidos),
        moneda=doc.moneda,
        tipo_cambio=_dec(doc.tipo_cambio),
        forma_pago=doc.forma_pago,
        metodo_pago=doc.metodo_pago,
        tipo_de_comprobante=doc.tipo_comprobante,
        exportacion=doc.exportacion,
    )


def _utc(valor: dt.datetime) -> dt.datetime:
    # SQLite devuelve fechas sin zona aunque la columna sea timezone=True.
    return valor if valor.tzinfo else valor.replace(tzinfo=dt.timezone.utc)


def validar(db: Session, org_id: str, documento_id: str) -> tuple[FiscalDocument, val.Validacion]:
    doc = obtener(db, org_id, documento_id)
    if doc.estado not in FD_EDITABLES:
        raise DocumentoError("Esta factura ya no es un borrador: no se vuelve a validar aquí.", 409)
    operacion = _operacion(db, org_id, doc.origen_tipo, doc.origen_id)
    contexto = val.Contexto(
        ahora_utc=_ahora(),
        fecha_emision_utc=_utc(doc.fecha_emision_utc),
        operacion=_operacion_numeros(operacion),
        operacion_cancelada=operacion.status == "CANCELLED",
        operacion_liquidada=operacion.status == "PAID",
    )
    resultado = val.validar(comprobante(doc), contexto)
    doc.validacion = resultado.como_dict()
    doc.validado_at = _ahora()
    doc.estado = FD_LISTO if resultado.listo else FD_BORRADOR
    db.commit()
    db.refresh(doc)
    return doc, resultado


def xml_borrador(db: Session, org_id: str, documento_id: str) -> tuple[FiscalDocument, bytes]:
    doc = obtener(db, org_id, documento_id)
    return doc, xml_sin_sellar(comprobante(doc), leyenda=LEYENDA_BORRADOR)


def xml_para_impresion(db: Session, org_id: str, documento_id: str) -> tuple[FiscalDocument, bytes]:
    """El XML del que sale el PDF: el timbrado si existe, si no el sellado y, si no, el borrador.

    El PDF se arma del XML (la fuente de verdad), nunca de las filas de la base.
    """
    from app.models.fiscal_document import XML_SELLADO, XML_TIMBRADO, FiscalDocumentXml

    doc = obtener(db, org_id, documento_id)
    # Puede haber varios sellados (un rechazo por datos obliga a sellar otra vez):
    # vale el de secuencia mayor, y sólo mientras el documento siga SELLADO; si
    # volvió a borrador, lo vigente es el borrador.
    guardados = {
        x.tipo: x.contenido
        for x in db.query(FiscalDocumentXml)
        .filter(
            FiscalDocumentXml.organization_id == org_id,
            FiscalDocumentXml.documento_id == doc.id,
            FiscalDocumentXml.tipo.in_((XML_TIMBRADO, XML_SELLADO)),
        )
        .order_by(FiscalDocumentXml.secuencia)
    }
    if XML_TIMBRADO in guardados:
        return doc, bytes(guardados[XML_TIMBRADO])
    if XML_SELLADO in guardados and doc.estado == FD_SELLADO:
        return doc, bytes(guardados[XML_SELLADO])
    return doc, xml_sin_sellar(comprobante(doc), leyenda=LEYENDA_BORRADOR)
