"""Clientes y proveedores: mismo contrato, dos tablas (factory compartido)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.fiscal_mx.schemas import FiscalReadiness, SatKey
from app.domains.fiscal_mx.service import check_receptor
from app.models.contact import Customer, Vendor
from app.models.organization import WRITE_ROLES
from app.schemas.common import paginate
from app.security.deps import get_current_org_id, require_role
from app.services.change_log import record_change, snapshot


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)


class ContactUpdate(ContactCreate):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    legal_name: str | None
    tax_id: str | None
    email: str | None
    phone: str | None
    notes: str | None
    status: str
    created_at: datetime


class _ReceptorFields(BaseModel):
    """Receptor de CFDI. Razón social = legal_name, RFC = tax_id (XAXX010101000 y
    XEXX010101000 valen como genéricos). Se validan en ``fiscal_mx.service``."""

    fiscal_regime: SatKey = Field(default=None, max_length=3)
    fiscal_postal_code: SatKey = Field(default=None, max_length=5)
    default_cfdi_use: SatKey = Field(default=None, max_length=4)


class CustomerCreate(ContactCreate, _ReceptorFields):
    pass


class CustomerUpdate(ContactUpdate, _ReceptorFields):
    pass


class CustomerRead(ContactRead):
    fiscal_regime: str | None = None
    fiscal_postal_code: str | None = None
    default_cfdi_use: str | None = None

    @computed_field
    @property
    def fiscal_readiness(self) -> FiscalReadiness:
        """Qué le falta al cliente para poder facturarle (lo calcula el backend)."""
        from app.domains.fiscal_mx.service import receptor_readiness

        return FiscalReadiness(
            **receptor_readiness(
                self.tax_id, self.legal_name, self.fiscal_regime, self.fiscal_postal_code, self.default_cfdi_use
            )
        )


def _no_checks(_current, changes: dict) -> dict:
    return changes


def build_contact_router(
    model,
    prefix: str,
    not_found_detail: str,
    create_schema: type[BaseModel] = ContactCreate,
    update_schema: type[BaseModel] = ContactUpdate,
    read_schema: type[BaseModel] = ContactRead,
    check=_no_checks,
) -> APIRouter:
    router = APIRouter(prefix=f"/{prefix}", tags=[prefix])
    # Sin `from __future__ import annotations` en este módulo: las anotaciones de
    # los endpoints se evalúan aquí y FastAPI ve el schema de cada tipo de contacto.
    CreateSchema, UpdateSchema, ReadSchema = create_schema, update_schema, read_schema  # noqa: N806

    def _get(db: Session, org_id: str, contact_id: str):
        contact = (
            db.query(model)
            .filter(
                model.id == contact_id,
                model.organization_id == org_id,
                model.deleted_at.is_(None),
            )
            .first()
        )
        if contact is None:
            raise HTTPException(status_code=404, detail=not_found_detail)
        return contact

    @router.get("")
    def list_contacts(
        q: str | None = Query(default=None, max_length=100),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_db),
        org_id: str = Depends(get_current_org_id),
    ):
        query = db.query(model).filter(
            model.organization_id == org_id,
            model.deleted_at.is_(None),
        )
        if q:
            pattern = f"%{q}%"
            query = query.filter(or_(model.name.ilike(pattern), model.legal_name.ilike(pattern)))
        query = query.order_by(model.name)
        return paginate(query, limit, offset, ReadSchema)

    @router.post("", response_model=ReadSchema, status_code=201)
    def create_contact(
        payload: CreateSchema,
        db: Session = Depends(get_db),
        org_id: str = Depends(get_current_org_id),
        _membership=Depends(require_role(WRITE_ROLES)),
    ):
        contact = model(organization_id=org_id, **check(None, payload.model_dump()))
        db.add(contact)
        db.flush()
        record_change(db, org_id, contact, "CREATE", _membership.user_id)
        db.commit()
        db.refresh(contact)
        return ReadSchema.model_validate(contact)

    @router.get("/{contact_id}", response_model=ReadSchema)
    def get_contact(
        contact_id: str,
        db: Session = Depends(get_db),
        org_id: str = Depends(get_current_org_id),
    ):
        return ReadSchema.model_validate(_get(db, org_id, contact_id))

    @router.patch("/{contact_id}", response_model=ReadSchema)
    def update_contact(
        contact_id: str,
        payload: UpdateSchema,
        db: Session = Depends(get_db),
        org_id: str = Depends(get_current_org_id),
        _membership=Depends(require_role(WRITE_ROLES)),
    ):
        contact = _get(db, org_id, contact_id)
        before = snapshot(contact)
        for field, value in check(contact, payload.model_dump(exclude_unset=True)).items():
            setattr(contact, field, value)
        record_change(db, org_id, contact, "UPDATE", _membership.user_id, before=before, after=snapshot(contact))
        db.commit()
        db.refresh(contact)
        return ReadSchema.model_validate(contact)

    @router.delete("/{contact_id}", status_code=204)
    def delete_contact(
        contact_id: str,
        db: Session = Depends(get_db),
        org_id: str = Depends(get_current_org_id),
        _membership=Depends(require_role(WRITE_ROLES)),
    ):
        contact = _get(db, org_id, contact_id)
        before = snapshot(contact)
        contact.deleted_at = datetime.now(timezone.utc)
        contact.status = "INACTIVE"
        record_change(db, org_id, contact, "DELETE", _membership.user_id, before=before, after=snapshot(contact))
        db.commit()

    return router


customers_router = build_contact_router(
    Customer,
    "customers",
    "El cliente no existe.",
    create_schema=CustomerCreate,
    update_schema=CustomerUpdate,
    read_schema=CustomerRead,
    check=check_receptor,
)
vendors_router = build_contact_router(Vendor, "vendors", "El proveedor no existe.")
