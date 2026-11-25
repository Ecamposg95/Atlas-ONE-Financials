"""Documento fiscal (CFDI 4.0 de ingreso): armado, validación previa, XML sin sellar y API.

Sin sellado ni timbrado. Lo que se prueba aquí: que los montos de la
operación nunca se corrigen, que las reglas del Anexo 20 y de la matriz de
errores se revisan antes de sellar, que el XML pasa el XSD oficial, que nada
toca el libro y que cada empresa sólo ve sus facturas.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from decimal import Decimal as D
from pathlib import Path

import pytest
from lxml import etree

from app.domains.fiscal_mx import documentos as docs_service
from app.models.fiscal_document import FiscalDocumentXml, XmlInmutable
from app.services.cfdi import xml_sat
from app.services.cfdi.armado import ErrorArmado, Operacion, Renglon, armar
from app.services.cfdi.comprobante import (
    NS_CFDI,
    RETENCION,
    Comprobante,
    Emisor,
    Impuesto,
    Receptor,
    limites_importe,
    limites_impuesto,
    resumir,
    xml_sin_sellar,
)
from app.services.cfdi.validacion import Contexto, validar
from app.services.cfdi.zona_horaria import hora_local
from app.services.taxes import split_total
from tests.helpers import auth_headers, register

NS = {"cfdi": NS_CFDI}
RFC_MORAL = "EKU9003173C9"
RFC_CLIENTE = "URE180429TM6"
CP_MTY = "64000"  # Tiempo del Centro, sin franja fronteriza
CP_TIJUANA = "22000"  # Tiempo del Noroeste, franja fronteriza norte
FECHA = dt.datetime(2026, 11, 25, 10, 0, 0)
FECHA_UTC = dt.datetime(2026, 11, 25, 16, 0, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- ayudas puras


def _op(total: str, tasa: str = "0.16") -> Operacion:
    b = split_total(D(total), D(tasa))
    return Operacion("Servicio de contabilidad", b.subtotal, b.tax_amount, b.total, D(tasa))


def _comprobante(armado, *, lugar=CP_MTY, receptor=None, forma="03", metodo="PUE", fecha=FECHA) -> Comprobante:
    r = resumir(armado.conceptos)
    return Comprobante(
        serie="A",
        folio="1",
        fecha=fecha,
        lugar_expedicion=lugar,
        emisor=Emisor(RFC_MORAL, "ESCUELA KEMPER URGATE", "601"),
        receptor=receptor or Receptor(RFC_CLIENTE, "UNIVERSIDAD ROBOTICA ESPAÑOLA", "86991", "601", "G03"),
        conceptos=armado.conceptos,
        subtotal=r.subtotal,
        total=r.total,
        descuento=r.descuento,
        total_impuestos_trasladados=r.total_trasladados,
        total_impuestos_retenidos=r.total_retenidos,
        forma_pago=forma,
        metodo_pago=metodo,
    )


def _ctx(op: Operacion | None = None, *, ahora=FECHA_UTC, fecha_utc=FECHA_UTC, liquidada=True) -> Contexto:
    return Contexto(ahora_utc=ahora, fecha_emision_utc=fecha_utc, operacion=op, operacion_liquidada=liquidada)


def _codigos(resultado) -> set[str]:
    return {p.codigo for p in resultado.problemas}


def _raiz(xml: bytes):
    return etree.fromstring(xml)


# ---------------------------------------------------------------- IVA 16 / 8 / 0 / exento / no objeto


def test_iva_16_concepto_unico_valida_contra_xsd_y_cuadra_con_la_operacion():
    op = _op("1160.00")
    armado = armar(op)
    assert len(armado.conceptos) == 1
    concepto = armado.conceptos[0]
    assert (concepto.cantidad, concepto.valor_unitario, concepto.importe) == (D("1"), D("1000.00"), D("1000.00"))
    assert concepto.clave_prod_serv == "01010101" and concepto.clave_unidad == "E48"
    assert any("un solo concepto" in s for s in armado.supuestos)

    comp = _comprobante(armado)
    xml = xml_sin_sellar(comp)
    assert xml_sat.errores_xsd(xml) == []
    raiz = _raiz(xml)
    assert (raiz.get("SubTotal"), raiz.get("Total"), raiz.get("NoCertificado"), raiz.get("Sello")) == (
        "1000.00",
        "1160.00",
        "0" * 20,
        "",
    )
    traslado = raiz.find("cfdi:Impuestos/cfdi:Traslados/cfdi:Traslado", NS)
    assert (traslado.get("Base"), traslado.get("TasaOCuota"), traslado.get("Importe")) == ("1000.00", "0.160000", "160.00")

    resultado = validar(comp, _ctx(op))
    assert resultado.listo, resultado.problemas
    assert {a.codigo for a in resultado.advertencias} == {"ATLAS-CLAVE-GENERICA"}


def test_cadena_original_con_la_xslt_oficial():
    comp = _comprobante(armar(_op("1160.00")))
    cadena = xml_sat.cadena_original(xml_sin_sellar(comp, leyenda="BORRADOR"))
    assert cadena.startswith("||4.0|A|1|2026-11-25T10:00:00|03|00000000000000000000|1000.00|MXN|1160.00|I|01|PUE|64000|")
    assert cadena.endswith("|1000.00|002|Tasa|0.160000|160.00|160.00||")
    assert "BORRADOR" not in cadena  # la leyenda es un comentario: no entra a la cadena


def test_iva_8_en_franja_fronteriza_y_advertencia_fuera_de_ella():
    op = _op("1080.00", "0.08")
    armado = armar(op)
    assert armado.conceptos[0].traslados[0].tasa_o_cuota == D("0.080000")
    en_frontera = validar(_comprobante(armado, lugar=CP_TIJUANA), _ctx(op))
    assert en_frontera.listo, en_frontera.problemas
    assert "ATLAS-IVA-8" not in {a.codigo for a in en_frontera.advertencias}
    fuera = validar(_comprobante(armado, lugar=CP_MTY), _ctx(op))
    assert fuera.listo and "ATLAS-IVA-8" in {a.codigo for a in fuera.advertencias}


def test_tasa_cero_lleva_traslado_en_cero():
    op = _op("500.00", "0")
    with pytest.raises(ErrorArmado, match="tasa 0 %, exenta o no objeto"):
        armar(op)
    armado = armar(op, tratamiento="tasa_0")
    comp = _comprobante(armado)
    raiz = _raiz(xml_sin_sellar(comp))
    impuestos = raiz.find("cfdi:Impuestos", NS)
    assert impuestos.get("TotalImpuestosTrasladados") == "0.00"
    assert impuestos.find("cfdi:Traslados/cfdi:Traslado", NS).get("TasaOCuota") == "0.000000"
    assert validar(comp, _ctx(op)).listo


def test_exento_sin_tasa_ni_total_trasladado():
    op = _op("500.00", "0")
    comp = _comprobante(armar(op, tratamiento="exento"))
    xml = xml_sin_sellar(comp)
    assert xml_sat.errores_xsd(xml) == []
    impuestos = _raiz(xml).find("cfdi:Impuestos", NS)
    assert impuestos.get("TotalImpuestosTrasladados") is None  # CFDI40212/40213: sólo exentos
    traslado = impuestos.find("cfdi:Traslados/cfdi:Traslado", NS)
    assert dict(traslado.attrib) == {"Base": "500.00", "Impuesto": "002", "TipoFactor": "Exento"}
    assert validar(comp, _ctx(op)).listo


def test_no_objeto_sin_nodo_de_impuestos():
    op = _op("500.00", "0")
    comp = _comprobante(armar(op, tratamiento="no_objeto"))
    raiz = _raiz(xml_sin_sellar(comp))
    assert raiz.find("cfdi:Impuestos", NS) is None
    assert raiz.find("cfdi:Conceptos/cfdi:Concepto", NS).get("ObjetoImp") == "01"
    assert validar(comp, _ctx(op)).listo


def test_tratamiento_contradictorio_se_rechaza():
    with pytest.raises(ErrorArmado, match="lleva IVA al 16"):
        armar(_op("1160.00"), tratamiento="exento")
    with pytest.raises(ErrorArmado, match="no es una tasa"):
        armar(Operacion("x", D("100"), D("10.00"), D("110.00"), D("0.10")))


# ---------------------------------------------------------------- descuentos y centavos


def test_descuentos_por_renglon():
    # Subtotal de la operación = base después de descuentos: 1500 − 150 + 500 − 0 = 1850.
    op = Operacion("Pedido", D("1850.00"), D("296.00"), D("2146.00"), D("0.16"))
    armado = armar(
        op,
        renglones=[
            Renglon("Silla", D("3"), D("500.00"), descuento=D("150.00"), clave_prod_serv="56101504", clave_unidad="H87"),
            Renglon("Instalación", D("1"), D("500.00"), clave_prod_serv="72151500"),
        ],
    )
    comp = _comprobante(armado)
    assert (comp.subtotal, comp.descuento, comp.total) == (D("2000.00"), D("150.00"), D("2146.00"))
    raiz = _raiz(xml_sin_sellar(comp))
    assert raiz.get("Descuento") == "150.00"
    silla = raiz.find("cfdi:Conceptos/cfdi:Concepto", NS)
    assert (silla.get("Importe"), silla.get("Descuento")) == ("1500.00", "150.00")
    assert silla.find("cfdi:Impuestos/cfdi:Traslados/cfdi:Traslado", NS).get("Base") == "1350.00"
    resultado = validar(comp, _ctx(op))
    assert resultado.listo, resultado.problemas


def test_renglones_que_no_suman_la_operacion_no_se_ajustan():
    op = _op("1160.00")
    with pytest.raises(ErrorArmado, match="no se ajustan montos"):
        armar(op, renglones=[Renglon("a", D("1"), D("999.99"))])
    with pytest.raises(ErrorArmado, match="mayor que el importe"):
        armar(op, renglones=[Renglon("a", D("1"), D("100.00"), descuento=D("100.01"))])


def test_centavos_se_reparten_dentro_de_la_tolerancia():
    # 3 × 33.33/33.33/33.34: IVA por renglón 5.33 + 5.33 + 5.33 = 15.99 ≠ 16.00.
    op = Operacion("x", D("100.00"), D("16.00"), D("116.00"), D("0.16"))
    armado = armar(
        op, renglones=[Renglon("a", D("1"), D("33.33")), Renglon("b", D("1"), D("33.33")), Renglon("c", D("1"), D("33.34"))]
    )
    importes = [c.traslados[0].importe for c in armado.conceptos]
    assert sum(importes) == D("16.00") and importes == [D("5.34"), D("5.33"), D("5.33")]
    for c in armado.conceptos:
        inferior, superior = limites_impuesto(c.base, D("0.16"))
        assert inferior <= c.traslados[0].importe <= superior
    assert validar(_comprobante(armado), _ctx(op)).listo


def test_iva_fuera_de_tolerancia_es_error_y_no_se_corrige():
    op = Operacion("x", D("100.00"), D("16.02"), D("116.02"), D("0.16"))
    with pytest.raises(ErrorArmado, match=r"debería quedar entre \$15\.99 y \$16\.01"):
        armar(op)
    with pytest.raises(ErrorArmado, match="no cuadra"):
        armar(Operacion("x", D("100.00"), D("16.00"), D("116.01"), D("0.16")))


@pytest.mark.parametrize("tasa", ["0.16", "0.08"])
def test_todo_total_capturado_se_puede_facturar_sin_tocar_centavos(tasa):
    """Los totales que parte ``split_total`` (IVA por diferencia) caben en la tolerancia del SAT."""
    for centavos in range(1, 3001):
        op = _op(str(D(centavos) / 100), tasa)
        comp = _comprobante(armar(op))
        assert (comp.subtotal, comp.total_impuestos_trasladados, comp.total) == (op.subtotal, op.impuesto, op.total)


def test_limites_del_anexo_20():
    # Los decimales escritos mandan: una cantidad entera tolera ±0.5 unidades.
    assert limites_importe(D("3"), D("33.333333")) == (D("83.33"), D("116.67"))
    assert limites_importe(D("2.5"), D("33.33")) == (D("81.64"), D("85.01"))
    assert limites_impuesto(D("1000.00"), D("0.160000")) == (D("159.99"), D("160.01"))


# ---------------------------------------------------------------- validación previa


def test_publico_en_general_xaxx():
    op = _op("116.00")
    armado = armar(op)
    bien = Receptor("XAXX010101000", "JUAN PEREZ", CP_MTY, "616", "S01")
    assert validar(_comprobante(armado, receptor=bien), _ctx(op)).listo

    mal = Receptor("XAXX010101000", "PUBLICO EN GENERAL", "86991", "601", "G03")
    codigos = _codigos(validar(_comprobante(armado, receptor=mal), _ctx(op)))
    assert {"CFDI40130", "CFDI40159", "CFDI40149"} <= codigos


def test_uso_cfdi_y_regimen_deben_corresponder():
    op = _op("116.00")
    receptor = Receptor(RFC_CLIENTE, "UNIVERSIDAD ROBOTICA ESPAÑOLA", "86991", "601", "D01")
    assert "CFDI40161" in _codigos(validar(_comprobante(armar(op), receptor=receptor), _ctx(op)))
    persona = Receptor(RFC_CLIENTE, "UNIVERSIDAD ROBOTICA ESPAÑOLA", "86991", "612", "G03")
    assert "CFDI40158" in _codigos(validar(_comprobante(armar(op), receptor=persona), _ctx(op)))


def test_ventana_de_72_horas_y_fecha_futura():
    op = _op("116.00")
    comp = _comprobante(armar(op))
    assert validar(comp, _ctx(op, ahora=FECHA_UTC + dt.timedelta(hours=71, minutes=59))).listo
    vieja = validar(comp, _ctx(op, ahora=FECHA_UTC + dt.timedelta(hours=72, minutes=1)))
    assert "401" in _codigos(vieja) and "72 horas" in vieja.problemas[0].mensaje
    futura = validar(comp, _ctx(op, ahora=FECHA_UTC - dt.timedelta(hours=1)))
    assert "401" in _codigos(futura)


def test_pue_ppd_y_forma_99():
    op = _op("116.00")
    armado = armar(op)
    assert "CFDI40105" in _codigos(validar(_comprobante(armado, forma="03", metodo="PPD"), _ctx(op)))
    assert "ATLAS-PUE-99" in _codigos(validar(_comprobante(armado, forma="99", metodo="PUE"), _ctx(op)))
    ppd = validar(_comprobante(armado, forma="99", metodo="PPD"), _ctx(op, liquidada=False))
    assert ppd.listo
    pendiente = validar(_comprobante(armado, forma="03", metodo="PUE"), _ctx(op, liquidada=False))
    assert pendiente.listo and "ATLAS-PUE-PENDIENTE" in {a.codigo for a in pendiente.advertencias}
    sin_datos = validar(_comprobante(armado, forma=None, metodo=None), _ctx(op))
    assert {"CFDI40104", "CFDI40124"} <= _codigos(sin_datos)


def test_claves_vigentes_a_la_fecha_de_emision():
    op = _op("116.00")
    armado = armar(op, clave_prod_serv="99999999")
    armado.conceptos[0].objeto_imp = "06"  # vigente desde 2024-12-13
    fecha = dt.datetime(2024, 6, 1, 10, 0, 0)
    fecha_utc = dt.datetime(2024, 6, 1, 16, 0, 0, tzinfo=dt.timezone.utc)
    resultado = validar(_comprobante(armado, fecha=fecha), _ctx(op, ahora=fecha_utc, fecha_utc=fecha_utc))
    mensajes = {p.codigo: p.mensaje for p in resultado.problemas}
    assert "no existe" in mensajes["CFDI40162"]
    assert "no está vigente el 2024-06-01" in mensajes["CFDI40170"]


def test_sumas_alteradas_se_detectan_con_su_codigo_del_sat():
    op = _op("1160.00")
    comp = _comprobante(armar(op))
    comp.conceptos[0].importe = D("1600.00")  # cantidad 1 × 1000.00 tolera hasta 1500.01
    comp.conceptos[0].traslados[0].importe = D("170.00")
    comp.total = D("1160.01")
    codigos = _codigos(validar(comp, _ctx(op)))
    assert {"CFDI40167", "CFDI40180", "CFDI40108", "CFDI40205", "CFDI40119", "ATLAS-CUADRE"} <= codigos


def test_cuadre_contra_la_operacion():
    comp = _comprobante(armar(_op("1160.00")))
    otra = _op("1276.00")
    problemas = [p for p in validar(comp, _ctx(otra)).problemas if p.codigo == "ATLAS-CUADRE"]
    assert len(problemas) == 3 and "no se ajustan aquí" in problemas[0].mensaje


def test_xsd_atrapa_lo_que_falta():
    comp = _comprobante(armar(_op("116.00")))
    comp.emisor.rfc = None
    resultado = validar(comp, _ctx(_op("116.00")))
    assert "ATLAS-DATOS" in _codigos(resultado) and "ATLAS-XSD" in _codigos(resultado)
    assert any("Rfc" in p.mensaje for p in resultado.problemas if p.codigo == "ATLAS-XSD")


def test_retenciones_en_el_xml():
    armado = armar(_op("1160.00"))
    concepto = armado.conceptos[0]
    concepto.impuestos.append(Impuesto(RETENCION, "002", "Tasa", D("0.106667"), D("1000.00"), D("106.67")))
    comp = _comprobante(armado)
    assert comp.total == D("1053.33") and comp.total_impuestos_retenidos == D("106.67")
    xml = xml_sin_sellar(comp)
    assert xml_sat.errores_xsd(xml) == []
    raiz = _raiz(xml)
    assert raiz.find("cfdi:Impuestos/cfdi:Retenciones/cfdi:Retencion", NS).get("Importe") == "106.67"
    resultado = validar(comp, _ctx(Operacion("x", D("1000.00"), D("160.00"), D("1053.33"), D("0.16"))))
    assert not {c for c in _codigos(resultado) if c.startswith("CFDI")}


# ---------------------------------------------------------------- zona horaria y recursos


@pytest.mark.parametrize(
    ("cp", "instante", "esperado", "huso"),
    [
        (CP_MTY, dt.datetime(2026, 7, 1, 18, 0), dt.datetime(2026, 7, 1, 12, 0), "Tiempo del Centro"),
        ("77500", dt.datetime(2026, 1, 1, 18, 0), dt.datetime(2026, 1, 1, 13, 0), "Tiempo del Sureste"),
        (CP_TIJUANA, dt.datetime(2026, 1, 15, 20, 0), dt.datetime(2026, 1, 15, 12, 0), "Tiempo del Noroeste"),
        (CP_TIJUANA, dt.datetime(2026, 7, 15, 19, 0), dt.datetime(2026, 7, 15, 12, 0), "Tiempo del Noroeste"),
        # Cambio de horario 2026: 8 de marzo a las 02:00 (−8 → −7), 1 de noviembre a las 02:00 (−7 → −8).
        (CP_TIJUANA, dt.datetime(2026, 3, 8, 9, 59), dt.datetime(2026, 3, 8, 1, 59), "Tiempo del Noroeste"),
        (CP_TIJUANA, dt.datetime(2026, 3, 8, 10, 0), dt.datetime(2026, 3, 8, 3, 0), "Tiempo del Noroeste"),
        (CP_TIJUANA, dt.datetime(2026, 11, 1, 9, 0), dt.datetime(2026, 11, 1, 1, 0), "Tiempo del Noroeste"),
    ],
)
def test_hora_local_por_codigo_postal(cp, instante, esperado, huso):
    hora = hora_local(cp, instante.replace(tzinfo=dt.timezone.utc))
    assert (hora.local, hora.huso) == (esperado, huso)


def test_recursos_sat_vendorizados_intactos():
    raiz = Path(xml_sat.__file__).resolve().parent / "recursos_sat"
    manifiesto = json.loads((raiz / "manifest.json").read_text(encoding="utf-8"))
    assert xml_sat.URL_XSD_40 in manifiesto["archivos"] and xml_sat.URL_XSLT_40 in manifiesto["archivos"]
    for url, entrada in manifiesto["archivos"].items():
        assert hashlib.sha256(xml_sat._bytes(url)).hexdigest() == entrada["sha256"]
    assert [f["url"] for f in xml_sat.faltantes()] == ["http://www.sat.gob.mx/sitio_internet/cfd/divisas/divisas.xslt"]


# ---------------------------------------------------------------- límites del módulo


def test_el_modulo_fiscal_no_toca_el_libro():
    raiz = Path(__file__).resolve().parents[1] / "app"
    archivos = [*(raiz / "services" / "cfdi").glob("*.py"), *(raiz / "domains" / "fiscal_mx").glob("*.py")]
    prohibido = re.compile(r"app\.services\.accounting|app\.services\.transactions|post_journal_entry\(|record_transaction\(")
    for archivo in archivos:
        assert not prohibido.search(archivo.read_text(encoding="utf-8")), archivo.name


# ---------------------------------------------------------------- API


def _empresa(client, email="dueno@example.com", cp=CP_MTY):
    headers = auth_headers(register(client, email=email, initial_cash="10000"))
    ok = client.patch(
        "/api/organizations/current",
        headers=headers,
        json={"legal_name": "ESCUELA KEMPER URGATE", "tax_id": RFC_MORAL, "fiscal_regime": "601", "fiscal_postal_code": cp},
    )
    assert ok.status_code == 200, ok.text
    return headers


def _cliente(client, headers, **campos):
    datos = {
        "name": "Universidad",
        "legal_name": "UNIVERSIDAD ROBOTICA ESPAÑOLA",
        "tax_id": RFC_CLIENTE,
        "fiscal_regime": "601",
        "fiscal_postal_code": "86991",
        "default_cfdi_use": "G03",
        **campos,
    }
    response = client.post("/api/customers", headers=headers, json=datos)
    assert response.status_code == 201, response.text
    return response.json()


def _ventas(client, headers):
    categorias = client.get("/api/categories?kind=INCOME", headers=headers).json()
    return next(c for c in categorias if c["name"] == "Ventas")["id"]


def _ingreso(client, headers, customer_id, **extra):
    cuenta = client.get("/api/accounts", headers=headers).json()[0]
    payload = {
        "date": "2026-11-20",
        "description": "Servicio de contabilidad noviembre",
        "amount": "1160",
        "tax_rate": "0.16",
        "category_id": _ventas(client, headers),
        "customer_id": customer_id,
        "financial_account_id": cuenta["id"],
        "status": "PAID",
        "cfdi_payment_form": "03",
        "cfdi_payment_method": "PUE",
        **extra,
    }
    response = client.post("/api/income", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _crear(client, headers, origen_id, origen_tipo="income", **extra):
    return client.post(
        "/api/fiscal-mx/documents", headers=headers, json={"origen_tipo": origen_tipo, "origen_id": origen_id, **extra}
    )


def _libro(client, headers) -> dict:
    return {
        "balanza": client.get("/api/accounting/trial-balance", headers=headers).json()["rows"],
        "cuentas": [(a["id"], a["current_balance"]) for a in client.get("/api/accounts", headers=headers).json()],
        "movimientos": client.get("/api/transactions", headers=headers).json()["total"],
        "polizas": client.get("/api/accounting/journal-entries", headers=headers).json()["total"],
    }


def test_api_borrador_desde_ingreso_validacion_y_xml(client):
    headers = _empresa(client)
    cliente = _cliente(client, headers)
    ingreso = _ingreso(client, headers, cliente["id"])
    libro_antes = _libro(client, headers)

    response = _crear(client, headers, ingreso["id"])
    assert response.status_code == 201, response.text
    doc = response.json()
    assert (doc["estado"], doc["serie"], doc["folio"], doc["validez_fiscal"]) == ("BORRADOR", "A", "1", False)
    assert (doc["subtotal"], doc["total_impuestos_trasladados"], doc["total"]) == ("1000.00", "160.00", "1160.00")
    assert (doc["emisor_rfc"], doc["receptor_rfc"], doc["receptor_uso_cfdi"]) == (RFC_MORAL, RFC_CLIENTE, "G03")
    assert (doc["lugar_expedicion"], doc["huso_horario"]) == (CP_MTY, "Tiempo del Centro")
    assert doc["conceptos"][0]["descripcion"] == "Servicio de contabilidad noviembre"
    assert doc["conceptos"][0]["impuestos"][0]["importe"] == "160.00"
    assert any("01010101" in s for s in doc["supuestos"])

    validacion = client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers)
    assert validacion.status_code == 200, validacion.text
    assert validacion.json()["listo"] is True, validacion.json()
    leido = client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()
    assert leido["estado"] == "LISTO_PARA_TIMBRAR" and leido["validacion"]["listo"] is True

    xml = client.get(f"/api/fiscal-mx/documents/{doc['id']}/xml", headers=headers)
    assert xml.status_code == 200
    assert xml.headers["content-type"].startswith("application/xml")
    assert "BORRADOR-SIN-VALIDEZ-FISCAL-A-1.xml" in xml.headers["content-disposition"]
    assert "ninguna" in xml.headers["x-validez-fiscal"]
    assert b"NO TIENE VALIDEZ FISCAL" in xml.content
    assert xml_sat.errores_xsd(xml.content) == []
    assert _raiz(xml.content).get("Total") == "1160.00"

    listado = client.get(f"/api/fiscal-mx/documents?origen_id={ingreso['id']}", headers=headers).json()
    assert listado["total"] == 1 and listado["items"][0]["id"] == doc["id"]

    # Facturar no mueve el libro, ni la operación.
    assert _libro(client, headers) == libro_antes
    assert client.get(f"/api/income/{ingreso['id']}", headers=headers).json()["amount"] == "1160.00"


def test_api_cuenta_por_cobrar_ppd(client):
    headers = _empresa(client)
    cliente = _cliente(client, headers)
    cxc = client.post(
        "/api/receivables",
        headers=headers,
        json={
            "customer_id": cliente["id"], "description": "Crédito a 30 días", "amount": "2320", "tax_rate": "0.16",
            "due_date": "2026-12-31", "category_id": _ventas(client, headers),
            "cfdi_payment_method": "PPD", "cfdi_payment_form": "99",
        },
    )
    assert cxc.status_code == 201, cxc.text
    libro_antes = _libro(client, headers)
    doc = _crear(client, headers, cxc.json()["id"], origen_tipo="receivable").json()
    assert (doc["metodo_pago"], doc["forma_pago"], doc["total"]) == ("PPD", "99", "2320.00")
    resultado = client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()
    assert resultado["listo"] is True, resultado
    assert _libro(client, headers) == libro_antes


def test_api_problemas_en_espanol_con_datos_incompletos(client):
    headers = auth_headers(register(client, initial_cash="10000"))  # empresa sin datos fiscales
    cliente = _cliente(client, headers, fiscal_regime=None, default_cfdi_use=None)
    ingreso = _ingreso(client, headers, cliente["id"], cfdi_payment_form=None, cfdi_payment_method=None)
    doc = _crear(client, headers, ingreso["id"]).json()
    resultado = client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()
    assert resultado["listo"] is False
    campos = {p["campo"] for p in resultado["problemas"]}
    assert {"emisor.rfc", "emisor.regimen_fiscal", "lugar_expedicion", "receptor.regimen_fiscal", "receptor.uso_cfdi", "forma_pago", "metodo_pago"} <= campos
    assert all(p["mensaje"] for p in resultado["problemas"])
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()["estado"] == "BORRADOR"


def test_api_rearmar_toma_los_datos_nuevos_y_conserva_el_folio(client):
    headers = _empresa(client)
    cliente = _cliente(client, headers, default_cfdi_use=None)  # sin uso de CFDI
    ingreso = _ingreso(client, headers, cliente["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    assert client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()["listo"] is False

    assert client.patch(f"/api/customers/{cliente['id']}", headers=headers, json={"default_cfdi_use": "G03"}).status_code == 200
    nuevo = client.post(f"/api/fiscal-mx/documents/{doc['id']}/rebuild", headers=headers, json={})
    assert nuevo.status_code == 200, nuevo.text
    assert (nuevo.json()["receptor_uso_cfdi"], nuevo.json()["folio"], nuevo.json()["estado"]) == ("G03", "1", "BORRADOR")
    assert client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()["listo"] is True

    # Una sola factura activa por operación.
    otra = _crear(client, headers, ingreso["id"])
    assert otra.status_code == 409 and "A-1" in otra.json()["detail"]


def test_api_folio_por_emisor(client):
    headers = _empresa(client)
    cliente = _cliente(client, headers)
    entidad = client.post(
        "/api/fiscal-entities",
        headers=headers,
        json={"name": "Xóchitl", "tax_id": "CACX7605101P8", "legal_name": "XOCHILT CASAS CHAVEZ", "fiscal_regime": "612", "fiscal_postal_code": CP_TIJUANA},
    ).json()
    folios = []
    for extra in ({}, {}, {"fiscal_entity_id": entidad["id"]}):
        ingreso = _ingreso(client, headers, cliente["id"], **extra)
        doc = _crear(client, headers, ingreso["id"]).json()
        folios.append((doc["emisor_rfc"], doc["folio"], doc["lugar_expedicion"]))
    assert folios == [(RFC_MORAL, "1", CP_MTY), (RFC_MORAL, "2", CP_MTY), ("CACX7605101P8", "1", CP_TIJUANA)]


def test_api_errores_de_armado(client):
    headers = _empresa(client)
    cliente = _cliente(client, headers)
    sin_cliente = _ingreso(client, headers, None)
    response = _crear(client, headers, sin_cliente["id"])
    assert response.status_code == 400 and "no tiene cliente" in response.json()["detail"]

    sin_iva = _ingreso(client, headers, cliente["id"], tax_rate="0")
    response = _crear(client, headers, sin_iva["id"])
    assert response.status_code == 422 and "exenta" in response.json()["detail"]
    assert _crear(client, headers, sin_iva["id"], tratamiento_iva="exento").status_code == 201

    ingreso = _ingreso(client, headers, cliente["id"])
    mal = _crear(client, headers, ingreso["id"], conceptos=[{"descripcion": "a", "cantidad": "1", "valor_unitario": "900"}])
    assert mal.status_code == 422 and "no se ajustan montos" in mal.json()["detail"]
    bien = _crear(
        client,
        headers,
        ingreso["id"],
        conceptos=[
            {"descripcion": "Asesoría", "cantidad": "2", "valor_unitario": "400", "clave_prod_serv": "84111506"},
            {"descripcion": "Papelería", "cantidad": "1", "valor_unitario": "250", "descuento": "50", "clave_unidad": "h87"},
        ],
    )
    assert bien.status_code == 201, bien.text
    assert (bien.json()["subtotal"], bien.json()["descuento"], bien.json()["total"]) == ("1050.00", "50.00", "1160.00")
    assert bien.json()["conceptos"][1]["clave_unidad"] == "H87"

    cancelado = _ingreso(client, headers, cliente["id"])
    assert client.post(f"/api/income/{cancelado['id']}/cancel", headers=headers, json={"reason": "error"}).status_code == 200
    assert _crear(client, headers, cancelado["id"]).status_code == 409


def test_api_ventana_de_72_horas(client, monkeypatch):
    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    real = docs_service._ahora
    monkeypatch.setattr(docs_service, "_ahora", lambda: real() + dt.timedelta(hours=73))
    resultado = client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()
    assert [p["codigo"] for p in resultado["problemas"]] == ["401"]
    # Rearmar la vuelve a fechar.
    client.post(f"/api/fiscal-mx/documents/{doc['id']}/rebuild", headers=headers, json={})
    assert client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()["listo"] is True


def test_api_aislamiento_entre_empresas(client):
    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()

    otra = _empresa(client, email="otra@example.com")
    assert _crear(client, otra, ingreso["id"]).status_code == 404
    for metodo, ruta in (
        ("get", f"/api/fiscal-mx/documents/{doc['id']}"),
        ("get", f"/api/fiscal-mx/documents/{doc['id']}/xml"),
        ("post", f"/api/fiscal-mx/documents/{doc['id']}/validate"),
        ("post", f"/api/fiscal-mx/documents/{doc['id']}/rebuild"),
    ):
        kwargs = {"json": {}} if metodo == "post" else {}
        assert getattr(client, metodo)(ruta, headers=otra, **kwargs).status_code == 404, ruta
    assert client.get("/api/fiscal-mx/documents", headers=otra).json()["total"] == 0
    assert client.get("/api/fiscal-mx/documents", headers=headers).json()["total"] == 1


def test_api_sin_sesion_y_sin_permiso(client):
    assert client.get("/api/fiscal-mx/documents").status_code == 401
    assert client.post("/api/fiscal-mx/documents", json={}).status_code == 401


def test_xml_fiscal_guardado_es_inmutable(client, db):
    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    org_id = headers["X-Organization-ID"]
    fila = FiscalDocumentXml(
        organization_id=org_id, documento_id=doc["id"], tipo="SELLADO", contenido=b"<x/>", sha256="0" * 64, bytes=4
    )
    db.add(fila)
    db.flush()
    fila.contenido = b"<y/>"
    with pytest.raises(XmlInmutable):
        db.flush()
    db.rollback()


# ---------------------------------------------------------------- migración


def test_migracion_documentos_fiscales_es_el_unico_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    raiz = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(raiz / "alembic.ini")))
    assert script.get_heads() == ["20261125_02"]
    assert script.get_revision("20261125_02").down_revision == "20261125_01"


@pytest.mark.postgres
def test_postgres_impide_modificar_un_xml_fiscal(client, db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    db.add(
        FiscalDocumentXml(
            organization_id=headers["X-Organization-ID"], documento_id=doc["id"], tipo="SELLADO",
            contenido=b"<x/>", sha256="0" * 64, bytes=4,
        )
    )
    db.flush()
    with pytest.raises(DBAPIError, match="no se modifica ni se borra"):
        with db.begin_nested():
            db.execute(text("UPDATE documentos_fiscales_xml SET contenido = :c"), {"c": b"<y/>"})
