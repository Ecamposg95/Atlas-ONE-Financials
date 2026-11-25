"""Contribuyentes (entidades fiscales): alta y edición. Nunca se borran."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.fiscal_mx.service import check_emisor
from app.models.fiscal_entity import FiscalEntity


def _assert_name_free(db: Session, organization_id: str, name: str, exclude_id: str | None) -> None:
    query = db.query(FiscalEntity).filter(
        FiscalEntity.organization_id == organization_id,
        func.lower(FiscalEntity.name) == name.lower(),
    )
    if exclude_id:
        query = query.filter(FiscalEntity.id != exclude_id)
    taken = query.first()
    if taken is not None:
        raise ValueError(f"Ya existe un contribuyente llamado {taken.name}.")


def _clean_tax_id(raw: str | None) -> str | None:
    return (raw or "").strip().upper() or None


def create_fiscal_entity(db: Session, organization_id: str, payload) -> FiscalEntity:
    name = payload.name.strip()
    _assert_name_free(db, organization_id, name, None)
    fiscal = check_emisor(
        None,
        {
            "tax_id": _clean_tax_id(payload.tax_id),
            "fiscal_regime": payload.fiscal_regime,
            "fiscal_postal_code": payload.fiscal_postal_code,
        },
    )
    entity = FiscalEntity(
        organization_id=organization_id,
        name=name,
        regime=(payload.regime or "").strip() or None,
        legal_name=(payload.legal_name or "").strip() or None,
        sort_order=payload.sort_order,
        **fiscal,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def update_fiscal_entity(db: Session, entity: FiscalEntity, payload) -> FiscalEntity:
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        _assert_name_free(db, entity.organization_id, changes["name"], entity.id)
    if "tax_id" in changes:
        changes["tax_id"] = _clean_tax_id(changes["tax_id"])
    if "regime" in changes:
        changes["regime"] = (changes["regime"] or "").strip() or None
    if "legal_name" in changes:
        changes["legal_name"] = (changes["legal_name"] or "").strip() or None
    changes = check_emisor(entity, changes)
    for field, value in changes.items():
        setattr(entity, field, value)
    db.commit()
    db.refresh(entity)
    return entity
