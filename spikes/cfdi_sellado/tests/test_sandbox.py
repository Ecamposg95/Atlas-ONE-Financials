"""Pruebas contra los ambientes de PRUEBAS de los proveedores. Llaman a la red.

Sólo corren con ``SPIKE_SANDBOX=1`` y las credenciales de prueba que cada
proveedor publica en su documentación (ver README):

    SPIKE_SANDBOX=1 FD_USUARIO=… FD_CONTRASENA=… SF_USUARIO=… SF_CONTRASENA=… \\
        .venv/bin/python -m pytest tests/test_sandbox.py -v -s

La prueba completa de Formas Digitales tarda varios minutos: el SAT de pruebas
tarda en conocer el UUID recién timbrado y hasta entonces la cancelación
responde 205 ("Folio Fiscal No existe").
"""

import base64
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from lxml import etree
from satcfdi.create.cfd import cfdi40

from cancelacion import NS_DSIG, FolioCancelacion, armar_solicitud
from pac_formas_digitales import FormasDigitales
from pac_solucion_factible import SolucionFactible
from proveedor_timbrado import Estado
from sellado import comprobante_de_prueba, sellar_con_satcfdi

pytestmark = pytest.mark.skipif(os.environ.get("SPIKE_SANDBOX") != "1", reason="sólo con SPIKE_SANDBOX=1 (llama a la red)")

EMISOR = "EKU9003173C9"
# Receptor de los ejemplos públicos de Formas Digitales; URE180429TM6/86991 da CFDI40147.
RECEPTOR = cfdi40.Receptor(
    rfc="EWE1709045U0", nombre="ESCUELA WILSON ESQUIVEL", domicilio_fiscal_receptor="44960",
    regimen_fiscal_receptor="601", uso_cfdi="G03",
)
ESPERA_SAT_MIN = float(os.environ.get("SPIKE_ESPERA_SAT_MIN", "15"))


def _cred(var: str) -> str:
    valor = os.environ.get(var)
    if not valor:
        pytest.skip(f"falta {var}")
    return valor


def _ahora() -> datetime:
    return datetime.now(ZoneInfo("America/Mexico_City")).replace(tzinfo=None, microsecond=0)


def _sellado(firmante, sufijo: str) -> bytes:
    c = comprobante_de_prueba(_ahora() - timedelta(minutes=5))
    c["Folio"] = f"{int(time.time())}{sufijo}"
    c["Receptor"] = RECEPTOR
    return sellar_con_satcfdi(c, firmante)


def _corromper(sol: bytes) -> bytes:
    raiz = etree.fromstring(sol)
    sv = raiz.find(f".//{{{NS_DSIG}}}SignatureValue")
    b = bytearray(base64.b64decode(sv.text))
    b[10] ^= 0xFF
    sv.text = base64.b64encode(bytes(b)).decode()
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


@pytest.fixture(scope="module")
def fd():
    return FormasDigitales(_cred("FD_USUARIO"), _cred("FD_CONTRASENA"))


@pytest.fixture(scope="module")
def sf():
    return SolucionFactible(_cred("SF_USUARIO"), _cred("SF_CONTRASENA"))


def test_formas_digitales_timbra_y_cancela_con_sha1_y_sha256(fd, firmante_local):
    timbrados = {}
    for alg in ("sha1", "sha256"):
        r = fd.timbrar(_sellado(firmante_local, alg[-1]), alg)
        print(f"\nFD timbrar {alg}: {r.estado.value} {r.uuid} {r.rfc_prov_certif} {r.segundos}s")
        assert r.estado is Estado.TIMBRADO, (r.codigo_proveedor, r.mensaje)
        timbrados[alg] = r

    # Control negativo: firma alterada -> 302 aunque el UUID aún no exista.
    sol = armar_solicitud(firmante_local, EMISOR, [FolioCancelacion(timbrados["sha256"].uuid, "02")], _ahora(),
                          "sha256", folio_sustitucion_vacio=True)
    malo = fd.cancelar(_corromper(sol))
    print(f"FD firma alterada: {malo.codigo_proveedor} {malo.mensaje}")
    assert malo.codigo_proveedor == "302"

    # Esperar a que el SAT de pruebas conozca los UUID.
    limite = time.monotonic() + ESPERA_SAT_MIN * 60
    for alg, r in timbrados.items():
        while True:
            st = fd.consultar_estatus(r.uuid, EMISOR, RECEPTOR["Rfc"], "3480.00")
            if st.estado == "Vigente" or time.monotonic() > limite:
                break
            time.sleep(30)
        print(f"FD estatus {alg}: {st}")
        assert st.estado == "Vigente"
        sol = armar_solicitud(firmante_local, EMISOR, [FolioCancelacion(r.uuid, "02")], _ahora(), alg,
                              folio_sustitucion_vacio=True)
        rc = fd.cancelar(sol)
        print(f"FD cancelar {alg}: {rc.codigo_proveedor} {rc.estatus_uuid} {rc.mensaje} {rc.segundos}s")
        assert rc.aceptada and rc.estatus_uuid[r.uuid] == "201"


def test_solucion_factible_timbra_y_solo_acepta_sha1(sf, firmante_local):
    resultados = {}
    for alg in ("sha1", "sha256"):
        r = sf.timbrar(_sellado(firmante_local, "7" if alg == "sha1" else "8"), alg)
        print(f"\nSF timbrar: {r.estado.value} {r.uuid} {r.rfc_prov_certif} {r.segundos}s")
        assert r.estado is Estado.TIMBRADO, (r.codigo_proveedor, r.mensaje)
        sol = armar_solicitud(firmante_local, EMISOR, [FolioCancelacion(r.uuid, "02")], _ahora(), alg)
        resultados[alg] = rc = sf.cancelar(sol)
        print(f"SF cancelar {alg}: {rc.codigo_proveedor} {rc.estatus_uuid} {rc.mensaje} {rc.segundos}s")
    assert resultados["sha1"].aceptada
    # Su verificador rechaza rsa-sha256 antes de llegar al SAT: "cannot find validation key".
    assert resultados["sha256"].codigo_proveedor == "1801"
