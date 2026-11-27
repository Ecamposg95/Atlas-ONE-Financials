"""Fechas de lo que ya movió dinero (R2·REQ-04).

Un gasto pagado, un ingreso cobrado, un traspaso, un pago o un cobro ya
ocurrieron: no pueden tener fecha posterior a hoy. «Hoy» es el de la empresa
(su zona horaria), no el del servidor. Lo pendiente sí puede ir al futuro: es
un compromiso, no dinero que se movió.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.organization import Organization

PENDING_HINT = "Si es un pago futuro, regístralo como pendiente."
WHEN_IT_HAPPENS_HINT = "Regístralo el día que ocurra."


def company_today(db: Session, org_id: str) -> date:
    """El «hoy» de la empresa, en su zona horaria."""
    # Import diferido: el tablero importa medio dominio y aquí sólo hace falta la fecha.
    from app.domains.dashboard.today import local_today

    return local_today(db.get(Organization, org_id))


def assert_not_future(db: Session, org_id: str, when: date | None, hint: str = PENDING_HINT) -> None:
    """Rechaza (ValueError → 400) una fecha posterior al hoy de la empresa."""
    if when is None:
        return
    today = company_today(db, org_id)
    if when > today:
        raise ValueError(
            f"La fecha no puede ser posterior a hoy ({today.strftime('%d/%m/%Y')}): "
            f"lo pagado ya ocurrió. {hint}"
        )
