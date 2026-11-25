"""Solicitud de cancelación firmada por nosotros (sin red)."""

import base64
from datetime import datetime

import pytest
from lxml import etree
from satcfdi.create.cancela import cancelacion as satcfdi_cancelacion
from satcfdi.models import Signer

from cancelacion import (
    NS_DSIG,
    AlgoritmoNoSoportado,
    FolioCancelacion,
    armar_solicitud,
    c14n,
    verificar_solicitud,
)
from conftest import CONTRASENA_PRUEBA
from firmante import FirmanteAwsKms, FirmanteLocal, descifrar_llave_csd
from test_sellado import KmsSimulado

FECHA = datetime(2026, 1, 21, 13, 0, 39)
UUID_EJEMPLO_FD = "B7EBEDF0-0AD8-4644-A6BA-EF650698E166"
# Del ejemplo público "Cancelacion2_v40" de Formas Digitales
# (https://forsedi.facturacfdi.mx/developers/webservice/cancelacion/soap/metodos-cancelacion).
# Reenviado tal cual a su ambiente de pruebas el 2026-11-25 respondió 202 (ya cancelado):
# es una firma que el SAT de pruebas acepta.
DIGEST_EJEMPLO_FD = "xvzmo6rIOtDcN66fd/Dh9mL0IcA="
FIRMA_EJEMPLO_FD = (
    "B2AJZyVyUOtFHbq+jwjsi8ILPI+043QM2BQnZtMyZbjw+p/5CwsFPen6sGPbxBLI0FxwLQssdbt3it6SNM0pwZPzqq89QvGe36LaXnMtEIpiOGGj0rd+"
    "UzryhDuaixlFUbIwC54gn4HlBj2gXGSHIrCPe33A7C2h6Hu+XC1qn4/zG+zCHUZO0dDshyaBIbP/71aB+J4MIQJ143dlW9WVDk9u0R/VHaVBREUo99B"
    "rb80tjkR+WwWbURduNDAkbU/6TsmztG4STGe+QKicmb7NI7dIGZUxu6gtH3VnQEXCGXBMkagTXXm8jFqTptEiKC9zNiYkGlxj1eQmLabLdjvNAg=="
)


def _valor(xml: bytes, nombre: str) -> str:
    return etree.fromstring(xml).findtext(f".//{{{NS_DSIG}}}{nombre}")


def _corromper(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    sv = raiz.find(f".//{{{NS_DSIG}}}SignatureValue")
    b = bytearray(base64.b64decode(sv.text))
    b[10] ^= 0xFF
    sv.text = base64.b64encode(bytes(b)).decode()
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


@pytest.fixture(scope="module")
def kms_firmante(cer_path, key_path, firmante_local):
    llave = descifrar_llave_csd(key_path.read_bytes(), CONTRASENA_PRUEBA)
    sim = KmsSimulado("arn:aws:kms:us-east-1:000000000000:key/simulada", llave)
    return FirmanteAwsKms(sim.key_id, firmante_local.certificado(), cliente=sim)


def test_sha1_reproduce_byte_a_byte_el_ejemplo_publico_de_formas_digitales(firmante_local):
    sol = armar_solicitud(
        firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha1",
        folio_sustitucion_vacio=True,
    )
    assert _valor(sol, "DigestValue") == DIGEST_EJEMPLO_FD
    assert _valor(sol, "SignatureValue") == FIRMA_EJEMPLO_FD


def test_sin_folio_sustitucion_vacio_el_resumen_cambia(firmante_local):
    """Por eso Formas Digitales respondía 302: rearma el documento con FolioSustitucion=""."""
    sol = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha1")
    assert _valor(sol, "DigestValue") != DIGEST_EJEMPLO_FD
    assert verificar_solicitud(sol)


def test_sha1_es_identica_a_la_de_satcfdi(cer_path, key_path, firmante_local):
    signer = Signer.load(cer_path.read_bytes(), key_path.read_bytes(), CONTRASENA_PRUEBA)
    ref = satcfdi_cancelacion.Cancelacion(
        emisor=signer, folios=satcfdi_cancelacion.Folio(uuid=UUID_EJEMPLO_FD, motivo="02"), fecha=FECHA
    ).xml_bytes()
    nuestra = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha1")
    for nombre in ("DigestValue", "SignatureValue", "X509Certificate", "X509SerialNumber", "X509IssuerName"):
        assert _valor(nuestra, nombre) == _valor(ref, nombre), nombre


@pytest.mark.parametrize("algoritmo", ["sha1", "sha256"])
def test_verifica_y_detecta_alteraciones(firmante_local, algoritmo):
    sol = armar_solicitud(
        firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, algoritmo
    )
    assert verificar_solicitud(sol)
    assert not verificar_solicitud(_corromper(sol))
    assert not verificar_solicitud(sol.replace(b'Motivo="02"', b'Motivo="03"'))


def test_sha256_declara_los_algoritmos_correctos(firmante_local):
    sol = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha256")
    raiz = etree.fromstring(sol)
    ns = {"ds": NS_DSIG}
    assert raiz.find(".//ds:SignatureMethod", ns).get("Algorithm").endswith("#rsa-sha256")
    assert raiz.find(".//ds:DigestMethod", ns).get("Algorithm").endswith("#sha256")


def test_kms_firma_la_cancelacion_sha256_igual_que_la_llave_local(firmante_local, kms_firmante):
    args = ("EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha256")
    assert armar_solicitud(kms_firmante, *args) == armar_solicitud(firmante_local, *args)


def test_kms_no_puede_firmar_sha1(kms_firmante):
    with pytest.raises(AlgoritmoNoSoportado):
        armar_solicitud(kms_firmante, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA, "sha1")


def test_motivo_01_exige_sustituto_y_lo_firma():
    with pytest.raises(ValueError):
        FolioCancelacion(UUID_EJEMPLO_FD, "01")
    with pytest.raises(ValueError):
        FolioCancelacion(UUID_EJEMPLO_FD, "02", folio_sustitucion=UUID_EJEMPLO_FD)
    with pytest.raises(ValueError):
        FolioCancelacion(UUID_EJEMPLO_FD, "05")


def test_c14n_de_un_subarbol_no_inventa_xmlns_vacio():
    """Regresión de lxml 6.1.3 / libxml2 2.14.6: los nietos salían con xmlns=""."""
    raiz = etree.fromstring(b'<R xmlns="urn:a"><S xmlns="urn:d"><I><Ref URI=""><T/></Ref></I></S></R>')
    i = raiz.find(".//{urn:d}I")
    assert c14n(i) == b'<I xmlns="urn:d"><Ref URI=""><T></T></Ref></I>'


def test_la_solicitud_no_lleva_material_de_llave(firmante_local, key_path):
    sol = armar_solicitud(firmante_local, "EKU9003173C9", [FolioCancelacion(UUID_EJEMPLO_FD, "02")], FECHA)
    assert b"PRIVATE" not in sol
    assert base64.b64encode(key_path.read_bytes())[:40] not in sol
    assert isinstance(firmante_local, FirmanteLocal)
