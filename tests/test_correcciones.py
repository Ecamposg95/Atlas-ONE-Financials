"""R2·HU-02 y R2·HU-03: corregir lo pagado con motivo y sin romper la
contabilidad, y respetar el mes cerrado también en lo que no genera póliza."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PDF2 = b"%PDF-1.4\n2 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = THIS_MONTH - timedelta(days=1)


def _setup(client):
    headers = auth_headers(register(client, initial_cash="50000"))
    categories = {c["name"]: c for c in client.get("/api/categories?kind=EXPENSE", headers=headers).json()}
    account = client.get("/api/accounts", headers=headers).json()[0]
    return headers, categories, account


def _expense(client, headers, category, account=None, when=None, status="PENDING", amount="1160"):
    body = {
        "date": (when or THIS_MONTH).isoformat(),
        "description": "Reactivos SEILAB",
        "amount": amount,
        "tax_rate": "0.16",
        "category_id": category["id"],
        "status": status,
    }
    if account:
        body["financial_account_id"] = account["id"]
    return client.post("/api/expenses", headers=headers, json=body)


def _close_last_month(client, headers):
    response = client.post(
        "/api/periods/close", headers=headers, json={"year": LAST_MONTH.year, "month": LAST_MONTH.month}
    )
    assert response.status_code == 200, response.text


def _trial(client, headers):
    rows = client.get("/api/accounting/trial-balance", headers=headers).json()["rows"]
    return {row["code"]: Decimal(str(row["balance"])) for row in rows}


# --- R2·HU-03: mes cerrado ---------------------------------------------------


def test_pending_expense_cannot_enter_a_closed_month(client):
    headers, categories, _ = _setup(client)
    pending = _expense(client, headers, categories["Renta"], when=LAST_MONTH).json()
    _close_last_month(client, headers)

    created = _expense(client, headers, categories["Renta"], when=LAST_MONTH)
    assert created.status_code == 400
    assert "está cerrado" in created.json()["detail"]

    edited = client.patch(f"/api/expenses/{pending['id']}", headers=headers, json={"notes": "otra"})
    assert edited.status_code == 400

    current = _expense(client, headers, categories["Renta"]).json()
    moved = client.patch(
        f"/api/expenses/{current['id']}", headers=headers, json={"date": LAST_MONTH.isoformat()}
    )
    assert moved.status_code == 400
    assert "está cerrado" in moved.json()["detail"]


def test_pending_income_cannot_enter_a_closed_month(client):
    headers, _, _ = _setup(client)
    _close_last_month(client, headers)
    category = client.get("/api/categories?kind=INCOME", headers=headers).json()[0]
    response = client.post(
        "/api/income",
        headers=headers,
        json={
            "date": LAST_MONTH.isoformat(),
            "description": "Estudios",
            "amount": "500",
            "category_id": category["id"],
            "status": "PENDING",
        },
    )
    assert response.status_code == 400
    assert "está cerrado" in response.json()["detail"]


# --- R2·HU-02: motivo obligatorio ----------------------------------------------


def test_cancelling_requires_a_reason(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, status="PAID").json()
    assert client.post(f"/api/expenses/{expense['id']}/cancel", headers=headers, json={}).status_code == 422
    assert (
        client.post(f"/api/expenses/{expense['id']}/cancel", headers=headers, json={"reason": " "}).status_code
        == 422
    )
    done = client.post(f"/api/expenses/{expense['id']}/cancel", headers=headers, json={"reason": "Duplicado"})
    assert done.status_code == 200


# --- R2·HU-02: corregir un gasto pagado ---------------------------------------------


def test_paid_expense_corrects_notes_with_a_reason(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, status="PAID").json()

    without = client.patch(f"/api/expenses/{expense['id']}", headers=headers, json={"notes": "Factura A-12"})
    assert without.status_code == 400
    assert "motivo" in without.json()["detail"]

    fixed = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"notes": "Factura A-12", "reference": "A-12", "reason": "Faltaba el folio"},
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["notes"] == "Factura A-12"
    event = client.get(f"/api/expenses/{expense['id']}/history", headers=headers).json()["items"][0]
    assert event["action"] == "UPDATE" and event["reason"] == "Faltaba el folio"


def test_paid_expense_keeps_money_fields_locked(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, status="PAID").json()
    for change in ({"amount": "999"}, {"date": THIS_MONTH.isoformat()}, {"description": "Otro"}):
        response = client.patch(
            f"/api/expenses/{expense['id']}", headers=headers, json={**change, "reason": "Me equivoqué"}
        )
        assert response.status_code == 400, change
        assert "cancélalo" in response.json()["detail"]


def test_category_correction_reclassifies_and_cancel_undoes_everything(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, status="PAID").json()
    before = _trial(client, headers)
    assert before["5300"] == Decimal("1000.00")

    fixed = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"category_id": categories["Inventario"]["id"], "reason": "Eran reactivos, no renta"},
    )
    assert fixed.status_code == 200, fixed.text
    after = _trial(client, headers)
    assert after.get("5300", Decimal("0")) == Decimal("0")
    assert after["5100"] == before.get("5100", Decimal("0")) + Decimal("1000.00")
    # El IVA y el dinero no se mueven.
    assert after["1190"] == before["1190"]
    assert after["1100"] == before["1100"]

    entries = client.get(
        "/api/accounting/journal-entries",
        headers=headers,
        params={"source_type": "expense", "source_id": expense["id"]},
    ).json()["items"]
    assert len(entries) == 2

    cancelled = client.post(f"/api/expenses/{expense['id']}/cancel", headers=headers, json={"reason": "Duplicado"})
    assert cancelled.status_code == 200, cancelled.text
    final = _trial(client, headers)
    assert final.get("5100", Decimal("0")) == before.get("5100", Decimal("0"))
    assert final.get("5300", Decimal("0")) == Decimal("0")


def test_paid_expense_in_a_closed_month_cannot_be_corrected(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account, when=LAST_MONTH, status="PAID").json()
    _close_last_month(client, headers)
    response = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"category_id": categories["Inventario"]["id"], "reason": "Eran reactivos"},
    )
    assert response.status_code == 400
    assert "está cerrado" in response.json()["detail"]


# --- R2·HU-02: sustituir comprobante --------------------------------------------------


def _upload(client, headers, expense_id, name, content):
    return client.post(
        f"/api/expenses/{expense_id}/attachments",
        headers=headers,
        files={"file": (name, content, "application/pdf")},
    )


def test_replace_receipt_keeps_the_trace(client):
    headers, categories, _ = _setup(client)
    expense = _expense(client, headers, categories["Renta"]).json()
    old = _upload(client, headers, expense["id"], "factura-a.pdf", PDF).json()

    replaced = client.post(
        f"/api/attachments/{old['id']}/replace",
        headers=headers,
        files={"file": ("factura-b.pdf", PDF2, "application/pdf")},
        data={"reason": "El proveedor canceló y reexpidió"},
    )
    assert replaced.status_code == 201, replaced.text
    names = [item["filename"] for item in client.get(f"/api/expenses/{expense['id']}/attachments", headers=headers).json()["items"]]
    assert names == ["factura-b.pdf"]

    event = client.get(f"/api/expenses/{expense['id']}/history", headers=headers).json()["items"][0]
    change = next(change for change in event["changes"] if change["field"] == "attachment")
    assert (change["old"], change["new"]) == ("factura-a.pdf", "factura-b.pdf")
    assert event["reason"] == "El proveedor canceló y reexpidió"


def test_replace_requires_reason_and_a_valid_file(client):
    headers, categories, _ = _setup(client)
    expense = _expense(client, headers, categories["Renta"]).json()
    old = _upload(client, headers, expense["id"], "factura-a.pdf", PDF).json()

    no_reason = client.post(
        f"/api/attachments/{old['id']}/replace",
        headers=headers,
        files={"file": ("factura-b.pdf", PDF2, "application/pdf")},
    )
    assert no_reason.status_code == 422
    bad_file = client.post(
        f"/api/attachments/{old['id']}/replace",
        headers=headers,
        files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"reason": "Otra versión"},
    )
    assert bad_file.status_code == 400
    names = [item["filename"] for item in client.get(f"/api/expenses/{expense['id']}/attachments", headers=headers).json()["items"]]
    assert names == ["factura-a.pdf"]


def test_replace_is_blocked_in_a_closed_month(client):
    headers, categories, _ = _setup(client)
    expense = _expense(client, headers, categories["Renta"], when=LAST_MONTH).json()
    old = _upload(client, headers, expense["id"], "factura-a.pdf", PDF).json()
    _close_last_month(client, headers)
    response = client.post(
        f"/api/attachments/{old['id']}/replace",
        headers=headers,
        files={"file": ("factura-b.pdf", PDF2, "application/pdf")},
        data={"reason": "Otra versión"},
    )
    assert response.status_code == 400
