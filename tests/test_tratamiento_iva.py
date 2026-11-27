"""R2·HU-05: tratamiento de IVA explícito y retenciones por tasa."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = THIS_MONTH - timedelta(days=1)


def _setup(client):
    headers = auth_headers(register(client, initial_cash="100000"))
    expense_category = next(
        c for c in client.get("/api/categories?kind=EXPENSE", headers=headers).json() if c["name"] == "Honorarios"
    )
    income_category = client.get("/api/categories?kind=INCOME", headers=headers).json()[0]
    account = client.get("/api/accounts", headers=headers).json()[0]
    return headers, expense_category, income_category, account


def _expense(client, headers, category, account, **extra):
    body = {
        "date": THIS_MONTH.isoformat(),
        "description": "Honorarios Dr. Pérez",
        "amount": "11600",
        "category_id": category["id"],
        "financial_account_id": account["id"],
        "status": "PAID",
        **extra,
    }
    return client.post("/api/expenses", headers=headers, json=body)


def test_treatment_defaults_follow_the_rate(client):
    headers, category, _, account = _setup(client)
    taxed = _expense(client, headers, category, account, tax_rate="0.16").json()
    untaxed = _expense(client, headers, category, account, tax_rate="0").json()
    assert taxed["tax_treatment"] == "TAXED"
    # Nadie decidió que es exento: queda pendiente de clasificar.
    assert untaxed["tax_treatment"] == "UNCLASSIFIED"


def test_treatment_must_match_the_rate(client):
    headers, category, _, account = _setup(client)
    exempt_with_vat = _expense(client, headers, category, account, tax_rate="0.16", tax_treatment="EXEMPT")
    assert exempt_with_vat.status_code == 400
    taxed_without_vat = _expense(client, headers, category, account, tax_rate="0", tax_treatment="TAXED")
    assert taxed_without_vat.status_code == 400
    exempt = _expense(client, headers, category, account, tax_rate="0", tax_treatment="EXEMPT")
    assert exempt.status_code == 201 and exempt.json()["tax_treatment"] == "EXEMPT"
    bogus = _expense(client, headers, category, account, tax_rate="0", tax_treatment="CASI_EXENTO")
    assert bogus.status_code == 422


def test_paid_expense_can_be_classified_without_reversal(client):
    headers, category, _, account = _setup(client)
    expense = _expense(client, headers, category, account, tax_rate="0").json()
    trial_before = client.get("/api/accounting/trial-balance", headers=headers).json()

    no_reason = client.patch(f"/api/expenses/{expense['id']}", headers=headers, json={"tax_treatment": "EXEMPT"})
    assert no_reason.status_code == 400
    fixed = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"tax_treatment": "EXEMPT", "reason": "Servicio médico exento, confirmado por contabilidad"},
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["tax_treatment"] == "EXEMPT"
    # Clasificar no mueve el libro.
    assert client.get("/api/accounting/trial-balance", headers=headers).json() == trial_before

    to_taxed = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"tax_treatment": "TAXED", "reason": "Sí llevaba IVA"},
    )
    assert to_taxed.status_code == 400

    event = client.get(f"/api/expenses/{expense['id']}/history", headers=headers).json()["items"][0]
    change = next(c for c in event["changes"] if c["field"] == "tax_treatment")
    assert (change["old"], change["new"], change["kind"]) == ("UNCLASSIFIED", "EXEMPT", "treatment")


def test_retention_by_rate_is_computed_on_the_base(client):
    headers, category, _, account = _setup(client)
    expense = _expense(
        client,
        headers,
        category,
        account,
        tax_rate="0.16",
        retention_isr_rate="0.10",
        retention_iva_rate="0.106667",
    ).json()
    # Base 10,000: ISR 10 % = 1,000; IVA 2/3 de 16 % = 1,066.67.
    assert Decimal(expense["retention_isr"]) == Decimal("1000.00")
    assert Decimal(expense["retention_iva"]) == Decimal("1066.67")
    assert Decimal(expense["retention_isr_rate"]) == Decimal("0.10")

    mismatch = _expense(
        client, headers, category, account, tax_rate="0.16", retention_isr_rate="0.10", retention_isr="500"
    )
    assert mismatch.status_code == 400
    assert "no coincide" in mismatch.json()["detail"]


def test_pending_retention_is_recomputed_when_the_amount_changes(client):
    headers, category, _, account = _setup(client)
    expense = _expense(
        client, headers, category, account, tax_rate="0.16", retention_isr_rate="0.10", status="PENDING"
    ).json()
    updated = client.patch(f"/api/expenses/{expense['id']}", headers=headers, json={"amount": "23200"})
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["retention_isr"]) == Decimal("2000.00")


def test_income_and_debts_carry_the_treatment(client):
    headers, expense_category, income_category, account = _setup(client)
    income = client.post(
        "/api/income",
        headers=headers,
        json={
            "date": THIS_MONTH.isoformat(),
            "description": "Estudios de laboratorio",
            "amount": "800",
            "tax_rate": "0",
            "tax_treatment": "EXEMPT",
            "category_id": income_category["id"],
            "status": "PENDING",
        },
    )
    assert income.status_code == 201, income.text
    assert income.json()["tax_treatment"] == "EXEMPT"

    vendor = client.post("/api/vendors", headers=headers, json={"name": "SEILAB"}).json()
    payable = client.post(
        "/api/payables",
        headers=headers,
        json={
            "vendor_id": vendor["id"],
            "description": "Estudios de referencia",
            "amount": "3000",
            "tax_rate": "0",
            "tax_treatment": "NOT_OBJECT",
            "due_date": THIS_MONTH.isoformat(),
            "category_id": expense_category["id"],
        },
    )
    assert payable.status_code == 201, payable.text
    assert payable.json()["tax_treatment"] == "NOT_OBJECT"


def test_vat_report_breaks_down_by_treatment_and_shows_retentions(client):
    headers, category, income_category, account = _setup(client)
    _expense(client, headers, category, account, tax_rate="0.16", retention_isr_rate="0.10", retention_iva_rate="0.106667")
    _expense(client, headers, category, account, tax_rate="0", amount="500")
    _expense(client, headers, category, account, tax_rate="0", amount="700", tax_treatment="EXEMPT")

    end = (THIS_MONTH + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    report = client.get(
        "/api/reports/iva", headers=headers, params={"start": THIS_MONTH.isoformat(), "end": end.isoformat()}
    ).json()
    rows = {row["treatment"]: row for row in report["by_treatment"]["expenses"]}
    assert Decimal(str(rows["TAXED"]["base"])) == Decimal("10000.00")
    assert Decimal(str(rows["TAXED"]["tax"])) == Decimal("1600.00")
    assert Decimal(str(rows["EXEMPT"]["base"])) == Decimal("700.00")
    assert rows["UNCLASSIFIED"]["operations"] == 1
    assert report["unclassified_count"] == 1
    assert Decimal(str(report["isr_withheld"])) == Decimal("1000.00")
    assert Decimal(str(report["vat_withheld"])) == Decimal("1066.67")


def test_classifying_income_respects_the_closed_month(client):
    headers, _, income_category, account = _setup(client)
    income = client.post(
        "/api/income",
        headers=headers,
        json={
            "date": LAST_MONTH.isoformat(),
            "description": "Estudios",
            "amount": "800",
            "tax_rate": "0",
            "category_id": income_category["id"],
            "financial_account_id": account["id"],
            "status": "PAID",
        },
    ).json()
    assert client.patch(
        f"/api/income/{income['id']}", headers=headers, json={"tax_treatment": "EXEMPT"}
    ).status_code == 200
    client.post("/api/periods/close", headers=headers, json={"year": LAST_MONTH.year, "month": LAST_MONTH.month})
    closed = client.patch(f"/api/income/{income['id']}", headers=headers, json={"tax_treatment": "NOT_OBJECT"})
    assert closed.status_code == 400


def test_list_filters_by_treatment(client):
    headers, category, _, account = _setup(client)
    _expense(client, headers, category, account, tax_rate="0.16")
    pending = _expense(client, headers, category, account, tax_rate="0").json()
    _expense(client, headers, category, account, tax_rate="0", tax_treatment="EXEMPT")
    items = client.get("/api/expenses", headers=headers, params={"tax_treatment": "UNCLASSIFIED"}).json()["items"]
    assert [item["id"] for item in items] == [pending["id"]]
    assert client.get("/api/expenses", headers=headers, params={"tax_treatment": "OTRO"}).status_code == 422
