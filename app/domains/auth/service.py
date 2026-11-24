from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.organization import Organization
from app.models.user import User
from app.security.passwords import hash_password, verify_password
from app.services.onboarding import provision_organization

logger = logging.getLogger("arca.auth")


class AccountLocked(Exception):
    """La cuenta está bloqueada por contraseñas fallidas; `minutes` es lo que falta."""

    def __init__(self, minutes: int) -> None:
        super().__init__(f"Cuenta bloqueada {minutes} min")
        self.minutes = minutes


def _aware(value: datetime | None) -> datetime | None:
    # SQLite devuelve fechas sin zona; en BD siempre se guardan en UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def register_user(
    db: Session,
    email: str,
    password: str,
    name: str,
    business_name: str,
    business_type: str | None = None,
    initial_cash=None,
) -> tuple[User, Organization]:
    """Cadena completa de onboarding (task pack §29). Hace commit."""
    normalized_email = email.strip().lower()
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing is not None:
        raise ValueError("Ya existe una cuenta con este correo.")

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        name=name.strip(),
    )
    db.add(user)
    db.flush()

    organization = provision_organization(
        db,
        user,
        business_name=business_name,
        business_type=business_type,
        initial_cash=initial_cash,
    )
    db.commit()
    db.refresh(user)
    db.refresh(organization)
    logger.info("registro: usuario=%s organización=%s", user.id, organization.id)
    return user, organization


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Valida credenciales. Hace commit cuando cambia el contador de fallos.

    Tras `login_max_failures` contraseñas incorrectas seguidas la cuenta queda
    bloqueada `login_lock_minutes`; mientras dure, ni la contraseña correcta
    entra (lanza `AccountLocked`).
    """
    settings = get_settings()
    user = db.query(User).filter(User.email == email.strip().lower()).with_for_update().first()
    if user is None:
        logger.warning("login fallido: correo desconocido")
        return None

    now = datetime.now(timezone.utc)
    locked_until = _aware(user.locked_until)
    if locked_until is not None and locked_until > now:
        logger.warning("login fallido: cuenta bloqueada usuario=%s", user.id)
        db.rollback()  # suelta el candado de la fila
        raise AccountLocked(max(1, math.ceil((locked_until - now).total_seconds() / 60)))

    if not verify_password(password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= settings.login_max_failures:
            user.failed_login_count = 0
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            logger.warning("login fallido: cuenta bloqueada por intentos usuario=%s", user.id)
        else:
            logger.warning("login fallido: contraseña incorrecta usuario=%s", user.id)
        db.commit()
        return None

    if user.status != "ACTIVE":
        logger.warning("login fallido: usuario inactivo usuario=%s", user.id)
        db.rollback()
        return None

    if user.failed_login_count or user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None
    db.commit()
    db.refresh(user)
    return user
