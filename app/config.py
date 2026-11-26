"""Configuración de Atlas Financials.

Patrón Atlas (dasic): dataclass congelada + lru_cache, fail-fast en producción.
Sin fallback de secreto en producción, nunca.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_DEV_SECRET = "arca-dev-secret-key-not-for-production-use-0000"
_DEV_DATABASE_URL = "sqlite:///./arca_dev.db"


def _normalize_database_url(url: str) -> str:
    # Railway entrega postgres://; SQLAlchemy requiere postgresql://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    env: str
    cors_origins: tuple[str, ...]
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    docs_enabled: bool
    # Perímetro: límite de intentos (en memoria) y bloqueo de cuenta (durable).
    rate_limit_enabled: bool
    login_max_failures: int
    login_lock_minutes: int
    agent_rate_per_minute: int
    # Asistente sobre Claude (spec 2026-11-02). La llave NO vive aquí: se lee
    # en el momento de construir el cliente, para que aparezca sin reiniciar nada.
    ai_model: str
    ai_effort: str
    ai_max_tokens: int
    ai_budget_default_usd: Decimal
    # CFDI (ADR-017/018): apagado hasta que haya servicio de llaves y proveedor.
    # Detalle de valores en app/services/cfdi/configuracion.py.
    cfdi_timbrado_habilitado: bool = False
    cfdi_firmante: str = "kms"
    cfdi_proveedor: str = "prodigia"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def _build_settings() -> Settings:
    env = os.getenv("ENV", "development")
    is_production = env == "production"

    database_url = os.getenv("DATABASE_URL", "")
    secret_key = os.getenv("SECRET_KEY", "")

    if is_production:
        if not database_url:
            raise RuntimeError("DATABASE_URL debe estar definida en producción.")
        if not secret_key:
            raise RuntimeError("SECRET_KEY debe estar definida en producción.")
        if len(secret_key) < 32:
            raise RuntimeError("SECRET_KEY debe tener al menos 32 caracteres.")
    else:
        database_url = database_url or _DEV_DATABASE_URL
        secret_key = secret_key or _DEV_SECRET

    cors_origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    )

    return Settings(
        database_url=_normalize_database_url(database_url),
        secret_key=secret_key,
        env=env,
        cors_origins=cors_origins,
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720")),
        refresh_token_expire_days=int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")),
        docs_enabled=os.getenv("DOCS_ENABLED", "false" if is_production else "true").lower() == "true",
        # En pruebas se apaga: toda la suite sale de la misma IP.
        rate_limit_enabled=os.getenv("RATE_LIMIT_ENABLED", "false" if env == "test" else "true").lower() == "true",
        login_max_failures=int(os.getenv("LOGIN_MAX_FAILURES", "5")),
        login_lock_minutes=int(os.getenv("LOGIN_LOCK_MINUTES", "15")),
        agent_rate_per_minute=int(os.getenv("AGENT_RATE_PER_MINUTE", "120")),
        ai_model=os.getenv("AI_MODEL", "claude-opus-5-5"),
        ai_effort=os.getenv("AI_EFFORT", "medium"),
        ai_max_tokens=int(os.getenv("AI_MAX_TOKENS", "16000")),
        ai_budget_default_usd=Decimal(os.getenv("AI_BUDGET_DEFAULT_USD", "20")),
        cfdi_timbrado_habilitado=os.getenv("CFDI_TIMBRADO_HABILITADO", "false").lower() == "true",
        cfdi_firmante=os.getenv("CFDI_FIRMANTE", "kms").strip().lower(),
        cfdi_proveedor=os.getenv("CFDI_PROVEEDOR", "prodigia").strip().lower(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _build_settings()
