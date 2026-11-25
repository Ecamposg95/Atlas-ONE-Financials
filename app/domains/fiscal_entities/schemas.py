from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domains.fiscal_mx.schemas import FiscalReadiness, SatKey


class FiscalEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    tax_id: str | None = Field(default=None, max_length=13)
    regime: str | None = Field(default=None, max_length=80)
    sort_order: int = Field(default=0, ge=0)
    # Emisor de CFDI cuando la operación lleva este contribuyente.
    legal_name: str | None = Field(default=None, max_length=255)
    fiscal_regime: SatKey = Field(default=None, max_length=3)
    fiscal_postal_code: SatKey = Field(default=None, max_length=5)


class FiscalEntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tax_id: str | None = Field(default=None, max_length=13)
    regime: str | None = Field(default=None, max_length=80)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    legal_name: str | None = Field(default=None, max_length=255)
    fiscal_regime: SatKey = Field(default=None, max_length=3)
    fiscal_postal_code: SatKey = Field(default=None, max_length=5)


class FiscalEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tax_id: str | None
    regime: str | None
    active: bool
    sort_order: int
    created_at: datetime
    legal_name: str | None = None
    fiscal_regime: str | None = None
    fiscal_postal_code: str | None = None

    @computed_field
    @property
    def fiscal_readiness(self) -> FiscalReadiness:
        from app.domains.fiscal_mx.service import emisor_readiness

        return FiscalReadiness(
            **emisor_readiness(self.tax_id, self.legal_name, self.fiscal_regime, self.fiscal_postal_code)
        )
