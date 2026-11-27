"""Sobre de paginación canónico Atlas: {items, total, limit, offset}. Único en todo el API."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import case, func

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def paginate(query, limit: int, offset: int, schema, sum_column=None, sum_where=None, sums: dict | None = None) -> dict:
    """Aplica limit/offset a un query ya filtrado por organización y serializa.

    `sum_column` agrega el total monetario de TODO el filtro (no sólo de la
    página): mostrar la suma de una página sería engañoso. `sum_where` deja
    fuera lo que no debe sumar (lo cancelado) y `sums` agrega otros totales
    con nombre (saldo, vencido), con la misma condición.
    """
    total = query.count()
    rows = query.limit(limit).offset(offset).all()
    page = {
        "items": [schema.model_validate(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    columns = {}
    if sum_column is not None:
        columns["total_amount"] = sum_column
    columns.update(sums or {})
    if columns:
        def summed(expression):
            if sum_where is not None:
                expression = case((sum_where, expression), else_=0)
            return func.coalesce(func.sum(expression), 0)

        values = query.with_entities(*[summed(expression) for expression in columns.values()]).order_by(None).one()
        page.update(dict(zip(columns.keys(), values, strict=True)))
        if sum_where is not None:
            page["sum_excludes_cancelled"] = True
    return page


def apply_sort(query, sort: str | None, allowed: dict, default: tuple):
    """Orden por columna con whitelist explícita.

    `sort="-amount"` ordena descendente. Un campo fuera de la whitelist se
    rechaza con 422: ordenarse por columnas arbitrarias expondría detalles
    internos y permitiría sondear el modelo. El orden por defecto del recurso
    se conserva como desempate para que la paginación sea estable.
    """
    from fastapi import HTTPException

    if not sort:
        return query.order_by(*default)
    descending = sort.startswith("-")
    field = sort[1:] if descending else sort
    column = allowed.get(field)
    if column is None:
        raise HTTPException(
            status_code=422,
            detail=f"No se puede ordenar por '{field}'. Campos válidos: {', '.join(sorted(allowed))}.",
        )
    return query.order_by(column.desc() if descending else column.asc(), *default)


# R2·HU-05: ver TAX_TREATMENTS en app/services/taxes.py.
TaxTreatment = Literal["TAXED", "ZERO_RATED", "EXEMPT", "NOT_OBJECT", "UNCLASSIFIED"]
