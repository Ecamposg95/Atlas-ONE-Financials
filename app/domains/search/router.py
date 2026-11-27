"""Búsqueda general (R2·HU-21): el buscador de la barra (Ctrl K) encuentra
ingresos, gastos, cuentas por pagar y cobrar, clientes y proveedores.

Texto: concepto, referencia, notas; nombre, razón social o RFC del contacto.
Si lo escrito es una cantidad ("1,160" o "$1160.00"), también busca ese monto.
Siempre filtrado por empresa; pocos resultados por tipo, lo más reciente primero.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contact import Customer, Vendor
from app.models.expense import Expense
from app.models.income import Income
from app.models.payable import Payable
from app.models.receivable import Receivable
from app.security.deps import get_current_org_id

router = APIRouter(tags=["search"])

PER_KIND = 5

# tipo → (modelo, ruta en la interfaz, sustantivo)
OPERATIONS = (
    ("expense", Expense, "/gastos", "Gasto"),
    ("income", Income, "/ingresos", "Ingreso"),
    ("payable", Payable, "/por-pagar", "Por pagar"),
    ("receivable", Receivable, "/por-cobrar", "Por cobrar"),
)


def _amount(text: str) -> Decimal | None:
    cleaned = re.sub(r"[\s$,]", "", text)
    if not re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=100),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    text = q.strip()
    pattern = f"%{text}%"
    amount = _amount(text)
    results: list[dict] = []

    for kind, model, path, noun in OPERATIONS:
        conditions = [model.description.ilike(pattern), model.notes.ilike(pattern)]
        if hasattr(model, "reference"):
            conditions.append(model.reference.ilike(pattern))
        if amount is not None:
            conditions.append(model.amount == amount)
        rows = (
            db.query(model)
            .filter(model.organization_id == org_id, or_(*conditions))
            .order_by(model.date.desc(), model.created_at.desc())
            .limit(PER_KIND)
            .all()
        )
        for row in rows:
            results.append(
                {
                    "kind": kind,
                    "id": row.id,
                    "title": row.description,
                    "noun": noun,
                    "date": row.date,
                    "amount": row.amount,
                    "status": row.status,
                    "to": f"{path}?open={row.id}",
                }
            )

    for kind, model, path, noun in (
        ("customer", Customer, "/clientes", "Cliente"),
        ("vendor", Vendor, "/proveedores", "Proveedor"),
    ):
        rows = (
            db.query(model)
            .filter(
                model.organization_id == org_id,
                model.deleted_at.is_(None),
                or_(model.name.ilike(pattern), model.legal_name.ilike(pattern), model.tax_id.ilike(pattern)),
            )
            .order_by(model.name)
            .limit(PER_KIND)
            .all()
        )
        for row in rows:
            results.append(
                {
                    "kind": kind,
                    "id": row.id,
                    "title": row.name,
                    "noun": noun,
                    "date": None,
                    "amount": None,
                    "status": row.status,
                    "to": f"{path}?q={quote(row.name)}",
                }
            )
    return {"items": results, "total": len(results), "limit": PER_KIND, "offset": 0}
