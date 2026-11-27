"""R2·HU-20 y R2·HU-21: totales de lo filtrado y búsqueda general."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

TODAY = date.today()


def _setup(client, email="dueno@lafe.mx", business="Laboratorios La Fe"):
    headers = auth_headers(register(client, email=email, business=business, initial_cash="50000"))
    categories = {c["name"]: c for c in client.get("/api/categories?kind=EXPENSE", headers=headers).json()}
    account = client.get("/api/accounts", headers=headers).json()[0]
    return headers, categories, account


def _expense(client, headers, category, account, amount, description="Reactivos", status="PAID"):
    response = client.post(
        "/api/expenses",
        headers=headers,
        json={
            "date": TODAY.isoformat(),
            "description": description,
            "amount": amount,
            "category_id": category["id"],
            "financial_account_id": account["id"],
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_filtered_total_leaves_out_cancelled(client):
    headers, categories, account = _setup(client)
    _expense(client, headers, categories["Renta"], account, "100")
    _expense(client, headers, categories["Renta"], account, "200")
    gone = _expense(client, headers, categories["Renta"], account, "1000")
    client.post(f"/api/expenses/{gone['id']}/cancel", headers=headers, json={"reason": "Duplicado"})

    page = client.get("/api/expenses", headers=headers, params={"limit": 1}).json()
    assert Decimal(str(page["total_amount"])) == Decimal("300.00")
    assert page["sum_excludes_cancelled"] is True
    cancelled = client.get("/api/expenses", headers=headers, params={"status": "CANCELLED"}).json()
    assert Decimal(str(cancelled["total_amount"])) == Decimal("1000.00")


def test_payables_totals_cover_the_whole_filter(client):
    headers, categories, account = _setup(client)
    vendor = client.post("/api/vendors", headers=headers, json={"name": "SEILAB"}).json()

    def payable(amount, due):
        return client.post(
            "/api/payables",
            headers=headers,
            json={
                "vendor_id": vendor["id"],
                "description": "Estudios",
                "amount": amount,
                "due_date": due.isoformat(),
                "category_id": categories["Renta"]["id"],
            },
        ).json()

    late = payable("1000", TODAY - timedelta(days=5))
    payable("500", TODAY + timedelta(days=10))
    client.post(f"/api/payables/{late['id']}/pay", headers=headers, json={"amount": "400", "financial_account_id": account["id"]})

    page = client.get("/api/payables", headers=headers, params={"limit": 1}).json()
    assert Decimal(str(page["total_amount"])) == Decimal("1500.00")
    assert Decimal(str(page["total_balance"])) == Decimal("1100.00")
    assert Decimal(str(page["total_overdue"])) == Decimal("600.00")


def test_global_search_finds_operations_contacts_and_amounts(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, "1160", description="Reactivos SEILAB 1876")
    vendor = client.post("/api/vendors", headers=headers, json={"name": "SEILAB", "tax_id": "SEI010101AAA"}).json()

    found = client.get("/api/search", headers=headers, params={"q": "seilab"}).json()["items"]
    kinds = {(item["kind"], item["id"]) for item in found}
    assert ("expense", expense["id"]) in kinds
    assert ("vendor", vendor["id"]) in kinds
    hit = next(item for item in found if item["id"] == expense["id"])
    assert hit["to"] == f"/gastos?open={expense['id']}"

    by_amount = client.get("/api/search", headers=headers, params={"q": "$1,160"}).json()["items"]
    assert any(item["id"] == expense["id"] for item in by_amount)
    by_rfc = client.get("/api/search", headers=headers, params={"q": "SEI0101"}).json()["items"]
    assert [item["kind"] for item in by_rfc] == ["vendor"]

    assert client.get("/api/search", headers=headers, params={"q": "x"}).status_code == 422


def test_global_search_stays_inside_the_company(client):
    headers, categories, account = _setup(client)
    _expense(client, headers, categories["Renta"], account, "500", description="Reactivos SEILAB")
    other, _, _ = _setup(client, email="ajena@example.com", business="Otra")
    assert client.get("/api/search", headers=other, params={"q": "seilab"}).json()["items"] == []
