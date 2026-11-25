"""Catálogos del SAT para los selectores de captura (régimen, uso, forma y método de pago)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.domains.fiscal_mx.schemas import SatOption
from app.security.deps import get_current_org_id
from app.services.cfdi import datos_fiscales as df

router = APIRouter(prefix="/fiscal-mx", tags=["fiscal-mx"])


@router.get("/catalogs/{nombre}")
def list_catalog(
    nombre: str,
    persona: Literal["fisica", "moral"] | None = Query(default=None),
    regimen: str | None = Query(default=None, max_length=3),
    rfc: str | None = Query(default=None, max_length=20),
    _org_id: str = Depends(get_current_org_id),
):
    """Claves vigentes hoy. ``rfc`` deduce el tipo de persona; ``regimen`` filtra los usos de CFDI."""
    if nombre not in df.CATALOGOS_PARA_CAPTURA:
        raise HTTPException(status_code=404, detail="Ese catálogo no está disponible para captura.")
    persona_moral = None if persona is None else persona == "moral"
    if persona_moral is None and rfc:
        persona_moral = df.persona_de_rfc(rfc)
    items = [SatOption(**fila) for fila in df.opciones(nombre, persona_moral=persona_moral, regimen=regimen)]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}
