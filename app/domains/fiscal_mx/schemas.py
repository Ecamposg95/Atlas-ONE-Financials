"""Piezas de schema compartidas para los datos fiscales de CFDI.

Aquí sólo se normaliza (mayúsculas, sin espacios). La validación contra los
catálogos del SAT necesita el estado completo del registro (RFC + régimen + uso)
y vive en ``app/domains/fiscal_mx/service.py``, que responde 400 en español.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field


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
