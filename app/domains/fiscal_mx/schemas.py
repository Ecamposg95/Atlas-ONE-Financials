"""Piezas de schema compartidas para los datos fiscales de CFDI.

Aquí sólo se normaliza (mayúsculas, sin espacios). La validación contra los
catálogos del SAT necesita el estado completo del registro (RFC + régimen + uso)
y vive en ``app/domains/fiscal_mx/service.py``, que responde 400 en español.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _clave(valor):
    if valor is None:
        return None
    if not isinstance(valor, str):
        return valor
    limpio = "".join(valor.split()).upper()
    return limpio or None


SatKey = Annotated[str | None, BeforeValidator(_clave)]


class FiscalReadiness(BaseModel):
    """¿Listo para facturar? ``faltantes`` impide timbrar; ``advertencias`` no."""

    listo: bool
    faltantes: list[str]
    advertencias: list[str]


class CfdiOperationFields(BaseModel):
    """Uso de CFDI, forma (c_FormaPago) y método (PUE/PPD) de pago del SAT, todos opcionales."""

    cfdi_use: SatKey = Field(default=None, max_length=4)
    cfdi_payment_form: SatKey = Field(default=None, max_length=2)
    cfdi_payment_method: SatKey = Field(default=None, max_length=3)


class SatOption(BaseModel):
    clave: str
    descripcion: str


# ---------------------------------------------------------------- documentos fiscales

_Dinero = Annotated[Decimal, Field(allow_inf_nan=False)]


class RenglonIn(BaseModel):
    """Renglón de la factura. La suma (importe − descuento) debe dar el subtotal de la operación."""

    descripcion: str = Field(min_length=1, max_length=1000)
    cantidad: _Dinero = Field(gt=0, max_digits=20, decimal_places=6)
    valor_unitario: _Dinero = Field(gt=0, max_digits=20, decimal_places=6)
    descuento: _Dinero | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    clave_prod_serv: str | None = Field(default=None, pattern=r"^[0-9]{8}$")
    clave_unidad: SatKey = Field(default=None, max_length=3)
    unidad: str | None = Field(default=None, max_length=20)
    no_identificacion: str | None = Field(default=None, max_length=100)


class ArmadoIn(BaseModel):
    """Opciones al preparar o volver a preparar la factura."""

    tratamiento_iva: Literal["gravado", "tasa_0", "exento", "no_objeto"] | None = None
    clave_prod_serv: str | None = Field(default=None, pattern=r"^[0-9]{8}$")
    clave_unidad: SatKey = Field(default=None, max_length=3)
    conceptos: list[RenglonIn] | None = Field(default=None, max_length=200)


class DocumentoCreate(ArmadoIn):
    origen_tipo: Literal["income", "receivable"]
    origen_id: str = Field(min_length=1, max_length=36)
    serie: str = Field(default="A", min_length=1, max_length=25, pattern=r"^[A-Za-z0-9-]{1,25}$")


class ImpuestoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tipo: str
    impuesto: str
    tipo_factor: str
    tasa_o_cuota: Decimal | None
    base: Decimal
    importe: Decimal | None


class ConceptoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    orden: int
    clave_prod_serv: str
    no_identificacion: str | None
    cantidad: Decimal
    clave_unidad: str
    unidad: str | None
    descripcion: str
    valor_unitario: Decimal
    importe: Decimal
    descuento: Decimal | None
    objeto_imp: str
    impuestos: list[ImpuestoRead]


class ProblemaRead(BaseModel):
    codigo: str
    campo: str
    mensaje: str


class ValidacionRead(BaseModel):
    listo: bool
    problemas: list[ProblemaRead]
    advertencias: list[ProblemaRead]


class ErrorTimbradoRead(BaseModel):
    """Último rechazo o falta de respuesta del proveedor, ya en español."""

    categoria: str
    mensaje: str
    codigo_proveedor: str | None = None
    codigo_sat: str | None = None
    at: str | None = None


class DocumentoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo_comprobante: str
    estado: str
    origen_tipo: str
    origen_id: str
    emisor_fiscal_entity_id: str | None
    emisor_rfc: str | None
    emisor_nombre: str | None
    emisor_regimen: str | None
    receptor_customer_id: str | None
    receptor_rfc: str | None
    receptor_nombre: str | None
    receptor_regimen: str | None
    receptor_domicilio_fiscal: str | None
    receptor_uso_cfdi: str | None
    serie: str
    folio: str
    fecha_emision: datetime
    huso_horario: str | None
    lugar_expedicion: str | None
    moneda: str
    exportacion: str
    forma_pago: str | None
    metodo_pago: str | None
    subtotal: Decimal
    descuento: Decimal | None
    total_impuestos_trasladados: Decimal | None
    total_impuestos_retenidos: Decimal | None
    total: Decimal
    supuestos: list[str]
    validado_at: datetime | None
    validacion: ValidacionRead | None
    uuid_fiscal: str | None
    no_certificado: str | None = None
    proveedor_timbrado: str | None = None
    rfc_prov_certif: str | None = None
    fecha_timbrado: datetime | None = None
    ultimo_error: ErrorTimbradoRead | None = None
    cancelacion_motivo: str | None = None
    cancelacion_folio_sustitucion: str | None = None
    cancelacion_solicitada_at: datetime | None = None
    cancelled_at: datetime | None = None
    estatus_sat: str | None = None
    estatus_cancelacion_sat: str | None = None
    conceptos: list[ConceptoRead]
    created_at: datetime
    # Hasta timbrar, nada de esto tiene validez fiscal.
    validez_fiscal: bool = False


# ---------------------------------------------------------------- timbrado y cancelación


class CancelacionIn(BaseModel):
    motivo: Literal["01", "02", "03", "04"]
    # Sólo con motivo 01: UUID de la factura (ya timbrada) que sustituye a ésta.
    folio_sustitucion: str | None = Field(default=None, max_length=36)


class EstatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    estado: str
    validez_fiscal: bool
    uuid_fiscal: str | None
    proveedor_timbrado: str | None
    rfc_prov_certif: str | None
    fecha_timbrado: datetime | None
    timbrado_intentos: int
    ultimo_error: ErrorTimbradoRead | None
    cancelacion_motivo: str | None
    cancelacion_solicitada_at: datetime | None
    cancelled_at: datetime | None
    estatus_sat: str | None
    es_cancelable: str | None
    estatus_cancelacion_sat: str | None
    estatus_consultado_at: datetime | None
    # False mientras el timbrado esté apagado: el estatus es sólo el guardado, sin consultar al SAT.
    timbrado_disponible: bool = False
