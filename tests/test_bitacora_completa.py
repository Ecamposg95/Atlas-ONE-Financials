"""R2·REQ-03: la bitácora cubre cierres y reaperturas, contactos, comprobantes,
traspasos, permisos del equipo y reglas de autorización."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _company(client, email="dueno@lafe.mx", business="Laboratorios La Fe"):
    body = register(client, email=email, business=business, initial_cash="50000")
    return body, auth_headers(body)


def _history(client, headers, **params):
    response = client.get("/api/history", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _changes(event):
    return {change["field"]: change for change in event["changes"]}


def test_closing_and_reopening_a_month_are_logged(client):
    _, headers = _company(client)
    last = date.today().replace(day=1) - timedelta(days=1)
    closed = client.post(
        "/api/periods/close", headers=headers, json={"year": last.year, "month": last.month, "notes": "Declarado"}
    )
    assert closed.status_code == 200, closed.text
    reopened = client.post(
        "/api/periods/reopen",
        headers=headers,
        json={"year": last.year, "month": last.month, "reason": "Factura sustituida"},
    )
    assert reopened.status_code == 200, reopened.text

    events = _history(client, headers, entity_type="period")
    assert [event["action"] for event in events] == ["REOPEN", "CLOSE"]
    assert events[0]["reason"] == "Factura sustituida"
    assert events[1]["reason"] == "Declarado"
    assert events[0]["entity_label"].startswith("Mes de ")
    assert events[0]["entity_label"].endswith(str(last.year))
    assert events[0]["user_name"]


def test_contact_create_edit_and_delete_are_logged(client):
    _, headers = _company(client)
    vendor = client.post("/api/vendors", headers=headers, json={"name": "SEILAB"}).json()
    edited = client.patch(f"/api/vendors/{vendor['id']}", headers=headers, json={"tax_id": "SEI010101AAA"})
    assert edited.status_code == 200, edited.text
    # Un cambio que no cambia nada no ensucia el historial.
    client.patch(f"/api/vendors/{vendor['id']}", headers=headers, json={"tax_id": "SEI010101AAA"})
    assert client.delete(f"/api/vendors/{vendor['id']}", headers=headers).status_code == 204

    events = client.get(f"/api/vendors/{vendor['id']}/history", headers=headers).json()["items"]
    assert [event["action"] for event in events] == ["DELETE", "UPDATE", "CREATE"]
    assert all(event["entity_label"] == "SEILAB" for event in events)
    rfc = _changes(events[1])["tax_id"]
    assert rfc["label"] == "RFC" and rfc["old"] is None and rfc["new"] == "SEI010101AAA"

    customer = client.post("/api/customers", headers=headers, json={"name": "Hospital Ángeles"}).json()
    created = _history(client, headers, entity_type="customer")
    assert created[0]["entity_id"] == customer["id"] and created[0]["action"] == "CREATE"


def test_attaching_and_removing_a_receipt_shows_in_the_expense_history(client):
    _, headers = _company(client)
    category = client.get("/api/categories?kind=EXPENSE", headers=headers).json()[0]
    expense = client.post(
        "/api/expenses",
        headers=headers,
        json={"date": "2026-10-15", "description": "Papelería", "amount": "116.00", "category_id": category["id"]},
    ).json()
    uploaded = client.post(
        f"/api/expenses/{expense['id']}/attachments",
        headers=headers,
        files={"file": ("factura.pdf", PDF, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert client.delete(f"/api/attachments/{uploaded.json()['id']}", headers=headers).status_code == 204

    events = client.get(f"/api/expenses/{expense['id']}/history", headers=headers).json()["items"]
    removed, added = _changes(events[0])["attachment"], _changes(events[1])["attachment"]
    assert added["label"] == "Comprobante"
    assert (added["old"], added["new"]) == (None, "factura.pdf")
    assert (removed["old"], removed["new"]) == ("factura.pdf", None)


def test_rejected_upload_leaves_no_trace(client):
    _, headers = _company(client)
    category = client.get("/api/categories?kind=EXPENSE", headers=headers).json()[0]
    expense = client.post(
        "/api/expenses",
        headers=headers,
        json={"date": "2026-10-15", "description": "Papelería", "amount": "116.00", "category_id": category["id"]},
    ).json()
    rejected = client.post(
        f"/api/expenses/{expense['id']}/attachments",
        headers=headers,
        files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert rejected.status_code == 400
    events = client.get(f"/api/expenses/{expense['id']}/history", headers=headers).json()["items"]
    assert all("attachment" not in _changes(event) for event in events)


def test_transfer_is_logged_with_both_accounts(client):
    _, headers = _company(client)
    cash = client.get("/api/accounts", headers=headers).json()[0]
    bank = client.post(
        "/api/accounts", headers=headers, json={"name": "BBVA", "type": "BANK", "initial_balance": "0"}
    ).json()
    response = client.post(
        "/api/transactions/transfer",
        headers=headers,
        json={"from_account_id": cash["id"], "to_account_id": bank["id"], "amount": "1500", "date": "2026-10-10"},
    )
    assert response.status_code == 201, response.text

    event = _history(client, headers, entity_type="transfer")[0]
    assert event["action"] == "CREATE"
    assert event["entity_label"] == f"Traspaso de {cash['name']} a BBVA"
    fields = _changes(event)
    assert fields["from_account_id"]["new_display"] == cash["name"]
    assert fields["to_account_id"]["new_display"] == "BBVA"
    assert Decimal(fields["amount"]["new"]) == Decimal("1500")


def test_team_permissions_and_approval_rules_are_logged(client):
    _, owner = _company(client)
    invited = client.post(
        "/api/organizations/current/members",
        headers=owner,
        json={"email": "liza@lafe.mx", "name": "Liza", "role": "MEMBER", "password": "supersegura123"},
    ).json()
    client.patch(
        f"/api/organizations/current/members/{invited['id']}",
        headers=owner,
        json={"role": "ADMIN", "can_authorize": True},
    )
    assert client.delete(f"/api/organizations/current/members/{invited['id']}", headers=owner).status_code == 204

    events = _history(client, owner, entity_type="member")
    assert [event["action"] for event in events] == ["DELETE", "UPDATE", "CREATE"]
    # Sigue con nombre aunque ya salió del equipo.
    assert all(event["entity_label"] == "Liza" for event in events)
    update = _changes(events[1])
    assert (update["role"]["old"], update["role"]["new"]) == ("MEMBER", "ADMIN")
    assert update["role"]["kind"] == "role"
    assert update["can_authorize"]["new"] is True

    client.patch("/api/organizations/current/approvals", headers=owner, json={"approval_threshold": "20000"})
    rules = _history(client, owner, entity_type="organization")[0]
    assert rules["entity_label"] == "Reglas de autorización"
    threshold = _changes(rules)["approval_threshold"]
    assert threshold["old"] is None and Decimal(threshold["new"]) == Decimal("20000")


def test_history_of_another_company_stays_private(client):
    _, owner = _company(client)
    client.post("/api/vendors", headers=owner, json={"name": "SEILAB"})
    _, other = _company(client, email="ajena@example.com", business="Otra")
    assert _history(client, other, entity_type="vendor") == []
