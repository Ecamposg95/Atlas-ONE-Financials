"""Datos fiscales para CFDI (fase 2 del megaplan): validadores, API y migración.

Sin sellado ni timbrado: sólo que los datos que pedirá la factura existan, sean
claves vigentes del SAT y sean coherentes entre sí.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.database import Base
from app.services.cfdi import datos_fiscales as df
from tests.helpers import auth_headers, register

HOY = dt.date(2026, 11, 25)
CP = "64000"
# RFC de pruebas que publica el SAT; su dígito verificador cuadra.
RFC_MORAL = "EKU9003173C9"
RFC_FISICA = "CACX7605101P8"


# ---------------------------------------------------------------- RFC


@pytest.mark.parametrize(
    ("rfc", "digito"),
    [("EKU9003173C9", "9"), ("XIA190128J61", "1"), ("CACX7605101P8", "8"), ("IIA040805DZ4", "4")],
)
def test_digito_verificador_de_rfc_del_sat(rfc, digito):
    assert df.digito_verificador(rfc) == digito
    revision = df.revisar_rfc(rfc)
    assert revision.digito_correcto and revision.advertencia is None


def test_rfc_tipo_de_persona_y_normalizacion():
    assert df.revisar_rfc(" eku900317 3c9 ").persona_moral is True
    assert df.revisar_rfc(RFC_FISICA).persona_moral is False


def test_digito_que_no_cuadra_solo_advierte():
    revision = df.revisar_rfc("EKU9003173C8")
    assert revision.digito_correcto is False
    assert "dígito verificador" in revision.advertencia


@pytest.mark.parametrize("rfc", ["EKU900317", "EKU9013173C9", "EKU9003323C9", "1KU9003173C9", "ABCDE9003173C9"])
def test_rfc_con_formato_invalido_se_rechaza(rfc):
    with pytest.raises(df.DatoFiscalInvalido, match="formato válido"):
        df.revisar_rfc(rfc)


def test_rfc_genericos():
    nacional = df.revisar_rfc("XAXX010101000")
    extranjero = df.revisar_rfc("xexx010101000")
    assert (nacional.generico, extranjero.generico) == ("nacional", "extranjero")
    assert nacional.advertencia is None and nacional.persona_moral is False


# ---------------------------------------------------------------- catálogos


def test_regimen_segun_tipo_de_persona():
    df.validar_regimen("601", persona_moral=True, fecha=HOY)
    df.validar_regimen("612", persona_moral=False, fecha=HOY)
    df.validar_regimen("626", persona_moral=True, fecha=HOY)  # RESICO aplica a ambas
    with pytest.raises(df.DatoFiscalInvalido, match="no aplica a una persona física"):
        df.validar_regimen("601", persona_moral=False, fecha=HOY)
    with pytest.raises(df.DatoFiscalInvalido, match="no aplica a una persona moral"):
        df.validar_regimen("612", persona_moral=True, fecha=HOY)
    with pytest.raises(df.DatoFiscalInvalido, match="no existe"):
        df.validar_regimen("999", persona_moral=None, fecha=HOY)


def test_regimen_respeta_vigencia():
    with pytest.raises(df.DatoFiscalInvalido, match="ya no está vigente"):
        df.validar_regimen("601", persona_moral=True, fecha=dt.date(2021, 12, 31))


def test_codigo_postal():
    df.validar_codigo_postal(CP, HOY)
    with pytest.raises(df.DatoFiscalInvalido, match="cinco dígitos"):
        df.validar_codigo_postal("6400", HOY)
    with pytest.raises(df.DatoFiscalInvalido, match="no existe"):
        df.validar_codigo_postal("00001", HOY)


@pytest.mark.parametrize(
    ("uso", "regimen", "moral", "ok"),
    [
        ("G03", "601", True, True),
        ("G03", "612", False, True),
        ("G03", "616", False, False),  # sin obligaciones fiscales no deduce gastos
        ("S01", "616", False, True),
        ("D01", "612", False, True),
        ("D01", "601", True, False),  # deducciones personales: sólo persona física
        ("CN01", "605", False, True),
        ("CN01", "601", True, False),
    ],
)
def test_uso_cfdi_contra_regimen(uso, regimen, moral, ok):
    if ok:
        df.validar_uso_cfdi(uso, regimen=regimen, persona_moral=moral, fecha=HOY)
    else:
        with pytest.raises(df.DatoFiscalInvalido, match="no corresponde al régimen"):
            df.validar_uso_cfdi(uso, regimen=regimen, persona_moral=moral, fecha=HOY)


def test_uso_cfdi_sin_regimen_solo_valida_catalogo():
    df.validar_uso_cfdi("G03", regimen=None, persona_moral=None, fecha=HOY)
    with pytest.raises(df.DatoFiscalInvalido, match="no existe"):
        df.validar_uso_cfdi("G99", regimen=None, persona_moral=None, fecha=HOY)


@pytest.mark.parametrize(
    ("forma", "metodo", "error"),
    [
        ("03", "PUE", None),
        ("99", "PPD", None),
        (None, "PPD", None),
        ("01", None, None),
        ("03", "PPD", "debe ser 99"),
        ("99", "PUE", "sólo va con PPD"),
        ("77", "PUE", "no existe"),
        ("03", "XYZ", "no existe"),
    ],
)
def test_forma_y_metodo_de_pago(forma, metodo, error):
    if error is None:
        df.validar_pago(forma, metodo, HOY)
    else:
        with pytest.raises(df.DatoFiscalInvalido, match=error):
            df.validar_pago(forma, metodo, HOY)


# ---------------------------------------------------------------- listo para facturar


def test_preparacion_emisor_dice_que_falta():
    vacio = df.preparacion_emisor(rfc=None, razon_social=None, regimen=None, codigo_postal=None, fecha=HOY)
    assert vacio.listo is False and len(vacio.faltantes) == 4

    listo = df.preparacion_emisor(
        rfc=RFC_MORAL, razon_social="ESCUELA KEMPER URGATE", regimen="601", codigo_postal=CP, fecha=HOY
    )
    assert listo.listo is True and listo.faltantes == [] and listo.advertencias == []

    con_avisos = df.preparacion_emisor(
        rfc="EKU9003173C8", razon_social="Escuela Kemper Urgate, S.A. de C.V.", regimen="601", codigo_postal=CP, fecha=HOY
    )
    assert con_avisos.listo is True
    assert len(con_avisos.advertencias) == 2  # dígito y régimen de capital

    incoherente = df.preparacion_emisor(rfc=RFC_MORAL, razon_social="X", regimen="612", codigo_postal=CP, fecha=HOY)
    assert incoherente.listo is False and "persona moral" in incoherente.faltantes[0]


def test_preparacion_receptor_generico_no_pide_codigo_postal():
    prep = df.preparacion_receptor(
        rfc="XAXX010101000", razon_social="PUBLICO EN GENERAL", regimen="616", codigo_postal=None, uso_cfdi="S01", fecha=HOY
    )
    assert prep.listo is True, prep.faltantes

    mal = df.preparacion_receptor(
        rfc="XAXX010101000", razon_social="PUBLICO EN GENERAL", regimen="601", codigo_postal=None, uso_cfdi="S01", fecha=HOY
    )
    assert mal.listo is False and "616" in mal.faltantes[0]


def test_preparacion_receptor_uso_incompatible():
    prep = df.preparacion_receptor(
        rfc=RFC_FISICA, razon_social="XOCHILT CASAS CHAVEZ", regimen="605", codigo_postal=CP, uso_cfdi="G03", fecha=HOY
    )
    assert prep.listo is False and any("G03" in f for f in prep.faltantes)


# ---------------------------------------------------------------- API


def _headers(client, email="dueno@example.com"):
    return auth_headers(register(client, email=email, initial_cash="10000"))


def test_empresa_captura_datos_de_emisor(client):
    headers = _headers(client)
    actual = client.get("/api/organizations/current", headers=headers).json()
    assert actual["fiscal_readiness"]["listo"] is False

    response = client.patch(
        "/api/organizations/current",
        headers=headers,
        json={"legal_name": "ESCUELA KEMPER URGATE", "tax_id": "eku9003173c9", "fiscal_regime": "601", "fiscal_postal_code": CP},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tax_id"] == RFC_MORAL and body["fiscal_regime"] == "601"
    assert body["fiscal_readiness"] == {"listo": True, "faltantes": [], "advertencias": []}


@pytest.mark.parametrize(
    ("payload", "mensaje"),
    [
        ({"tax_id": "NO-ES-RFC"}, "formato válido"),
        ({"tax_id": RFC_MORAL, "fiscal_regime": "612"}, "no aplica a una persona moral"),
        ({"fiscal_postal_code": "00001"}, "no existe"),
        ({"tax_id": "XAXX010101000"}, "genérico no puede emitir"),
    ],
)
def test_empresa_rechaza_datos_fiscales_invalidos(client, payload, mensaje):
    headers = _headers(client)
    response = client.patch("/api/organizations/current", headers=headers, json=payload)
    assert response.status_code == 400
    assert mensaje in response.json()["detail"]


def test_contribuyente_como_emisor(client):
    headers = _headers(client)
    response = client.post(
        "/api/fiscal-entities",
        headers=headers,
        json={"name": "Xóchitl", "tax_id": RFC_FISICA, "legal_name": "XOCHILT CASAS CHAVEZ", "fiscal_regime": "612", "fiscal_postal_code": CP},
    )
    assert response.status_code == 201, response.text
    entity = response.json()
    assert entity["fiscal_readiness"]["listo"] is True

    bad = client.patch(f"/api/fiscal-entities/{entity['id']}", headers=headers, json={"fiscal_regime": "601"})
    assert bad.status_code == 400 and "persona física" in bad.json()["detail"]


def _customer(client, headers, **fields):
    response = client.post("/api/customers", headers=headers, json={"name": "Cliente", **fields})
    return response


def test_cliente_con_datos_de_receptor(client):
    headers = _headers(client)
    response = _customer(
        client, headers, legal_name="ESCUELA KEMPER URGATE", tax_id=RFC_MORAL,
        fiscal_regime="601", fiscal_postal_code=CP, default_cfdi_use="g03",
    )
    assert response.status_code == 201, response.text
    customer = response.json()
    assert customer["default_cfdi_use"] == "G03"
    assert customer["fiscal_readiness"]["listo"] is True

    # Cambiar el régimen a uno incompatible con el uso guardado se rechaza.
    bad = client.patch(f"/api/customers/{customer['id']}", headers=headers, json={"fiscal_regime": "616"})
    assert bad.status_code == 400

    incompleto = _customer(client, headers).json()
    faltan = incompleto["fiscal_readiness"]["faltantes"]
    assert incompleto["fiscal_readiness"]["listo"] is False and len(faltan) == 5


def test_cliente_publico_en_general(client):
    headers = _headers(client)
    ok = _customer(
        client, headers, legal_name="PUBLICO EN GENERAL", tax_id="XAXX010101000", fiscal_regime="616", default_cfdi_use="S01"
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["fiscal_readiness"]["listo"] is True

    mal = _customer(client, headers, tax_id="XAXX010101000", fiscal_regime="601")
    assert mal.status_code == 400 and "616" in mal.json()["detail"]


def test_proveedores_no_cambian(client):
    headers = _headers(client)
    vendor = client.post("/api/vendors", headers=headers, json={"name": "Papelería", "tax_id": "lo que sea"})
    assert vendor.status_code == 201
    assert "fiscal_readiness" not in vendor.json()


def _income_payload(client, headers, **extra):
    ventas = next(c for c in client.get("/api/categories?kind=INCOME", headers=headers).json() if c["name"] == "Ventas")
    return {"date": "2026-11-20", "description": "Venta", "amount": "1160", "tax_rate": "0.16", "category_id": ventas["id"], **extra}


def test_ingreso_con_uso_forma_y_metodo(client):
    headers = _headers(client)
    customer = _customer(client, headers, tax_id=RFC_MORAL, fiscal_regime="601").json()
    payload = _income_payload(
        client, headers, customer_id=customer["id"], cfdi_use="G01", cfdi_payment_form="03", cfdi_payment_method="PUE"
    )
    response = client.post("/api/income", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    income = response.json()
    assert (income["cfdi_use"], income["cfdi_payment_form"], income["cfdi_payment_method"]) == ("G01", "03", "PUE")

    # PPD exige forma 99 también al editar, en cualquier estado.
    bad = client.patch(f"/api/income/{income['id']}", headers=headers, json={"cfdi_payment_method": "PPD"})
    assert bad.status_code == 400 and "99" in bad.json()["detail"]
    ok = client.patch(
        f"/api/income/{income['id']}", headers=headers, json={"cfdi_payment_method": "PPD", "cfdi_payment_form": "99"}
    )
    assert ok.status_code == 200 and ok.json()["cfdi_payment_form"] == "99"


def test_ingreso_uso_incompatible_con_regimen_del_cliente(client):
    headers = _headers(client)
    customer = _customer(client, headers, tax_id=RFC_MORAL, fiscal_regime="601").json()
    response = client.post(
        "/api/income", headers=headers, json=_income_payload(client, headers, customer_id=customer["id"], cfdi_use="D01")
    )
    assert response.status_code == 400 and "D01" in response.json()["detail"]


def test_datos_fiscales_no_tocan_el_libro(client):
    headers = _headers(client)
    customer = _customer(client, headers, tax_id=RFC_MORAL, fiscal_regime="601").json()
    ventas_id = _income_payload(client, headers)["category_id"]
    receivable = client.post(
        "/api/receivables",
        headers=headers,
        json={
            "customer_id": customer["id"], "description": "Crédito", "amount": "1160", "tax_rate": "0.16",
            "due_date": "2026-12-31", "category_id": ventas_id, "cfdi_payment_method": "PPD", "cfdi_payment_form": "99",
        },
    )
    assert receivable.status_code == 201, receivable.text
    before = client.get("/api/accounting/trial-balance", headers=headers).json()["rows"]

    rid = receivable.json()["id"]
    patched = client.patch(f"/api/receivables/{rid}", headers=headers, json={"cfdi_use": "G03"})
    assert patched.status_code == 200 and patched.json()["cfdi_use"] == "G03"
    assert patched.json()["amount"] == "1160.00"
    bad = client.patch(f"/api/receivables/{rid}", headers=headers, json={"cfdi_payment_form": "04"})
    assert bad.status_code == 400

    after = client.get("/api/accounting/trial-balance", headers=headers).json()["rows"]
    assert before == after
    balances = {row["code"]: Decimal(str(row["balance"])) for row in after}
    assert balances["1200"] == Decimal("1160")


def test_cuenta_por_cobrar_ajena_no_se_edita(client):
    headers = _headers(client)
    customer = _customer(client, headers).json()
    ventas_id = _income_payload(client, headers)["category_id"]
    rid = client.post(
        "/api/receivables",
        headers=headers,
        json={"customer_id": customer["id"], "description": "x", "amount": "100", "due_date": "2026-12-31", "category_id": ventas_id},
    ).json()["id"]
    otro = _headers(client, email="otro@example.com")
    response = client.patch(f"/api/receivables/{rid}", headers=otro, json={"cfdi_use": "G03"})
    assert response.status_code == 404


def test_catalogos_para_captura(client):
    headers = _headers(client)
    morales = client.get("/api/fiscal-mx/catalogs/c_RegimenFiscal?persona=moral", headers=headers).json()["items"]
    claves = {row["clave"] for row in morales}
    assert "601" in claves and "612" not in claves

    por_rfc = client.get(f"/api/fiscal-mx/catalogs/c_RegimenFiscal?rfc={RFC_FISICA}", headers=headers).json()["items"]
    assert "612" in {row["clave"] for row in por_rfc} and "601" not in {row["clave"] for row in por_rfc}

    usos = client.get("/api/fiscal-mx/catalogs/c_UsoCFDI?regimen=616", headers=headers).json()["items"]
    assert "S01" in {row["clave"] for row in usos} and "G03" not in {row["clave"] for row in usos}

    assert client.get("/api/fiscal-mx/catalogs/c_ClaveProdServ", headers=headers).status_code == 404
    assert client.get("/api/fiscal-mx/catalogs/c_FormaPago").status_code == 401


# ---------------------------------------------------------------- migración


def test_migracion_un_solo_head_y_columnas_nullable():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    raiz = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(raiz / "alembic.ini")))
    assert len(script.get_heads()) == 1

    migracion = script.get_revision("20261125_01").module
    for tabla, columnas in migracion._COLUMNAS.items():
        modelo = Base.metadata.tables[tabla]
        for nombre, tipo in columnas:
            columna = modelo.columns[nombre]
            assert columna.nullable, f"{tabla}.{nombre} debe ser nullable"
            assert columna.type.length == tipo.length, f"{tabla}.{nombre}: largo distinto al modelo"


@pytest.mark.postgres
def test_migracion_aplicada_en_postgres(db):
    from sqlalchemy import inspect

    inspector = inspect(db.get_bind())
    columnas = {c["name"]: c for c in inspector.get_columns("customers")}
    assert columnas["default_cfdi_use"]["nullable"] is True
    assert {"cfdi_use", "cfdi_payment_form", "cfdi_payment_method"} <= {c["name"] for c in inspector.get_columns("incomes")}
