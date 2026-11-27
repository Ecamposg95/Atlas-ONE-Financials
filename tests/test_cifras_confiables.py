"""Cifras confiables: la apertura en la fecha de corte y el resumen con la base del estado de resultados."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

TODAY = date.today()
CUTOFF = TODAY.replace(day=1) - timedelta(days=1)  # último día del mes pasado: nunca hoy


def _company(client, email="cifras@example.com", cutoff=CUTOFF):
    headers = auth_headers(register(client, email=email, business="La Fe"))
    if cutoff is not None:
        response = client.patch("/api/opening", headers=headers, json={"opening_date": cutoff.isoformat()})
        assert response.status_code == 200, response.text
    return headers


def _create_account(client, headers, opening="25000", name="Santander PyME"):
    return client.post("/api/accounts", headers=headers, json={"name": name, "type": "BANK", "opening_balance": opening})


def _account_entries(client, headers, account_id):
    response = client.get("/api/accounting/journal-entries?source_type=financial_account&limit=200", headers=headers)
    assert response.status_code == 200, response.text
    return [entry for entry in response.json()["items"] if entry["source_id"] == account_id]


# --- R2·HU-12.a: saldo inicial fechado en el corte ---


def test_initial_balance_is_posted_at_the_cutoff_date(client):
    headers = _company(client)
    response = _create_account(client, headers)
    assert response.status_code == 201, response.text
    account = response.json()

    [entry] = _account_entries(client, headers, account["id"])
    assert entry["date"] == CUTOFF.isoformat()
    debit = sum(Decimal(str(line["debit"])) for line in entry["lines"])
    credit = sum(Decimal(str(line["credit"])) for line in entry["lines"])
    assert debit == credit == Decimal("25000.00")


def test_without_a_cutoff_the_initial_balance_stays_at_today(client):
    headers = _company(client, cutoff=None)
    account = _create_account(client, headers).json()
    [entry] = _account_entries(client, headers, account["id"])
    assert entry["date"] == TODAY.isoformat()


def test_a_closed_cutoff_month_rejects_an_initial_balance_like_the_adjustment(client):
    headers = _company(client)
    closed = client.post("/api/periods/close", headers=headers, json={"year": CUTOFF.year, "month": CUTOFF.month})
    assert closed.status_code == 200, closed.text

    response = _create_account(client, headers)
    assert response.status_code == 400
    assert "fecha de corte" in response.json()["detail"]
    # Sin saldo inicial no hay póliza: el alta procede.
    assert _create_account(client, headers, opening="0", name="Banorte").status_code == 201


# --- R2·HU-10.b: desglose por categoría sin IVA ---


def test_dashboard_category_breakdown_matches_the_income_statement(client):
    headers = _company(client, cutoff=None)
    account = client.get("/api/accounts", headers=headers).json()[0]
    renta = next(c for c in client.get("/api/categories?kind=EXPENSE", headers=headers).json() if c["name"] == "Renta")
    created = client.post(
        "/api/expenses",
        headers=headers,
        json={
            "date": TODAY.isoformat(),
            "description": "Renta del local",
            "amount": "11600",
            "tax_rate": "0.16",
            "category_id": renta["id"],
            "financial_account_id": account["id"],
            "status": "PAID",
        },
    )
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["subtotal"]) == Decimal("10000.00")

    summary = client.get("/api/dashboard/summary", headers=headers).json()
    by_category = {row["category"]: Decimal(str(row["amount"])) for row in summary["expense_categories"]}
    assert by_category["Renta"] == Decimal("10000.00")

    flow = client.get("/api/dashboard/cash-flow", headers=headers).json()
    top = {row["category"]: Decimal(str(row["amount"])) for row in flow["points"][-1]["top_expense_categories"]}
    assert top["Renta"] == Decimal("10000.00")

    series = client.get("/api/reports/category-series", headers=headers).json()
    assert Decimal(str(series["points"][-1]["Renta"])) == by_category["Renta"]

    month_start = TODAY.replace(day=1).isoformat()
    pnl = client.get(f"/api/reports/profit-loss?start={month_start}&end={TODAY.isoformat()}", headers=headers).json()
    assert Decimal(str(pnl["total_expenses"])) == sum(by_category.values())
