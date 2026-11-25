"""Documento fiscal (CFDI 4.0) de la capa de localización mexicana (ADR-013).

Un documento fiscal se liga a la operación que lo origina (ingreso o cuenta
por cobrar) pero no la modifica ni crea pólizas: la operación ya está en el
libro por su cuenta. Emisor y receptor se guardan como **fotografía** de lo
que llevará el XML; si después cambia el cliente, el documento sólo cambia al
rearmarlo, mientras siga en borrador.

Los XML que valen fiscalmente (sellado, timbrado, acuse de cancelación) van en
``documentos_fiscales_xml`` como bytes inmutables: una fila por tipo y
documento, que nunca se actualiza ni se borra (evento de SQLAlchemy aquí y
disparador en PostgreSQL). Van en PostgreSQL, como los adjuntos, porque el
disco de Railway es efímero y aún no hay bucket; separados del documento para
que listar no cargue bytes. El XML sin sellar no se guarda: se regenera
determinísticamente del documento.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.mixins import AuditMixin, TenantMixin, UUIDPKMixin, _utcnow

# Ciclo de vida. En este PR sólo se alcanzan BORRADOR y LISTO_PARA_TIMBRAR;
# los demás quedan para el sellado y el timbrado (ADR-017 y ADR-018).
FD_BORRADOR = "BORRADOR"
FD_LISTO = "LISTO_PARA_TIMBRAR"
FD_SELLADO = "SELLADO"
FD_TIMBRADO = "TIMBRADO"
FD_CANCELACION_EN_PROCESO = "CANCELACION_EN_PROCESO"
FD_CANCELADO = "CANCELADO"
FD_DESCARTADO = "DESCARTADO"
FISCAL_DOCUMENT_STATUSES = (
    FD_BORRADOR,
    FD_LISTO,
    FD_SELLADO,
    FD_TIMBRADO,
    FD_CANCELACION_EN_PROCESO,
    FD_CANCELADO,
    FD_DESCARTADO,
)
# Estados que todavía se pueden rearmar desde la operación.
FD_EDITABLES = (FD_BORRADOR, FD_LISTO)
# Estados que ocupan la operación: no se prepara otro documento mientras exista uno.
FD_ACTIVOS = (FD_BORRADOR, FD_LISTO, FD_SELLADO, FD_TIMBRADO, FD_CANCELACION_EN_PROCESO)

ORIGEN_INGRESO = "income"
ORIGEN_CXC = "receivable"
ORIGENES = (ORIGEN_INGRESO, ORIGEN_CXC)

XML_SELLADO = "SELLADO"
XML_TIMBRADO = "TIMBRADO"
XML_ACUSE_CANCELACION = "ACUSE_CANCELACION"
XML_TIPOS = (XML_SELLADO, XML_TIMBRADO, XML_ACUSE_CANCELACION)

IMPUESTO_TRASLADO = "TRASLADO"
IMPUESTO_RETENCION = "RETENCION"


class FiscalDocument(Base, UUIDPKMixin, TenantMixin, AuditMixin):
    __tablename__ = "documentos_fiscales"
    __table_args__ = (
        CheckConstraint(
            "(income_id IS NOT NULL AND receivable_id IS NULL) OR (income_id IS NULL AND receivable_id IS NOT NULL)",
            name="ck_documentos_fiscales_un_origen",
        ),
        # Serie y folio no se repiten por emisor (empresa o contribuyente).
        UniqueConstraint("organization_id", "emisor_clave", "serie", "folio", name="uq_documentos_fiscales_folio"),
        Index("ix_documentos_fiscales_origen", "organization_id", "origen_tipo", "origen_id"),
    )

    tipo_comprobante = Column(String(1), nullable=False, default="I")  # c_TipoDeComprobante
    estado = Column(String(30), nullable=False, default=FD_BORRADOR)  # FISCAL_DOCUMENT_STATUSES

    # Operación de origen: exactamente una.
    origen_tipo = Column(String(20), nullable=False)  # ORIGENES
    origen_id = Column(String(36), nullable=False)
    income_id = Column(String(36), ForeignKey("incomes.id"), nullable=True)
    receivable_id = Column(String(36), ForeignKey("receivables.id"), nullable=True)

    # Emisor: la empresa (fiscal_entity_id nulo) o un contribuyente de la empresa.
    emisor_fiscal_entity_id = Column(String(36), ForeignKey("fiscal_entities.id"), nullable=True)
    emisor_clave = Column(String(36), nullable=False)  # fiscal_entity_id u organization_id
    emisor_rfc = Column(String(13), nullable=True)
    emisor_nombre = Column(String(300), nullable=True)
    emisor_regimen = Column(String(3), nullable=True)

    # Receptor: fotografía del cliente al armar.
    receptor_customer_id = Column(String(36), ForeignKey("customers.id"), nullable=True)
    receptor_rfc = Column(String(13), nullable=True)
    receptor_nombre = Column(String(300), nullable=True)
    receptor_regimen = Column(String(3), nullable=True)
    receptor_domicilio_fiscal = Column(String(5), nullable=True)
    receptor_uso_cfdi = Column(String(4), nullable=True)

    serie = Column(String(25), nullable=False)
    folio = Column(String(40), nullable=False)
    # Fecha del atributo Fecha: hora local del lugar de expedición, sin zona.
    fecha_emision = Column(DateTime(timezone=False), nullable=False)
    fecha_emision_utc = Column(DateTime(timezone=True), nullable=False)
    huso_horario = Column(String(60), nullable=True)
    lugar_expedicion = Column(String(5), nullable=True)  # c_CodigoPostal

    moneda = Column(String(3), nullable=False, default="MXN")
    tipo_cambio = Column(Numeric(18, 6), nullable=True)
    exportacion = Column(String(2), nullable=False, default="01")
    forma_pago = Column(String(2), nullable=True)
    metodo_pago = Column(String(3), nullable=True)

    subtotal = Column(Numeric(14, 2), nullable=False)
    descuento = Column(Numeric(14, 2), nullable=True)
    total_impuestos_trasladados = Column(Numeric(14, 2), nullable=True)
    total_impuestos_retenidos = Column(Numeric(14, 2), nullable=True)
    total = Column(Numeric(14, 2), nullable=False)

    # Supuestos aplicados al armar (p. ej. concepto único), para el contador.
    supuestos = Column(JSON, nullable=False, default=list)
    validado_at = Column(DateTime(timezone=True), nullable=True)
    validacion = Column(JSON, nullable=True)  # último resultado: {listo, problemas, advertencias}

    # Timbre (siguiente PR).
    uuid_fiscal = Column(String(36), nullable=True, unique=True)
    proveedor_timbrado = Column(String(40), nullable=True)
    rfc_prov_certif = Column(String(13), nullable=True)
    fecha_timbrado = Column(DateTime(timezone=False), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(String(500), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    @property
    def validez_fiscal(self) -> bool:
        """Sólo un CFDI timbrado (y no cancelado) vale ante el SAT."""
        return self.estado == FD_TIMBRADO

    conceptos = relationship(
        "FiscalDocumentConcept",
        order_by="FiscalDocumentConcept.orden",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class FiscalDocumentConcept(Base, UUIDPKMixin, TenantMixin):
    __tablename__ = "documentos_fiscales_conceptos"
    __table_args__ = (UniqueConstraint("documento_id", "orden", name="uq_documentos_fiscales_conceptos_orden"),)

    documento_id = Column(String(36), ForeignKey("documentos_fiscales.id"), nullable=False, index=True)
    orden = Column(Integer, nullable=False)
    clave_prod_serv = Column(String(8), nullable=False)  # c_ClaveProdServ
    no_identificacion = Column(String(100), nullable=True)
    cantidad = Column(Numeric(20, 6), nullable=False)
    clave_unidad = Column(String(3), nullable=False)  # c_ClaveUnidad
    unidad = Column(String(20), nullable=True)
    descripcion = Column(String(1000), nullable=False)
    valor_unitario = Column(Numeric(20, 6), nullable=False)
    importe = Column(Numeric(14, 2), nullable=False)
    descuento = Column(Numeric(14, 2), nullable=True)
    objeto_imp = Column(String(2), nullable=False)  # c_ObjetoImp

    impuestos = relationship(
        "FiscalDocumentConceptTax",
        order_by="FiscalDocumentConceptTax.orden",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class FiscalDocumentConceptTax(Base, UUIDPKMixin, TenantMixin):
    __tablename__ = "documentos_fiscales_impuestos"

    concepto_id = Column(String(36), ForeignKey("documentos_fiscales_conceptos.id"), nullable=False, index=True)
    orden = Column(Integer, nullable=False, default=0)
    tipo = Column(String(10), nullable=False)  # TRASLADO | RETENCION
    impuesto = Column(String(3), nullable=False)  # c_Impuesto
    tipo_factor = Column(String(6), nullable=False)  # Tasa | Cuota | Exento
    tasa_o_cuota = Column(Numeric(8, 6), nullable=True)
    base = Column(Numeric(14, 2), nullable=False)
    importe = Column(Numeric(14, 2), nullable=True)


class FiscalDocumentXml(Base, UUIDPKMixin, TenantMixin):
    """Bytes de un XML con valor fiscal. Se escriben una vez y no cambian."""

    __tablename__ = "documentos_fiscales_xml"
    __table_args__ = (UniqueConstraint("documento_id", "tipo", name="uq_documentos_fiscales_xml_tipo"),)

    documento_id = Column(String(36), ForeignKey("documentos_fiscales.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # XML_TIPOS
    contenido = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class XmlInmutable(RuntimeError):
    pass


@event.listens_for(FiscalDocumentXml, "before_update")
def _xml_no_se_actualiza(_mapper, _connection, _target):
    raise XmlInmutable("Un XML fiscal guardado no se modifica: reconstruirlo invalida el sello.")


@event.listens_for(FiscalDocumentXml, "before_delete")
def _xml_no_se_borra(_mapper, _connection, _target):
    raise XmlInmutable("Un XML fiscal guardado no se borra.")


class FiscalSeries(Base, UUIDPKMixin, TenantMixin):
    """Contador de folios por emisor y serie; se toma bajo lock de fila."""

    __tablename__ = "documentos_fiscales_series"
    __table_args__ = (UniqueConstraint("organization_id", "emisor_clave", "serie", name="uq_documentos_fiscales_series"),)

    emisor_clave = Column(String(36), nullable=False)
    serie = Column(String(25), nullable=False)
    siguiente_folio = Column(Integer, nullable=False, default=1)
