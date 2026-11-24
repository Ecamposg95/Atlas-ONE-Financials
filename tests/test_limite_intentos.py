"""Perímetro: bloqueo de cuenta por contraseñas fallidas y límite de intentos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.user import User
from app.security import rate_limit
from app.security.rate_limit import SlidingWindowLimiter
from tests.helpers import auth_headers, register

EMAIL = "dueno@example.com"
GOOD = "supersegura123"


def _login(client, password=GOOD, email=EMAIL):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture()
def limited(monkeypatch):
    """Enciende el límite por IP (apagado por defecto en pruebas) con contadores limpios."""
    rate_limit.limiter.reset()
    monkeypatch.setattr(rate_limit, "is_enabled", lambda: True)
    yield
    rate_limit.limiter.reset()


def test_cinco_fallos_bloquean_la_cuenta_aun_con_la_contrasena_correcta(client):
    register(client)
    for _ in range(5):
        assert _login(client, "incorrecta").status_code == 401

    blocked = _login(client)
    assert blocked.status_code == 429
    assert "bloqueada" in blocked.json()["detail"]
    assert int(blocked.headers["Retry-After"]) > 0


def test_el_bloqueo_vence_y_la_cuenta_vuelve_a_entrar(client, db):
    register(client)
    for _ in range(5):
        _login(client, "incorrecta")
    assert _login(client).status_code == 429

    user = db.query(User).filter(User.email == EMAIL).one()
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    assert _login(client).status_code == 200
    db.refresh(user)
    assert user.locked_until is None
    assert user.failed_login_count == 0


def test_un_login_correcto_reinicia_el_contador(client, db):
    register(client)
    for _ in range(4):
        assert _login(client, "incorrecta").status_code == 401
    assert _login(client).status_code == 200
    # Otros cuatro fallos no bloquean: el contador volvió a cero.
    for _ in range(4):
        assert _login(client, "incorrecta").status_code == 401
    assert _login(client).status_code == 200


def test_correo_desconocido_no_revela_nada_ni_bloquea(client):
    for _ in range(8):
        response = _login(client, "loquesea", email="nadie@example.com")
        assert response.status_code == 401
        assert response.json()["detail"] == "Correo o contraseña incorrectos."


def test_el_bloqueo_de_una_cuenta_no_toca_a_otra(client):
    register(client)
    register(client, email="otra@example.com", business="Otra")
    for _ in range(5):
        _login(client, "incorrecta")
    assert _login(client).status_code == 429
    assert _login(client, email="otra@example.com").status_code == 200


def test_limite_por_ip_en_login(client, limited):
    register(client)
    for _ in range(20):
        assert _login(client, "x", email="nadie@example.com").status_code == 401
    response = _login(client, "x", email="nadie@example.com")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"].startswith("Demasiados intentos")


def test_limite_por_llave_de_agente(client, limited, monkeypatch):
    from app.config import get_settings

    body = register(client)
    key = client.post(
        "/api/agent-keys", json={"name": "bot", "scopes": "READ"}, headers=auth_headers(body)
    )
    assert key.status_code == 201, key.text
    token = key.json()["token"]
    monkeypatch.setattr(
        rate_limit, "get_settings", lambda: type("S", (), {"agent_rate_per_minute": 3, "rate_limit_enabled": True})()
    )
    assert get_settings().agent_rate_per_minute == 120  # el real no cambia
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(3):
        assert client.get("/api/agent/tools", headers=headers).status_code == 200
    assert client.get("/api/agent/tools", headers=headers).status_code == 429


def test_ventana_deslizante():
    window = SlidingWindowLimiter()
    assert window.hit("k", limit=2, window_seconds=10, now=0) is None
    assert window.hit("k", limit=2, window_seconds=10, now=1) is None
    assert window.hit("k", limit=2, window_seconds=10, now=2) == 8
    assert window.hit("otra", limit=2, window_seconds=10, now=2) is None
    # Al salir el primer intento de la ventana, vuelve a pasar.
    assert window.hit("k", limit=2, window_seconds=10, now=10.5) is None
