"""R2·HU-04: corregir varios gastos a la vez, con vista previa y resultado por gasto."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = THIS_MONTH - timedelta(days=1)


def _setup(client):
    headers = auth_headers(register(client, initial_cash="50000"))
    categories = {c["name"]: c for c in client.get("/api/categories?kind=EXPENSE", headers=headers).json()}
    account = client.get("/api/accounts", headers=headers).json()[0]
    return headers, categories, account


def _expense(client, headers, category, account, when=THIS_MONTH, status="PAID", amount="500", tax_rate="0"):
    response = client.post(
        "/api/expenses",
        headers=headers,
        json={
            "date": when.isoformat(),
            "description": "Estudios de referencia",
            "amount": amount,
            "tax_rate": tax_rate,
            "category_id": category["id"],
            "financial_account_id": account["id"],
            "status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bulk(client, headers, ids, changes, dry_run, reason="Clasificación de contabilidad"):
    return client.post(
        "/api/expenses/bulk-update",
        headers=headers,
        json={"ids": ids, "changes": changes, "reason": reason, "dry_run": dry_run},
    )


def _trial(client, headers):
    rows = client.get("/api/accounting/trial-balance", headers=headers).json()["rows"]
    return {row["code"]: Decimal(str(row["balance"])) for row in rows}


def test_preview_changes_nothing_and_apply_matches_it(client):
    headers, categories, account = _setup(client)
    ids = [_expense(client, headers, categories["Renta"], account)["id"] for _ in range(3)]
    trial = _trial(client, headers)
    changes = {"category_id": categories["Inventario"]["id"], "tax_treatment": "EXEMPT"}

    preview = _bulk(client, headers, ids, changes, dry_run=True)
    assert preview.status_code == 200, preview.text
    assert (preview.json()["updated"], preview.json()["rejected"]) == (3, 0)
    assert _trial(client, headers) == trial
    assert all(
        client.get(f"/api/expenses/{expense_id}", headers=headers).json()["tax_treatment"] == "UNCLASSIFIED"
        for expense_id in ids
    )
    assert client.get(f"/api/expenses/{ids[0]}/history", headers=headers).json()["total"] == 1

    applied = _bulk(client, headers, ids, changes, dry_run=False).json()
    assert applied["updated"] == 3
    after = _trial(client, headers)
    assert after["5100"] == trial.get("5100", Decimal("0")) + Decimal("1500.00")
    assert after.get("5300", Decimal("0")) == trial["5300"] - Decimal("1500.00")
    expense = client.get(f"/api/expenses/{ids[0]}", headers=headers).json()
    assert (expense["category_id"], expense["tax_treatment"]) == (categories["Inventario"]["id"], "EXEMPT")
    event = client.get(f"/api/expenses/{ids[0]}/history", headers=headers).json()["items"][0]
    assert event["reason"] == "Clasificación de contabilidad"


def test_each_expense_is_judged_on_its_own(client):
    headers, categories, account = _setup(client)
    closed = _expense(client, headers, categories["Renta"], account, when=LAST_MONTH)
    client.post("/api/periods/close", headers=headers, json={"year": LAST_MONTH.year, "month": LAST_MONTH.month})
    taxed = _expense(client, headers, categories["Renta"], account, tax_rate="0.16")
    cancelled = _expense(client, headers, categories["Renta"], account)
    client.post(f"/api/expenses/{cancelled['id']}/cancel", headers=headers, json={"reason": "Duplicado"})
    ok = _expense(client, headers, categories["Renta"], account)
    already = _expense(client, headers, categories["Renta"], account)
    client.patch(
        f"/api/expenses/{already['id']}", headers=headers, json={"tax_treatment": "EXEMPT", "reason": "Ya revisado"}
    )

    ids = [closed["id"], taxed["id"], cancelled["id"], ok["id"], already["id"], "no-existe"]
    result = _bulk(client, headers, ids, {"tax_treatment": "EXEMPT"}, dry_run=False).json()
    outcome = {item["id"]: item for item in result["items"]}
    assert outcome[ok["id"]]["outcome"] == "updated"
    assert outcome[already["id"]]["outcome"] == "unchanged"
    assert outcome[closed["id"]]["outcome"] == "rejected"
    assert "está cerrado" in outcome[closed["id"]]["detail"]
    assert outcome[taxed["id"]]["outcome"] == "rejected"
    assert "gravada" in outcome[taxed["id"]]["detail"] or "IVA" in outcome[taxed["id"]]["detail"]
    assert outcome["no-existe"]["detail"] == "El gasto no existe."
    assert (result["updated"], result["unchanged"], result["rejected"]) == (1, 1, 4)
    # El cancelado sólo admite proyecto: tratamiento rechazado.
    assert outcome[cancelled["id"]]["outcome"] == "rejected"


def test_bulk_refuses_money_fields_and_other_companies(client):
    headers, categories, account = _setup(client)
    expense = _expense(client, headers, categories["Renta"], account)
    money = _bulk(client, headers, [expense["id"]], {"amount": "1"}, dry_run=True)
    assert money.status_code == 422
    no_reason = _bulk(client, headers, [expense["id"]], {"tax_treatment": "EXEMPT"}, dry_run=True, reason="")
    assert no_reason.status_code == 422

    other = auth_headers(register(client, email="ajena@example.com", business="Otra"))
    foreign = _bulk(client, other, [expense["id"]], {"tax_treatment": "EXEMPT"}, dry_run=False).json()
    assert foreign["rejected"] == 1
    assert client.get(f"/api/expenses/{expense['id']}", headers=headers).json()["tax_treatment"] == "UNCLASSIFIED"


def test_viewer_cannot_bulk_update(client):
    body = register(client, initial_cash="1000")
    owner = auth_headers(body)
    client.post(
        "/api/organizations/current/members",
        headers=owner,
        json={"email": "consulta@lafe.mx", "name": "Consulta", "role": "VIEWER", "password": "supersegura123"},
    )
    viewer = auth_headers(client.post("/api/auth/login", json={"email": "consulta@lafe.mx", "password": "supersegura123"}).json())
    response = _bulk(client, viewer, ["x"], {"tax_treatment": "EXEMPT"}, dry_run=True)
    assert response.status_code == 403
