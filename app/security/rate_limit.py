"""Límite de intentos por ventana deslizante, en memoria del proceso.

Protege el perímetro: autenticación por IP e invocación de agentes por llave.
Vive en memoria porque el servicio corre en una sola réplica (ADR-001); un
reinicio vacía los contadores, y eso está bien: el bloqueo de cuenta por
contraseñas fallidas sí es durable (`users.locked_until`).

Si algún día hay más de una réplica, este módulo es el único punto a cambiar
por un almacén compartido.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings
from app.security.agent import AgentContext, get_agent_context

_SWEEP_THRESHOLD = 10_000


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> int | None:
        """Registra un intento. Devuelve None si pasa, o los segundos a esperar."""
        now = time.monotonic() if now is None else now
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] + window_seconds - now))
            hits.append(now)
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(cutoff)
            return None

    def _sweep(self, cutoff: float) -> None:
        for stale in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[stale]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def is_enabled() -> bool:
    return get_settings().rate_limit_enabled


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos. Espera un momento y vuelve a intentar.",
        headers={"Retry-After": str(retry_after)},
    )


def _client_ip(request: Request) -> str:
    # uvicorn corre con --proxy-headers, así que `client.host` ya es la IP real.
    return request.client.host if request.client else "desconocida"


def limit_by_ip(scope: str, limit: int, window_seconds: int):
    """Dependencia: a lo más `limit` llamadas por IP en la ventana, por `scope`."""

    def _checker(request: Request) -> None:
        if not is_enabled():
            return
        retry_after = limiter.hit(f"{scope}:{_client_ip(request)}", limit, window_seconds)
        if retry_after is not None:
            raise _too_many(retry_after)

    return _checker


def limit_agent_key(context: AgentContext = Depends(get_agent_context)) -> None:
    """Dependencia: tope de invocaciones por llave de agente y por minuto."""
    if not is_enabled():
        return
    settings = get_settings()
    retry_after = limiter.hit(f"agent:{context.agent_key_id}", settings.agent_rate_per_minute, 60)
    if retry_after is not None:
        raise _too_many(retry_after)
