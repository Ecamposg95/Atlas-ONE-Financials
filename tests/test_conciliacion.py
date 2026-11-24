"""Conciliación bancaria: el estado de cuenta se liga con movimientos que ya
existen. Conciliar no mueve saldos ni escribe pólizas; las diferencias quedan
a la vista y un estado cerrado conserva sus cifras."""

from datetime import date, timedelta
from decimal import Decimal

from tests.helpers import auth_headers, register
from tests.test_transito import _account, _balances

DAY = date(2026, 10, 15)


def _setup(client, email="dueno@example.com"):
    headers = auth_headers(register(client, email=email, initial_cash="0"))
    banco = client.post(
        "/api/accounts", headers=headers, json={"name": "BBVA", "type": "BANK", "opening_balance": "10000"}
    ).json()
    cats = {c["kind"] + ":" + c["name"]: c for c in client.get("/api/categories", headers=headers).json()}
    return headers, banco, cats


def _income(client, headers, banco, cats, amount, when=DAY, reference=None):
    payload = {
        "date": when.isoformat(),
        "description": "Venta por transferencia",
        "amount": amount,
        "category_id": cats["INCOME:Ventas"]["id"],
        "financial_account_id": banco["id"],
        "status": "PAID",
    }
    if reference:
        payload["reference"] = reference
    response = client.post("/api/income", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _expense(client, headers, banco, cats, amount, when=DAY):
    response = client.post(
        "/api/expenses",
        headers=headers,
        json={
            "date": when.isoformat(),
            "description": "Renta",
            "amount": amount,
            "category_id": cats["EXPENSE:Otros"]["id"],
            "financial_account_id": banco["id"],
            "status": "PAID",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _csv(rows, header="Fecha,Concepto,Referencia,Cargo,Abono"):
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def _upload(client, headers, banco, content, name="octubre.csv", **form):
    return client.post(
        "/api/bank-statements",
        headers=headers,
        files={"file": (name, content, "text/csv")},
        data={"financial_account_id": banco["id"], **form},
    )


def _line(detail, description):
    return next(line for line in detail["lines"] if line["description"] == description)


def test_vista_previa_detecta_columnas_y_no_guarda(client):
    headers, banco, _cats = _setup(client)
    content = _csv(["15/10/2026,Depósito,ABC1,,1500.00", "16/10/2026,Renta,,800.00,", "Saldo final,,,,"])
    response = client.post(
        "/api/bank-statements/preview", headers=headers, files={"file": ("octubre.csv", content, "text/csv")}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping"] == {
        "date": "Fecha",
        "description": "Concepto",
        "reference": "Referencia",
        "deposit": "Abono",
        "withdrawal": "Cargo",
    }
    assert body["total_rows"] == 2
    assert body["skipped_count"] == 1
    assert Decimal(body["deposits"]) == Decimal("1500.00")
    assert Decimal(body["withdrawals"]) == Decimal("800.00")
    assert client.get("/api/bank-statements", headers=headers).json()["total"] == 0


def test_sugiere_confirma_y_no_mueve_saldos(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "1500")
    _expense(client, headers, banco, cats, "800")
    saldo_antes = _account(client, headers, banco["id"])["current_balance"]
    balanza_antes = _balances(client, headers)

    response = _upload(
        client, headers, banco, _csv(["16/10/2026,Depósito,,,1500.00", "16/10/2026,Renta local,,800.00,"])
    )
    assert response.status_code == 201, response.text
    detail = response.json()
    assert detail["summary"]["pending_count"] == 2
    deposito = _line(detail, "Depósito")
    assert deposito["suggestions"][0]["kind"] == "EXACT"
    transaction_id = deposito["suggestions"][0]["transactions"][0]["id"]

    detail = client.post(
        f"/api/bank-statements/{detail['statement']['id']}/lines/{deposito['id']}/match",
        headers=headers,
        json={"transaction_ids": [transaction_id]},
    ).json()
    deposito = _line(detail, "Depósito")
    assert deposito["status"] == "MATCHED"
    assert Decimal(deposito["difference"]) == 0
    assert detail["summary"]["pending_count"] == 1

    assert _account(client, headers, banco["id"])["current_balance"] == saldo_antes
    assert _balances(client, headers) == balanza_antes


def test_un_deposito_liquida_varias_ventas_y_la_diferencia_queda_visible(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "400")
    _income(client, headers, banco, cats, "600")
    detail = _upload(client, headers, banco, _csv(["15/10/2026,Depósito agrupado,,,1000.00"])).json()
    line = detail["lines"][0]
    assert line["suggestions"][0]["kind"] == "GROUP"
    ids = [t["id"] for t in line["suggestions"][0]["transactions"]]
    assert len(ids) == 2
    statement_id = detail["statement"]["id"]

    # Ligar sólo una venta deja una diferencia de 600 a la vista.
    detail = client.post(
        f"/api/bank-statements/{statement_id}/lines/{line['id']}/match",
        headers=headers,
        json={"transaction_ids": ids[:1]},
    ).json()
    assert detail["summary"]["differences_count"] == 1
    assert {a["kind"] for a in detail["summary"]["alerts"]} >= {"DIFFERENCE", "BOOK_UNMATCHED"}

    detail = client.post(f"/api/bank-statements/{statement_id}/lines/{line['id']}/reset", headers=headers).json()
    assert detail["lines"][0]["status"] == "PENDING"
    detail = client.post(
        f"/api/bank-statements/{statement_id}/lines/{line['id']}/match",
        headers=headers,
        json={"transaction_ids": ids},
    ).json()
    assert Decimal(detail["lines"][0]["difference"]) == 0
    assert detail["summary"]["alerts"] == []


def test_un_movimiento_no_se_concilia_dos_veces(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "500")
    detail = _upload(
        client, headers, banco, _csv(["15/10/2026,Depósito uno,,,500.00", "15/10/2026,Depósito dos,,,500.00"])
    ).json()
    statement_id = detail["statement"]["id"]
    uno, dos = _line(detail, "Depósito uno"), _line(detail, "Depósito dos")
    transaction_id = uno["suggestions"][0]["transactions"][0]["id"]
    url = f"/api/bank-statements/{statement_id}/lines"
    assert client.post(f"{url}/{uno['id']}/match", headers=headers, json={"transaction_ids": [transaction_id]}).status_code == 200
    again = client.post(f"{url}/{dos['id']}/match", headers=headers, json={"transaction_ids": [transaction_id]})
    assert again.status_code == 409
    assert "ya está conciliado" in again.json()["detail"]


def test_conciliar_automatico_solo_toma_lo_que_no_es_ambiguo(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "1500")
    _income(client, headers, banco, cats, "250")
    _income(client, headers, banco, cats, "250")
    detail = _upload(
        client, headers, banco, _csv(["15/10/2026,Único,,,1500.00", "15/10/2026,Ambiguo,,,250.00"])
    ).json()
    result = client.post(f"/api/bank-statements/{detail['statement']['id']}/auto-match", headers=headers).json()
    assert result["confirmed"] == 1
    assert _line(result["detail"], "Único")["status"] == "MATCHED"
    assert _line(result["detail"], "Ambiguo")["status"] == "PENDING"


def test_cierre_exige_resolver_todo_y_guarda_la_fotografia(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "1500")
    _expense(client, headers, banco, cats, "300")  # cheque que el banco aún no cobra
    detail = _upload(
        client, headers, banco, _csv(["15/10/2026,Depósito,,,1500.00", "15/10/2026,Comisión,,50.00,"])
    ).json()
    statement_id = detail["statement"]["id"]
    url = f"/api/bank-statements/{statement_id}"
    client.post(f"{url}/auto-match", headers=headers)

    pendiente = client.post(f"{url}/close", headers=headers, json={"closing_balance": "11450"})
    assert pendiente.status_code == 400
    assert "pendientes" in pendiente.json()["detail"]

    comision = _line(client.get(url, headers=headers).json(), "Comisión")
    sin_nota = client.post(f"{url}/lines/{comision['id']}/ignore", headers=headers, json={"note": "  "})
    assert sin_nota.status_code == 400
    client.post(f"{url}/lines/{comision['id']}/ignore", headers=headers, json={"note": "Comisión por registrar"})

    cerrado = client.post(f"{url}/close", headers=headers, json={"closing_balance": "11450"})
    assert cerrado.status_code == 200, cerrado.text
    summary = cerrado.json()["summary"]
    # Libros: 10000 + 1500 − 300 = 11200. Banco: 11200 + 300 (cheque en tránsito) − 50 (comisión) = 11450.
    assert Decimal(summary["book_balance"]) == Decimal("11200.00")
    assert Decimal(summary["in_transit_out"]) == Decimal("300.00")
    assert Decimal(summary["ignored_total"]) == Decimal("-50.00")
    assert Decimal(summary["unexplained"]) == 0

    # Un movimiento posterior con fecha del periodo no cambia la conciliación cerrada.
    _income(client, headers, banco, cats, "999")
    despues = client.get(url, headers=headers).json()
    assert despues["statement"]["status"] == "CLOSED"
    assert Decimal(despues["summary"]["book_balance"]) == Decimal("11200.00")
    assert Decimal(despues["summary"]["unexplained"]) == 0

    cambio = client.post(f"{url}/lines/{comision['id']}/reset", headers=headers)
    assert cambio.status_code == 409


def test_mismo_archivo_no_entra_dos_veces_y_cancelar_lo_libera(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "500")
    content = _csv(["15/10/2026,Depósito,,,500.00"])
    first = _upload(client, headers, banco, content)
    assert first.status_code == 201
    assert _upload(client, headers, banco, content).status_code == 409

    statement_id = first.json()["statement"]["id"]
    client.post(f"/api/bank-statements/{statement_id}/auto-match", headers=headers)
    assert client.post(f"/api/bank-statements/{statement_id}/cancel", headers=headers).status_code == 200
    again = _upload(client, headers, banco, content)
    assert again.status_code == 201
    # El movimiento quedó libre: vuelve a proponerse.
    assert again.json()["lines"][0]["suggestions"]


def test_solo_banco_y_procesador_y_archivo_sin_renglones(client):
    headers, banco, _cats = _setup(client)
    caja = client.post(
        "/api/accounts", headers=headers, json={"name": "Caja chica", "type": "CASH", "opening_balance": "0"}
    ).json()
    response = _upload(client, headers, caja, _csv(["15/10/2026,Depósito,,,500.00"]))
    assert response.status_code == 400
    assert "banco" in response.json()["detail"]
    vacio = _upload(client, headers, banco, _csv(["Total,,,,"]))
    assert vacio.status_code == 400


def test_otra_empresa_no_ve_ni_toca_la_conciliacion(client):
    headers, banco, cats = _setup(client)
    _income(client, headers, banco, cats, "500")
    detail = _upload(client, headers, banco, _csv(["15/10/2026,Depósito,,,500.00"])).json()
    statement_id = detail["statement"]["id"]
    line = detail["lines"][0]
    transaction_id = line["suggestions"][0]["transactions"][0]["id"]

    otros, otro_banco, _ = _setup(client, email="otro@example.com")
    assert client.get(f"/api/bank-statements/{statement_id}", headers=otros).status_code == 404
    assert client.get("/api/bank-statements", headers=otros).json()["total"] == 0
    assert client.post(f"/api/bank-statements/{statement_id}/close", headers=otros, json={}).status_code == 404
    # Ni con su propio estado de cuenta puede tomar un movimiento ajeno.
    suyo = _upload(client, otros, otro_banco, _csv(["15/10/2026,Depósito,,,500.00"])).json()
    robo = client.post(
        f"/api/bank-statements/{suyo['statement']['id']}/lines/{suyo['lines'][0]['id']}/match",
        headers=otros,
        json={"transaction_ids": [transaction_id]},
    )
    assert robo.status_code == 404


def test_movimiento_cancelado_despues_de_conciliar_genera_alerta(client):
    headers, banco, cats = _setup(client)
    venta = _income(client, headers, banco, cats, "500")
    detail = _upload(client, headers, banco, _csv(["15/10/2026,Depósito,,,500.00"])).json()
    url = f"/api/bank-statements/{detail['statement']['id']}"
    client.post(f"{url}/auto-match", headers=headers)
    assert client.get("/api/bank-statements/alerts", headers=headers).json() == {
        "open_statements": 1,
        "pending_lines": 0,
        "difference_lines": 0,
    }
    cancel = client.post(f"/api/income/{venta['id']}/cancel", headers=headers, json={"reason": "Se capturó mal"})
    assert cancel.status_code in (200, 201), cancel.text
    kinds = {a["kind"] for a in client.get(url, headers=headers).json()["summary"]["alerts"]}
    assert "CANCELLED_MATCH" in kinds


def test_importe_con_signo_en_una_sola_columna(client):
    headers, banco, cats = _setup(client)
    _expense(client, headers, banco, cats, "800", when=DAY - timedelta(days=2))
    content = _csv(["2026-10-15;Pago renta;-800.00"], header="Fecha;Descripción;Importe")
    detail = _upload(client, headers, banco, content).json()
    line = detail["lines"][0]
    assert Decimal(line["amount"]) == Decimal("-800.00")
    assert line["suggestions"][0]["kind"] == "EXACT"
