"""«Hoy» de la empresa, no del servidor (R2·HU-09.b).

El servidor corre en UTC: a las 18:00 de México ya sería mañana y una cuenta
que vence hoy saldría vencida. Todo lo vencido, la antigüedad y los cortes por
defecto se calculan con la fecha local de la zona de la organización.

Donde hay `db` y `organization_id` se usa `organization_today`. Los schemas de
lectura (que calculan `is_overdue` sin contexto) usan `company_today`, que lee
la zona de la empresa activa de la petición: el middleware abre un contenedor
por petición y `get_current_membership` le pone la zona de la empresa.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

DEFAULT_TIMEZONE = "America/Mexico_City"


def _utcnow() -> datetime:
    """El reloj, aparte para poder congelarlo en pruebas."""
    return datetime.now(timezone.utc)


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_date(timezone_name: str | None, now: datetime | None = None) -> date:
    """La fecha de hoy en la zona dada; una zona inválida cae a la de México."""
    return (now or _utcnow()).astimezone(_zone(timezone_name)).date()


def organization_today(db: Session, organization_id: str, now: datetime | None = None) -> date:
    from app.models.organization import Organization

    organization = db.get(Organization, organization_id)
    return local_date(organization.timezone if organization else None, now)


class _RequestDay:
    __slots__ = ("timezone",)

    def __init__(self) -> None:
        self.timezone: str | None = None


# Un contenedor mutable por petición: las dependencias síncronas corren en
# otro hilo con una copia del contexto, así que no basta con `set()` ahí; el
# objeto compartido sí llega a la serialización de la respuesta.
_request_day: ContextVar[_RequestDay | None] = ContextVar("company_request_day", default=None)


def use_company_timezone(timezone_name: str | None) -> None:
    holder = _request_day.get()
    if holder is not None:
        holder.timezone = timezone_name


def company_today(now: datetime | None = None) -> date:
    """Hoy en la zona de la empresa de la petición en curso (México si no hay)."""
    holder = _request_day.get()
    return local_date(holder.timezone if holder else None, now)


class CompanyDayMiddleware:
    """Middleware ASGI: un contenedor de zona horaria nuevo por petición."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _request_day.set(_RequestDay())
        try:
            await self.app(scope, receive, send)
        finally:
            _request_day.reset(token)
