"""Catálogos del SAT versionados: integridad de los datos y consultas del cargador."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest

from app.services.cfdi.catalogos import (
    CatalogoNoEncontrado,
    ClaveNoValida,
    EstadoClave,
    catalogo,
    catalogos_disponibles,
    errores_sat,
    manifiesto,
    tasa_o_cuota_valida,
    uso_cfdi_permitido,
)
from app.services.cfdi.catalogos.cargador import DATA

HOY = dt.date(2026, 11, 25)

REQUERIDOS = [
    # CFDI 4.0
    "c_FormaPago", "c_MetodoPago", "c_UsoCFDI", "c_RegimenFiscal", "c_ClaveProdServ", "c_ClaveUnidad",
    "c_ObjetoImp", "c_Impuesto", "c_TasaOCuota", "c_TipoDeComprobante", "c_Exportacion", "c_Periodicidad",
    "c_Meses", "c_TipoRelacion", "c_Moneda", "c_CodigoPostal", "c_Pais", "c_TipoFactor",
    # Nómina 1.2
    "c_TipoNomina", "c_TipoPercepcion", "c_TipoDeduccion", "c_TipoOtroPago", "c_PeriodicidadPago",
    "c_TipoContrato", "c_TipoRegimen", "c_RiesgoPuesto", "c_Banco",
    # Pagos 2.0 y cancelación
    "c_TipoCadenaPago", "c_MotivoCancelacion",
]


def test_estan_todos_los_catalogos_requeridos():
    disponibles = set(catalogos_disponibles())
    assert set(REQUERIDOS) <= disponibles


@pytest.mark.parametrize("nombre", REQUERIDOS)
def test_metadatos_de_origen_completos(nombre):
    cat = catalogo(nombre)
    assert len(cat) > 0
    assert cat.origen["url"].startswith(("http://", "https://"))
    assert len(cat.origen["sha256"]) == 64
    dt.date.fromisoformat(cat.origen["fecha_descarga"])
    assert "vigencia_inicio" in cat.sat


def test_manifiesto_coincide_con_los_archivos():
    m = manifiesto()
    for entrada in [*m["catalogos"].values(), *m["matrices"].values()]:
        crudo = (DATA / entrada["archivo"]).read_bytes()
        assert hashlib.sha256(crudo).hexdigest() == entrada["sha256"], entrada["archivo"]


def test_datos_sin_flotantes():
    # Todo valor es texto o null: los montos y tasas se leen con Decimal.
    doc = json.loads((DATA / "cfdi40" / "c_TasaOCuota.json").read_text(encoding="utf-8"))
    for fila in doc["registros"]:
        assert all(v is None or isinstance(v, str) for v in fila)


def test_claves_conservan_ceros_a_la_izquierda():
    assert catalogo("c_FormaPago").obtener("01").descripcion == "Efectivo"
    assert catalogo("c_FormaPago").obtener("1") is None
    assert catalogo("c_Impuesto").obtener("002").descripcion == "IVA"
    assert catalogo("c_ClaveProdServ").obtener("01010101").descripcion == "No existe en el catálogo"
    assert catalogo("c_TipoRelacion").obtener("04").descripcion == "Sustitución de los CFDI previos"


def test_valores_conocidos():
    assert set(r.clave for r in catalogo("c_MetodoPago")) == {"PUE", "PPD"}
    assert {"I", "E", "T", "N", "P"} <= {r.clave for r in catalogo("c_TipoDeComprobante")}
    assert catalogo("c_RegimenFiscal").obtener("626").descripcion == "Régimen Simplificado de Confianza"
    assert catalogo("c_UsoCFDI").obtener("G03") is not None
    assert catalogo("c_Moneda").obtener("MXN") is not None
    assert catalogo("c_ClaveUnidad").obtener("H87") is not None
    assert catalogo("c_ClaveUnidad").obtener("E48") is not None
    assert catalogo("c_TipoNomina").obtener("O").descripcion == "Nómina ordinaria"
    assert catalogo("c_TipoPercepcion").obtener("001") is not None
    motivos = {r.clave: r.descripcion for r in catalogo("c_MotivoCancelacion")}
    assert motivos["01"] == "Comprobante emitido con errores con relación"
    assert set(motivos) == {"01", "02", "03", "04"}


def test_codigo_postal_trae_huso_horario():
    cp = catalogo("c_CodigoPostal").obtener("20000")
    assert cp["c_estado"] == "AGU"
    assert cp["descripcion_del_huso_horario"] == "Tiempo del Centro"
    assert len(catalogo("c_CodigoPostal")) > 90_000


def test_llave_compuesta_de_municipio():
    mun = catalogo("c_Municipio")
    assert mun.llave == ("c_estado", "clave")
    assert mun.obtener(("AGU", "001")).descripcion == "Aguascalientes"
    assert mun.obtener(("BCN", "001")).descripcion == "Ensenada"


def test_vigencia_por_fecha():
    cat = catalogo("c_ObjetoImp")
    # "06" entra en vigor después que "01": antes de su inicio no vale.
    seis = cat.obtener("06")
    assert seis.vigencia_inicio > dt.date(2022, 1, 1)
    antes = seis.vigencia_inicio - dt.timedelta(days=1)
    assert cat.estado("06", antes) is EstadoClave.NO_VIGENTE
    assert cat.estado("06", seis.vigencia_inicio) is EstadoClave.VIGENTE
    assert cat.estado("06", dt.datetime.combine(HOY, dt.time(12))) is EstadoClave.VIGENTE
    assert cat.estado("99", HOY) is EstadoClave.INEXISTENTE
    assert "06" not in {r.clave for r in cat.vigentes(antes)}


def test_vigencia_con_fecha_fin_inclusive():
    # Busca un registro con fin de vigencia en cualquier catálogo chico para probar el borde.
    for nombre in ["c_TipoDeduccion", "c_TipoPercepcion", "c_TipoOtroPago", "c_ClaveUnidad", "c_Pais", "c_Moneda"]:
        con_fin = [r for r in catalogo(nombre) if r.vigencia_fin]
        if con_fin:
            r = con_fin[0]
            assert r.vigente_en(r.vigencia_fin)
            assert not r.vigente_en(r.vigencia_fin + dt.timedelta(days=1))
            return
    pytest.skip("ningún catálogo chico tiene fin de vigencia")


def test_validar_lanza_error_en_espanol():
    cat = catalogo("c_FormaPago")
    assert cat.validar("03", HOY).descripcion == "Transferencia electrónica de fondos"
    with pytest.raises(ClaveNoValida, match="no existe en el catálogo c_FormaPago"):
        cat.validar("XX", HOY)
    with pytest.raises(ClaveNoValida, match="no está vigente"):
        catalogo("c_ObjetoImp").validar("06", dt.date(2022, 1, 1))


def test_catalogo_inexistente():
    with pytest.raises(CatalogoNoEncontrado):
        catalogo("c_NoExiste")


def test_tasa_o_cuota():
    assert tasa_o_cuota_valida("002", "Tasa", "0.160000", traslado=True, fecha=HOY)
    assert tasa_o_cuota_valida("002", "Tasa", Decimal("0.08"), traslado=True, fecha=HOY)  # franja fronteriza
    assert tasa_o_cuota_valida("002", "Tasa", "0.106667", traslado=False, fecha=HOY)  # retención en rango
    assert not tasa_o_cuota_valida("002", "Tasa", "0.15", traslado=True, fecha=HOY)
    assert not tasa_o_cuota_valida("002", "Tasa", "0.20", traslado=False, fecha=HOY)
    assert tasa_o_cuota_valida("001", "Tasa", "0.10", traslado=False, fecha=HOY)
    assert not tasa_o_cuota_valida("001", "Tasa", "0.10", traslado=True, fecha=HOY)
    assert not tasa_o_cuota_valida("999", "Tasa", "0.16", traslado=True, fecha=HOY)
    assert not tasa_o_cuota_valida("002", "Tasa", "no-numero", traslado=True, fecha=HOY)


def test_uso_cfdi_por_regimen_y_persona():
    assert uso_cfdi_permitido("G03", "601", persona_moral=True, fecha=HOY)
    assert uso_cfdi_permitido("G03", "626", persona_moral=False, fecha=HOY)
    assert not uso_cfdi_permitido("D01", "601", persona_moral=True, fecha=HOY)  # deducción personal
    assert uso_cfdi_permitido("CN01", "605", persona_moral=False, fecha=HOY)
    assert not uso_cfdi_permitido("CN01", "612", persona_moral=False, fecha=HOY)
    assert not uso_cfdi_permitido("ZZZ", "601", persona_moral=True, fecha=HOY)


def test_matrices_de_errores():
    [error] = errores_sat("CFDI40104")
    assert error.matriz == "cfdi40"
    assert "c_FormaPago" in error.descripcion
    assert errores_sat("NOM1")[0].matriz == "nomina12"
    assert errores_sat("CRP20101")[0].matriz == "pagos20"
    assert errores_sat("NO-EXISTE") == ()
