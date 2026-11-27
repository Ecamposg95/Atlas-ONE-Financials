"""R2·REQ-04: lo que ya movió dinero no puede tener fecha futura.

Gastos pagados, ingresos cobrados, traspasos, pagos de cuentas por pagar y
cobros de cuentas por cobrar se rechazan con fecha posterior al hoy de la
empresa. Lo pendiente (gastos, ingresos, vencimientos) sí puede ir al futuro.
"""

from datetime import timedelta
from decimal import Decimal

from app.domains.dashboard.today import local_today
from app.models.organization import Organization
from tests.helpers import auth_headers, register


def _setup(client, db):
    body = register(client, initial_cash="10000")
    headers = auth_headers(body)
    account = client.get("/api/accounts", headers=headers).json()[0]
    expense_cats = client.get("/api/categories?kind=EXPENSE", headers=headers).json()
    income_cats = client.get("/api/categories?kind=INCOME", headers=headers).json()
    today = local_today(db.get(Organization, body["organization"]["id"]))
    return {
        "headers": headers,
        "account": account,
        "renta": next(c for c in expense_cats if c["name"] == "Renta"),
        "ventas": next(c for c in income_cats if c["name"] == "Ventas"),
        "today": today,
        "tomorrow": (today + timedelta(days=1)).isoformat(),
    }


def _balance(client, ctx) -> Decimal:
    return Decimal(client.get(f"/api/accounts/{ctx['account']['id']}", headers=ctx["headers"]).json()["current_balance"])


def _assert_future_rejected(response):
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail.startswith("La fecha no puede ser posterior a hoy")
    assert "ya ocurrió" in detail


def _expense(client, ctx, date, status):
    return client.post(
        "/api/expenses",
        headers=ctx["headers"],
        json={
            "date": date,
            "description": "Renta",
            "amount": "1000",
            "category_id": ctx["renta"]["id"],
            "financial_account_id": ctx["account"]["id"],
            "status": status,
        },
    )


def _income(client, ctx, date, status):
    return client.post(
        "/api/income",
        headers=ctx["headers"],
        json={
            "date": date,
            "description": "Venta",
            "amount": "1000",
            "category_id": ctx["ventas"]["id"],
            "financial_account_id": ctx["account"]["id"],
            "status": status,
        },
    )


# --- Gastos e ingresos --------------------------------------------------------


def test_paid_expense_with_future_date_is_rejected(client, db):
    ctx = _setup(client, db)
    response = _expense(client, ctx, ctx["tomorrow"], "PAID")
    _assert_future_rejected(response)
    assert "regístralo como pendiente" in response.json()["detail"]
    assert _balance(client, ctx) == Decimal("10000")


def test_paid_income_with_future_date_is_rejected(client, db):
    ctx = _setup(client, db)
    _assert_future_rejected(_income(client, ctx, ctx["tomorrow"], "PAID"))
    assert _balance(client, ctx) == Decimal("10000")


def test_paid_today_is_allowed(client, db):
    ctx = _setup(client, db)
    assert _expense(client, ctx, ctx["today"].isoformat(), "PAID").status_code == 201
    assert _income(client, ctx, ctx["today"].isoformat(), "PAID").status_code == 201


def test_pending_operations_may_be_future(client, db):
    ctx = _setup(client, db)
    expense = _expense(client, ctx, ctx["tomorrow"], "PENDING")
    income = _income(client, ctx, ctx["tomorrow"], "PENDING")
    assert expense.status_code == 201, expense.text
    assert income.status_code == 201, income.text


def test_paying_pending_expense_with_future_date_is_rejected(client, db):
    ctx = _setup(client, db)
    expense = _expense(client, ctx, ctx["today"].isoformat(), "PENDING").json()
    response = client.post(
        f"/api/expenses/{expense['id']}/pay", headers=ctx["headers"], json={"date": ctx["tomorrow"]}
    )
    _assert_future_rejected(response)
    assert client.get(f"/api/expenses/{expense['id']}", headers=ctx["headers"]).json()["status"] == "PENDING"


def test_paying_future_pending_expense_without_date_is_rejected(client, db):
    # Sin fecha de pago se usa la del gasto: si es futura, también se rechaza.
    ctx = _setup(client, db)
    expense = _expense(client, ctx, ctx["tomorrow"], "PENDING").json()
    _assert_future_rejected(client.post(f"/api/expenses/{expense['id']}/pay", headers=ctx["headers"], json={}))
    paid = client.post(
        f"/api/expenses/{expense['id']}/pay", headers=ctx["headers"], json={"date": ctx["today"].isoformat()}
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "PAID"


def test_collecting_pending_income_with_future_date_is_rejected(client, db):
    ctx = _setup(client, db)
    income = _income(client, ctx, ctx["today"].isoformat(), "PENDING").json()
    response = client.post(f"/api/income/{income['id']}/pay", headers=ctx["headers"], json={"date": ctx["tomorrow"]})
    _assert_future_rejected(response)
    assert _balance(client, ctx) == Decimal("10000")


# --- Traspasos ---------------------------------------------------------------


def test_transfer_with_future_date_is_rejected(client, db):
    ctx = _setup(client, db)
    bank = client.post(
        "/api/accounts", headers=ctx["headers"], json={"name": "BBVA", "type": "BANK", "opening_balance": "0"}
    ).json()
    payload = {"from_account_id": ctx["account"]["id"], "to_account_id": bank["id"], "amount": "500"}
    _assert_future_rejected(
        client.post("/api/transactions/transfer", headers=ctx["headers"], json={**payload, "date": ctx["tomorrow"]})
    )
    assert _balance(client, ctx) == Decimal("10000")
    ok = client.post(
        "/api/transactions/transfer", headers=ctx["headers"], json={**payload, "date": ctx["today"].isoformat()}
    )
    assert ok.status_code == 201, ok.text


# --- Cuentas por pagar y por cobrar ------------------------------------------


def test_payable_due_in_future_but_payment_cannot_be(client, db):
    ctx = _setup(client, db)
    vendor = client.post("/api/vendors", headers=ctx["headers"], json={"name": "Inmobiliaria"}).json()
    payable = client.post(
        "/api/payables",
        headers=ctx["headers"],
        json={
            "vendor_id": vendor["id"],
            "description": "Renta",
            "amount": "1000",
            "due_date": (ctx["today"] + timedelta(days=30)).isoformat(),
            "category_id": ctx["renta"]["id"],
        },
    )
    assert payable.status_code == 201, payable.text
    url = f"/api/payables/{payable.json()['id']}/pay"
    payment = {"amount": "400", "financial_account_id": ctx["account"]["id"]}
    _assert_future_rejected(client.post(url, headers=ctx["headers"], json={**payment, "date": ctx["tomorrow"]}))
    assert _balance(client, ctx) == Decimal("10000")
    # Sin fecha se toma el hoy de la empresa, que nunca es futuro.
    assert client.post(url, headers=ctx["headers"], json=payment).status_code == 200


def test_receivable_due_in_future_but_collection_cannot_be(client, db):
    ctx = _setup(client, db)
    customer = client.post("/api/customers", headers=ctx["headers"], json={"name": "Grupo Vega"}).json()
    receivable = client.post(
        "/api/receivables",
        headers=ctx["headers"],
        json={
            "customer_id": customer["id"],
            "description": "Servicio",
            "amount": "1000",
            "due_date": (ctx["today"] + timedelta(days=30)).isoformat(),
            "category_id": ctx["ventas"]["id"],
        },
    )
    assert receivable.status_code == 201, receivable.text
    url = f"/api/receivables/{receivable.json()['id']}/collect"
    collection = {"amount": "400", "financial_account_id": ctx["account"]["id"]}
    _assert_future_rejected(client.post(url, headers=ctx["headers"], json={**collection, "date": ctx["tomorrow"]}))
    assert _balance(client, ctx) == Decimal("10000")
    assert client.post(url, headers=ctx["headers"], json=collection).status_code == 200


# --- Importación --------------------------------------------------------------


def test_import_marks_future_rows_as_errors(client, db):
    ctx = _setup(client, db)
    headers = ctx["headers"]
    csv = (
        "Fecha,Concepto,Monto\n"
        f"{ctx['today'].isoformat()},Sueldo Juan,1200\n"
        f"{ctx['tomorrow']},Sueldo María,800\n"
    ).encode("utf-8")
    batch = client.post(
        "/api/imports",
        headers=headers,
        files={"file": ("gastos.csv", csv, "application/octet-stream")},
        data={"kind": "EXPENSES"},
    )
    assert batch.status_code == 201, batch.text
    mapped = client.post(
        f"/api/imports/{batch.json()['id']}/map",
        headers=headers,
        json={
            "mapping": {"fecha": "Fecha", "concepto": "Concepto", "monto": "Monto"},
            "defaults": {"category_id": ctx["renta"]["id"], "financial_account_id": ctx["account"]["id"]},
        },
    )
    assert mapped.status_code == 200, mapped.text
    rows = mapped.json()["rows"]["items"]
    assert [r["status"] for r in rows] == ["OK", "ERROR"]
    assert rows[1]["message"].startswith("Fecha futura")
