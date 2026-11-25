"""Datos fiscales para CFDI sobre los registros de la empresa (ADR-013).

Valida con el estado combinado (lo guardado + lo que cambia) porque las reglas
cruzan campos: el tipo de persona sale del RFC, el régimen depende de él y el
uso de CFDI del régimen. Sólo se revisa lo que se toca, para no bloquear la
edición de registros viejos capturados antes de estas reglas; lo que siga mal
aparece en el indicador de "listo para facturar".

Nada aquí toca pólizas ni saldos.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.contact import Customer
from app.services.cfdi import datos_fiscales as df

EMISOR_FIELDS = ("tax_id", "fiscal_regime", "fiscal_postal_code")
RECEPTOR_FIELDS = ("tax_id", "fiscal_regime", "fiscal_postal_code", "default_cfdi_use")
OPERATION_FIELDS = ("cfdi_use", "cfdi_payment_form", "cfdi_payment_method")


def _merged(current: Any, changes: dict, field: str):
    if field in changes:
        return changes[field]
    return getattr(current, field, None) if current is not None else None


def _normalize_tax_id(changes: dict) -> None:
    if "tax_id" in changes:
        changes["tax_id"] = df.normalizar_rfc(changes["tax_id"])
        if changes["tax_id"] is not None:
            df.revisar_rfc(changes["tax_id"])


def check_emisor(current: Any, changes: dict) -> dict:
    """Empresa o contribuyente que emite. Devuelve los cambios normalizados."""
    _normalize_tax_id(changes)
    if not any(field in changes for field in EMISOR_FIELDS):
        return changes
    rfc = _merged(current, changes, "tax_id")
    if "tax_id" in changes and df.es_generico(rfc):
        raise df.DatoFiscalInvalido("Un RFC genérico no puede emitir facturas; escribe el RFC de la constancia.")
    df.validar_emisor(
        rfc=None if df.es_generico(rfc) else rfc,
        regimen=_merged(current, changes, "fiscal_regime"),
        codigo_postal=_merged(current, changes, "fiscal_postal_code"),
    )
    return changes


def check_receptor(current: Any, changes: dict) -> dict:
    """Cliente que recibe la factura. Devuelve los cambios normalizados."""
    _normalize_tax_id(changes)
    if not any(field in changes for field in RECEPTOR_FIELDS):
        return changes
    df.validar_receptor(
        rfc=_merged(current, changes, "tax_id"),
        regimen=_merged(current, changes, "fiscal_regime"),
        codigo_postal=_merged(current, changes, "fiscal_postal_code"),
        uso_cfdi=_merged(current, changes, "default_cfdi_use"),
    )
    return changes


def check_operation(
    db: Session,
    org_id: str,
    *,
    customer_id: str | None,
    cfdi_use: str | None,
    cfdi_payment_form: str | None,
    cfdi_payment_method: str | None,
) -> None:
    """Uso, forma y método de pago de un ingreso o cuenta por cobrar.

    El uso se coteja con el régimen del cliente si ya lo tiene capturado; si no,
    sólo contra el catálogo (el indicador del cliente dirá qué falta).
    """
    df.validar_pago(cfdi_payment_form, cfdi_payment_method)
    if not cfdi_use:
        return
    regimen = persona = None
    if customer_id:
        customer = (
            db.query(Customer)
            .filter(Customer.id == customer_id, Customer.organization_id == org_id)
            .first()
        )
        if customer is not None:
            regimen = customer.fiscal_regime
            persona = df.persona_de_rfc(customer.tax_id)
    df.validar_uso_cfdi(cfdi_use, regimen=regimen, persona_moral=persona)


def emisor_readiness(rfc, razon_social, regimen, codigo_postal) -> dict:
    return df.preparacion_emisor(
        rfc=rfc, razon_social=razon_social, regimen=regimen, codigo_postal=codigo_postal
    ).como_dict()


def receptor_readiness(rfc, razon_social, regimen, codigo_postal, uso_cfdi) -> dict:
    return df.preparacion_receptor(
        rfc=rfc, razon_social=razon_social, regimen=regimen, codigo_postal=codigo_postal, uso_cfdi=uso_cfdi
    ).como_dict()
