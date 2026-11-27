"""Desglose de IVA.

El usuario captura el TOTAL (lo que dice el ticket) y elige la tasa; aquí se
obtiene la base. El impuesto se calcula por DIFERENCIA, nunca recalculado:
así `subtotal + impuesto == total` es exacto y la partida doble no arrastra
centavos de deriva.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from app.services.accounting.engine import _quantize

# Tasas admitidas en México (general, frontera, tasa 0 / exento).
ALLOWED_RATES = (Decimal("0.16"), Decimal("0.08"), Decimal("0"))


# Tratamiento de IVA (R2·HU-05). La tasa da el monto; el tratamiento dice POR
# QUÉ una operación no lleva IVA, que para el SAT no es lo mismo:
#   TAXED        gravado al 16 % u 8 %
#   ZERO_RATED   gravado a tasa 0 % (cuenta como actividad gravada)
#   EXEMPT       exento (p. ej. ciertos servicios médicos; lo confirma contabilidad)
#   NOT_OBJECT   no objeto del impuesto
#   UNCLASSIFIED sin clasificar: tasa 0 que nadie ha revisado. Es un pendiente,
#                no un tratamiento; el reporte de IVA lo señala.
TAX_TREATMENTS = ("TAXED", "ZERO_RATED", "EXEMPT", "NOT_OBJECT", "UNCLASSIFIED")
UNTAXED_TREATMENTS = ("ZERO_RATED", "EXEMPT", "NOT_OBJECT", "UNCLASSIFIED")


@dataclass(frozen=True)
class TaxBreakdown:
    total: Decimal
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    tax_treatment: str = "UNCLASSIFIED"


def resolve_treatment(rate: Decimal, treatment: str | None, current: str | None = None) -> str:
    """Tratamiento coherente con la tasa.

    Sin tratamiento explícito: con IVA es gravado; sin IVA se conserva el que
    ya tenía la operación si no era gravado, y si no, queda sin clasificar:
    el sistema nunca decide que algo es exento.
    """
    rate = Decimal(rate)
    if treatment is None:
        if rate > 0:
            return "TAXED"
        return current if current in UNTAXED_TREATMENTS else "UNCLASSIFIED"
    if treatment not in TAX_TREATMENTS:
        raise ValueError("Ese tratamiento de IVA no existe.")
    if treatment == "TAXED" and rate == 0:
        raise ValueError("Una operación gravada necesita tasa de 16 % u 8 %; para 0 % elige tasa 0, exento o no objeto.")
    if treatment != "TAXED" and rate > 0:
        raise ValueError("Sólo una operación gravada lleva IVA: cambia la tasa a 0 o el tratamiento a gravado.")
    return treatment


def retention_from_rate(subtotal: Decimal, rate: Decimal | None, amount: Decimal | None) -> Decimal:
    """Retención por tasa sobre la base (subtotal) o por importe capturado.

    Con tasa, el importe se calcula; si además viene un importe distinto, es un
    error de captura y se rechaza en vez de elegir uno en silencio.
    """
    amount = _quantize(amount or 0)
    if rate is None:
        return amount
    computed = _quantize(Decimal(subtotal) * Decimal(rate))
    if amount and abs(amount - computed) > Decimal("0.01"):
        raise ValueError(
            f"La retención capturada (${amount:,.2f}) no coincide con la tasa sobre la base (${computed:,.2f})."
        )
    return computed


def split_total(total: Decimal, tax_rate: Decimal) -> TaxBreakdown:
    """Separa un total en base gravable e impuesto."""
    total = _quantize(total)
    rate = Decimal(tax_rate)
    if rate < 0 or rate > 1:
        raise ValueError("La tasa de impuesto no es válida.")
    if rate == 0:
        return TaxBreakdown(total=total, subtotal=total, tax_rate=Decimal("0"), tax_amount=Decimal("0"))
    subtotal = _quantize(total / (Decimal("1") + rate))
    return TaxBreakdown(
        total=total, subtotal=subtotal, tax_rate=rate, tax_amount=total - subtotal, tax_treatment="TAXED"
    )


def with_treatment(breakdown: TaxBreakdown, treatment: str | None, current: str | None = None) -> TaxBreakdown:
    return replace(breakdown, tax_treatment=resolve_treatment(breakdown.tax_rate, treatment, current))


def proportional_tax(tax_amount: Decimal, paid: Decimal, total: Decimal, remaining_tax: Decimal) -> Decimal:
    """Impuesto que corresponde a un cobro/pago parcial.

    El último abono liquida el remanente exacto para que la cuenta de IVA
    pendiente cierre en cero, sin residuos de centavos.
    """
    tax_amount = Decimal(tax_amount)
    if tax_amount == 0:
        return Decimal("0")
    paid = Decimal(paid)
    total = Decimal(total)
    if paid >= total:
        return _quantize(remaining_tax)
    share = _quantize(tax_amount * paid / total)
    return min(share, _quantize(remaining_tax))
