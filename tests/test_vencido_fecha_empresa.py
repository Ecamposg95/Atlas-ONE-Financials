"""R2·HU-09.b: «vencido» se mide con la fecha de la empresa, no la del servidor.

El reloj queda congelado el 2026-11-28 03:00 UTC: en el servidor (UTC) ya es
día 28, pero en Ciudad de México siguen siendo las 21:00 del 27. Lo que vence
el 27 todavía no está vencido; lo del 26 sí.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core import company_date
from app.models.organization import Organization
from tests.helpers import auth_headers, register

FROZEN_UTC = datetime(2026, 11, 28, 3, 0, tzinfo=timezone.utc)
TODAY_MX = "2026-11-27"
YESTERDAY_MX = "2026-11-26"


@pytest.fixture(autouse=True)
def _reloj_congelado(monkeypatch):
    monkeypatch.setattr(company_date, "_utcnow", lambda: FROZEN_UTC)


def _empresa(client, email="vence@example.com"):
    body = register(client, email=email, initial_cash="10000")
    return body["organization"]["id"], auth_headers(body)


def _category(client, headers, kind, name):
    return next(c for c in client.get(f"/api/categories?kind={kind}", headers=headers).json() if c["name"] == name)


def _receivable(client, headers, due, amount):
    customer = client.post("/api/customers", headers=headers, json={"name": f"Cliente {due}"}).json()
    response = client.post(
        "/api/receivables",
        headers=headers,
        json={
            "customer_id": customer["id"],
            "description": "Factura a crédito",
            "amount": amount,
            "date": "2026-11-01",
            "due_date": due,
            "category_id": _category(client, headers, "INCOME", "Ventas")["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _payable(client, headers, due, amount):
    vendor = client.post("/api/vendors", headers=headers, json={"name": f"Proveedor {due}"}).json()
    response = client.post(
        "/api/payables",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "description": "Reactivos",
            "amount": amount,
            "date": "2026-11-01",
            "due_date": due,
            "category_id": _category(client, headers, "EXPENSE", "Renta")["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_cxc_que_vence_hoy_en_mexico_no_esta_vencida(client):
    _org, headers = _empresa(client)
    hoy = _receivable(client, headers, TODAY_MX, "700")
    ayer = _receivable(client, headers, YESTERDAY_MX, "300")

    assert hoy["is_overdue"] is False
    assert hoy["display_status"] == "OPEN"
    assert ayer["is_overdue"] is True

    detalle = client.get(f"/api/receivables/{hoy['id']}", headers=headers).json()
    assert detalle["is_overdue"] is False

    page = client.get("/api/receivables", headers=headers).json()
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[hoy["id"]]["display_status"] == "OPEN"
    assert by_id[ayer["id"]]["display_status"] == "OVERDUE"
    assert Decimal(str(page["total_overdue"])) == Decimal("300")

    vencidas = client.get("/api/receivables?status=OVERDUE", headers=headers).json()
    assert [item["id"] for item in vencidas["items"]] == [ayer["id"]]

    summary = client.get("/api/dashboard/summary", headers=headers).json()
    assert Decimal(str(summary["overdue_receivables"])) == Decimal("300")


def test_cxp_que_vence_hoy_en_mexico_no_esta_vencida(client):
    _org, headers = _empresa(client)
    hoy = _payable(client, headers, TODAY_MX, "500")
    ayer = _payable(client, headers, YESTERDAY_MX, "200")

    assert hoy["is_overdue"] is False
    assert ayer["is_overdue"] is True

    page = client.get("/api/payables", headers=headers).json()
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[hoy["id"]]["display_status"] == "OPEN"
    assert Decimal(str(page["total_overdue"])) == Decimal("200")

    vencidas = client.get("/api/payables?status=OVERDUE", headers=headers).json()
    assert [item["id"] for item in vencidas["items"]] == [ayer["id"]]

    cartera = client.get("/api/portfolio", headers=headers).json()
    fila = cartera[0] if isinstance(cartera, list) else cartera["items"][0]
    assert Decimal(str(fila["payable_overdue"])) == Decimal("200")


def test_la_zona_es_la_de_cada_empresa(client, db):
    """Una empresa en Tokio ya vive el 28: lo del 27 sí le está vencido."""
    org_id, headers = _empresa(client, email="tokio@example.com")
    db.get(Organization, org_id).timezone = "Asia/Tokyo"
    db.flush()

    hoy_mx = _payable(client, headers, TODAY_MX, "500")
    assert hoy_mx["is_overdue"] is True
    page = client.get("/api/payables?status=OVERDUE", headers=headers).json()
    assert page["total"] == 1
    assert Decimal(str(page["total_overdue"])) == Decimal("500")


def test_sin_peticion_cae_a_la_fecha_de_mexico():
    assert company_date.company_today().isoformat() == TODAY_MX
