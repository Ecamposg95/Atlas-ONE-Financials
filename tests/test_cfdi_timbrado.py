"""Sellado, timbrado y cancelación del documento fiscal (ADR-017 y ADR-018).

Sin red y sin llaves en el repositorio: el CSD es **sintético** (RSA 2048
generado al correr, con el número de serie y el RFC como los pone el SAT) y
el proveedor es ``ProveedorSimulado``. Si el CSD de prueba del SAT está en
``~/.cache/atlas-financials-spike-csd`` (lo baja el spike), dos pruebas más
lo usan; si no, se saltan.

Lo que se vigila: guardar antes de enviar, nunca timbrar dos veces (timeout y
reintento), rechazos en español con su código, cancelación con motivo y
sustitución, el estado final por consulta, la bitácora de cada firma, el
candado de producción y que nada toque el libro.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import os
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree

from app.config import get_settings
from app.domains.fiscal_mx import router as fiscal_router
from app.domains.fiscal_mx import timbrado as timbrado_service
from app.main import app as fastapi_app
from app.models.fiscal_document import (
    BitacoraInmutable,
    FiscalDocument,
    FiscalDocumentXml,
    FiscalSignatureLog,
)
from app.services.cfdi import configuracion as cfdi_config
from app.services.cfdi import xml_sat
from app.services.cfdi.cancelacion import (
    NS_DSIG,
    AlgoritmoNoSoportado,
    ErrorCancelacion,
    FolioCancelacion,
    armar_solicitud,
    c14n,
    verificar_solicitud,
)
from app.services.cfdi.firmante import (
    ErrorFirmante,
    Firmante,
    FirmanteKms,
    FirmanteLocalPruebas,
    FirmanteNoDisponible,
    numero_certificado,
    rfc_del_certificado,
)
from app.services.cfdi.pac_formas_digitales import URL_TIMBRADO_PRUEBAS, FormasDigitalesPruebas
from app.services.cfdi.pac_simulado import ProveedorSimulado
from app.services.cfdi.proveedor_timbrado import (
    Categoria,
    Estado,
    EstadoCancelacion,
    ProveedorTimbrado,
    SinRespuesta,
    normalizar_error,
)
from app.services.cfdi.sellado import ErrorSellado, revisar_certificado, sellar, verificar_sello
from tests.helpers import auth_headers
from tests.test_cfdi_documento_fiscal import _cliente, _crear, _empresa, _ingreso, _libro

NO_CERTIFICADO = "30001000000500003416"
RFC_EMISOR = "EKU9003173C9"
CONTRASENA = "12345678a"
FIXTURES = Path(__file__).parent / "fixtures" / "cfdi_pac"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"


# ---------------------------------------------------------------- CSD sintético


def _csd(rfc: str = RFC_EMISOR, *, desde=dt.datetime(2025, 1, 1), hasta=dt.datetime(2030, 1, 1)):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    emisor = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "AC UAT"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SERVICIO DE ADMINISTRACION TRIBUTARIA"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        ]
    )
    titular = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "ESCUELA KEMPER URGATE SA DE CV"),
            x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, f"{rfc} / VADA800927DJ3"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(titular)
        .issuer_name(emisor)
        .public_key(llave.public_key())
        .serial_number(int.from_bytes(NO_CERTIFICADO.encode("ascii"), "big"))
        .not_valid_before(desde)
        .not_valid_after(hasta)
        .sign(llave, hashes.SHA256())
    )
    return cert, llave


@pytest.fixture(scope="module")
def csd_archivos(tmp_path_factory):
    """``.cer`` en DER y ``.key`` en PKCS#8 cifrado en DER, como los entrega el SAT."""
    cert, llave = _csd()
    carpeta = tmp_path_factory.mktemp("csd")
    cer = carpeta / "prueba.cer"
    key = carpeta / "prueba.key"
    cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    key.write_bytes(
        llave.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(CONTRASENA.encode()),
        )
    )
    return cer, key


@pytest.fixture(scope="module")
def firmante(csd_archivos) -> FirmanteLocalPruebas:
    cer, key = csd_archivos
    return FirmanteLocalPruebas.desde_archivos(cer, key, CONTRASENA, entorno="test")


@pytest.fixture()
def pac() -> ProveedorSimulado:
    return ProveedorSimulado()


@pytest.fixture()
def timbrado(client, firmante, pac):
    """Habilita el timbrado en la API con el firmante de prueba y el proveedor simulado."""
    servicios = cfdi_config.ServiciosTimbrado(proveedor=pac, firmante_para=lambda _org, _rfc: firmante)
    fastapi_app.dependency_overrides[fiscal_router.servicios_timbrado] = lambda: servicios
    fastapi_app.dependency_overrides[fiscal_router.servicios_timbrado_opcional] = lambda: servicios
    yield servicios
    fastapi_app.dependency_overrides.pop(fiscal_router.servicios_timbrado, None)
    fastapi_app.dependency_overrides.pop(fiscal_router.servicios_timbrado_opcional, None)


def _lista(client, headers, cliente_id=None) -> dict:
    """Factura validada (LISTO_PARA_TIMBRAR) de un ingreso nuevo."""
    cliente_id = cliente_id or _cliente(client, headers)["id"]
    ingreso = _ingreso(client, headers, cliente_id)
    doc = _crear(client, headers, ingreso["id"]).json()
    validacion = client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()
    assert validacion["listo"], validacion
    doc["ingreso"] = ingreso
    return doc


def _stamp(client, headers, doc_id):
    return client.post(f"/api/fiscal-mx/documents/{doc_id}/stamp", headers=headers)


def _cancel(client, headers, doc_id, motivo="02", folio=None):
    payload = {"motivo": motivo} | ({"folio_sustitucion": folio} if folio else {})
    return client.post(f"/api/fiscal-mx/documents/{doc_id}/cancel", headers=headers, json=payload)


def _status(client, headers, doc_id):
    response = client.get(f"/api/fiscal-mx/documents/{doc_id}/status", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _xmls(db, doc_id, tipo=None):
    q = db.query(FiscalDocumentXml).filter(FiscalDocumentXml.documento_id == doc_id)
    if tipo:
        q = q.filter(FiscalDocumentXml.tipo == tipo)
    return q.order_by(FiscalDocumentXml.tipo, FiscalDocumentXml.secuencia).all()


def _bitacora(db, doc_id):
    return (
        db.query(FiscalSignatureLog)
        .filter(FiscalSignatureLog.documento_id == doc_id)
        .order_by(FiscalSignatureLog.created_at)
        .all()
    )


def _hasta_timbrado(client, headers):
    doc = _lista(client, headers)
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 200, response.text
    return response.json() | {"ingreso": doc["ingreso"]}


# ---------------------------------------------------------------- firmante y sellado (sin API)


def test_firmante_local_lee_el_formato_del_sat(firmante):
    assert isinstance(firmante, Firmante)
    assert numero_certificado(firmante.certificado()) == NO_CERTIFICADO
    assert rfc_del_certificado(firmante.certificado()) == RFC_EMISOR


def test_firmante_local_se_niega_en_produccion(csd_archivos):
    cer, key = csd_archivos
    with pytest.raises(FirmanteNoDisponible, match="sólo para pruebas"):
        FirmanteLocalPruebas.desde_archivos(cer, key, CONTRASENA, entorno="production")


def test_firmante_local_con_contrasena_o_llave_equivocada(csd_archivos):
    cer, key = csd_archivos
    with pytest.raises(ErrorFirmante, match="contraseña"):
        FirmanteLocalPruebas.desde_archivos(cer, key, "otra", entorno="test")
    otro_cert, _ = _csd()
    _, otra_llave = _csd()
    with pytest.raises(ErrorFirmante, match="no corresponde"):
        FirmanteLocalPruebas(otro_cert, otra_llave, entorno="test")


def test_firmante_kms_es_un_hueco_con_mensaje_claro():
    with pytest.raises(FirmanteNoDisponible, match="servicio de llaves"):
        FirmanteKms()


def test_sellar_pone_certificado_y_sello_que_verifica(firmante):
    from tests.test_cfdi_documento_fiscal import _comprobante, _op
    from app.services.cfdi.armado import armar
    from app.services.cfdi.comprobante import xml_sin_sellar

    sellado = sellar(xml_sin_sellar(_comprobante(armar(_op("1160.00")))), firmante)
    raiz = etree.fromstring(sellado.xml)
    assert raiz.get("NoCertificado") == NO_CERTIFICADO and raiz.get("Certificado") and raiz.get("Sello")
    assert xml_sat.errores_xsd(sellado.xml) == []
    assert verificar_sello(sellado.xml)
    assert sellado.cadena_original.startswith(f"||4.0|A|1|2026-11-25T10:00:00|03|{NO_CERTIFICADO}|")
    assert sellado.sha256_cadena == hashlib.sha256(sellado.cadena_original.encode()).hexdigest()
    # Cualquier cambio después de sellar rompe el sello.
    assert not verificar_sello(sellado.xml.replace(b'Total="1160.00"', b'Total="1161.00"'))


def test_el_certificado_debe_ser_del_emisor_y_estar_vigente(firmante):
    cuando = dt.datetime(2026, 11, 25, tzinfo=dt.timezone.utc)
    revisar_certificado(firmante, RFC_EMISOR, cuando)
    with pytest.raises(ErrorSellado, match="RFC"):
        revisar_certificado(firmante, "XAXX010101000", cuando)
    with pytest.raises(ErrorSellado, match="vigente"):
        revisar_certificado(firmante, RFC_EMISOR, dt.datetime(2031, 1, 1, tzinfo=dt.timezone.utc))


def test_una_firma_que_no_corresponde_no_se_usa(firmante):
    from tests.test_cfdi_documento_fiscal import _comprobante, _op
    from app.services.cfdi.armado import armar
    from app.services.cfdi.comprobante import xml_sin_sellar

    class Tramposo:
        tipo = "tramposo"

        def firmar(self, datos):
            return firmante.firmar(datos + b"x")

        def certificado(self):
            return firmante.certificado()

    with pytest.raises(ErrorSellado, match="no corresponde"):
        sellar(xml_sin_sellar(_comprobante(armar(_op("1160.00")))), Tramposo())


# ---------------------------------------------------------------- solicitud de cancelación (sin API)


def test_solicitud_de_cancelacion_sha256_y_sha1_verifican(firmante):
    fecha = dt.datetime(2026, 11, 25, 12, 0, 0)
    folio = FolioCancelacion("B7EBEDF0-0AD8-4644-A6BA-EF650698E166", "02")
    for algoritmo in ("sha256", "sha1"):
        sol = armar_solicitud(firmante, RFC_EMISOR, [folio], fecha, algoritmo, folio_sustitucion_vacio=True)
        assert verificar_solicitud(sol)
        assert not verificar_solicitud(sol.replace(b'Motivo="02"', b'Motivo="03"'))
        assert b"PRIVATE" not in sol
    metodo = etree.fromstring(armar_solicitud(firmante, RFC_EMISOR, [folio], fecha)).find(f".//{{{NS_DSIG}}}SignatureMethod")
    assert metodo.get("Algorithm").endswith("rsa-sha256")


def test_firmante_sin_sha1_no_firma_la_cancelacion_sha1(firmante):
    class SoloSha256:
        tipo = "kms"

        def firmar(self, datos):
            return firmante.firmar(datos)

        def certificado(self):
            return firmante.certificado()

    with pytest.raises(AlgoritmoNoSoportado):
        armar_solicitud(SoloSha256(), RFC_EMISOR, [FolioCancelacion("A" * 8 + "-0000-0000-0000-" + "0" * 12, "02")], dt.datetime(2026, 1, 1), "sha1")


def test_motivos_de_cancelacion():
    uuid = "B7EBEDF0-0AD8-4644-A6BA-EF650698E166"
    with pytest.raises(ErrorCancelacion, match="01"):
        FolioCancelacion(uuid, "01")
    with pytest.raises(ErrorCancelacion):
        FolioCancelacion(uuid, "02", folio_sustitucion=uuid)
    with pytest.raises(ErrorCancelacion):
        FolioCancelacion(uuid, "05")
    assert FolioCancelacion(uuid, "01", folio_sustitucion="C" * 8 + "-0000-0000-0000-" + "0" * 12)


def test_c14n_de_un_subarbol_no_inventa_xmlns_vacio():
    raiz = etree.fromstring(b'<R xmlns="urn:a"><S xmlns="urn:d"><I><Ref URI=""><T/></Ref></I></S></R>')
    assert c14n(raiz.find(".//{urn:d}I")) == b'<I xmlns="urn:d"><Ref URI=""><T></T></Ref></I>'


# ---------------------------------------------------------------- API: camino feliz


def test_timbrar_sella_guarda_y_timbra_sin_tocar_el_libro(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    libro_antes = _libro(client, headers)

    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 200, response.text
    timbrada = response.json()
    assert timbrada["estado"] == "TIMBRADO" and timbrada["validez_fiscal"] is True
    assert (timbrada["proveedor_timbrado"], timbrada["rfc_prov_certif"], timbrada["no_certificado"]) == (
        "simulado",
        "AAA010101AAA",
        NO_CERTIFICADO,
    )
    assert timbrada["uuid_fiscal"] and timbrada["fecha_timbrado"]

    # Se guardaron el sellado y el timbrado; el timbrado lleva el mismo sello y el UUID.
    sellado, timbre = _xmls(db, doc["id"], "SELLADO"), _xmls(db, doc["id"], "TIMBRADO")
    assert [x.secuencia for x in sellado] == [1] and len(timbre) == 1
    assert verificar_sello(bytes(sellado[0].contenido))
    descarga = client.get(f"/api/fiscal-mx/documents/{doc['id']}/stamped-xml", headers=headers)
    assert descarga.status_code == 200 and descarga.content == bytes(timbre[0].contenido)
    assert timbrada["uuid_fiscal"] in descarga.headers["content-disposition"]
    raiz = etree.fromstring(descarga.content)
    tfd = raiz.find(f".//{{{NS_TFD}}}TimbreFiscalDigital")
    assert tfd.get("UUID") == timbrada["uuid_fiscal"]
    assert raiz.get("Sello") == etree.fromstring(bytes(sellado[0].contenido)).get("Sello") == tfd.get("SelloCFD")

    # Bitácora: la firma con usuario, certificado y huella de la cadena original; nunca la llave.
    eventos = _bitacora(db, doc["id"])
    sello = next(e for e in eventos if e.evento == "SELLO")
    cadena = xml_sat.cadena_original(bytes(sellado[0].contenido))
    assert sello.sha256 == hashlib.sha256(cadena.encode()).hexdigest()
    assert (sello.no_certificado, sello.firmante) == (NO_CERTIFICADO, "local_pruebas") and sello.user_id
    assert any(e.evento == "TIMBRADO" and e.uuid_fiscal == timbrada["uuid_fiscal"] for e in eventos)

    # Timbrar otra vez no hace nada: mismo UUID, un solo envío.
    otra = _stamp(client, headers, doc["id"])
    assert otra.status_code == 200 and otra.json()["uuid_fiscal"] == timbrada["uuid_fiscal"]
    assert pac.envios == 1

    # Ni el libro ni la operación cambian; la factura ya no se rearma.
    assert _libro(client, headers) == libro_antes
    assert client.get(f"/api/income/{doc['ingreso']['id']}", headers=headers).json()["amount"] == "1160.00"
    assert client.post(f"/api/fiscal-mx/documents/{doc['id']}/rebuild", headers=headers, json={}).status_code == 409

    estatus = _status(client, headers, doc["id"])
    assert (estatus["estatus_sat"], estatus["timbrado_disponible"]) == ("Vigente", True)

    # La representación impresa sale del XML timbrado.
    pdf = client.get(f"/api/fiscal-mx/documents/{doc['id']}/pdf", headers=headers)
    assert pdf.status_code == 200 and "x-validez-fiscal" not in pdf.headers


def test_sin_validar_no_se_timbra(client, timbrado):
    headers = _empresa(client)
    ingreso = _ingreso(client, headers, _cliente(client, headers)["id"])
    doc = _crear(client, headers, ingreso["id"]).json()
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 409 and "Valida" in response.json()["detail"]


def test_validacion_vencida_se_revisa_antes_de_sellar(client, db, timbrado, monkeypatch):
    from app.domains.fiscal_mx import documentos as docs_service

    headers = _empresa(client)
    doc = _lista(client, headers)
    real = docs_service._ahora
    monkeypatch.setattr(docs_service, "_ahora", lambda: real() + dt.timedelta(hours=73))
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 422 and "72 horas" in response.json()["detail"]
    assert _xmls(db, doc["id"]) == []  # no se selló nada


def test_certificado_de_otro_rfc_no_sella(client, db, pac):
    cert, llave = _csd(rfc="URE180429TM6")
    ajeno = FirmanteLocalPruebas(cert, llave, entorno="test")
    servicios = cfdi_config.ServiciosTimbrado(proveedor=pac, firmante_para=lambda _o, _r: ajeno)
    fastapi_app.dependency_overrides[fiscal_router.servicios_timbrado] = lambda: servicios
    try:
        headers = _empresa(client)
        doc = _lista(client, headers)
        response = _stamp(client, headers, doc["id"])
    finally:
        fastapi_app.dependency_overrides.pop(fiscal_router.servicios_timbrado, None)
    assert response.status_code == 409 and "URE180429TM6" in response.json()["detail"]
    assert _xmls(db, doc["id"]) == [] and pac.envios == 0


# ---------------------------------------------------------------- API: rechazos del proveedor


def test_rechazo_por_datos_regresa_a_borrador_y_se_vuelve_a_sellar(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.rechazar_con = ("CFDI40147", "DomicilioFiscalReceptor no está en la lista de RFC inscritos")
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 422
    detalle = response.json()["detail"]
    assert "CFDI40147" in detalle and "datos fiscales del cliente" in detalle

    leido = client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()
    assert leido["estado"] == "BORRADOR" and leido["uuid_fiscal"] is None
    assert (leido["ultimo_error"]["categoria"], leido["ultimo_error"]["codigo_sat"]) == ("DATOS_RECEPTOR", "CFDI40147")
    # El sellado rechazado ya no es lo vigente: el PDF vuelve a ser el borrador.
    pdf = client.get(f"/api/fiscal-mx/documents/{doc['id']}/pdf", headers=headers)
    assert pdf.status_code == 200 and "ninguna" in pdf.headers["x-validez-fiscal"]

    # Corregido (aquí basta validar otra vez), se sella de nuevo: el sellado rechazado se conserva.
    assert client.post(f"/api/fiscal-mx/documents/{doc['id']}/validate", headers=headers).json()["listo"]
    ok = _stamp(client, headers, doc["id"])
    assert ok.status_code == 200 and ok.json()["estado"] == "TIMBRADO"
    assert [x.secuencia for x in _xmls(db, doc["id"], "SELLADO")] == [1, 2]
    assert ok.json()["ultimo_error"] is None
    assert len([e for e in _bitacora(db, doc["id"]) if e.evento == "SELLO"]) == 2


def test_rechazo_ajeno_a_la_factura_reenvia_el_mismo_xml(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.rechazar_con = ("SALDO", "Saldo insuficiente")
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 502 and "timbres" in response.json()["detail"]
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()["estado"] == "SELLADO"

    ok = _stamp(client, headers, doc["id"])
    assert ok.status_code == 200 and ok.json()["estado"] == "TIMBRADO"
    assert len(_xmls(db, doc["id"], "SELLADO")) == 1  # no se volvió a sellar


@pytest.mark.parametrize(
    ("codigo", "categoria", "texto"),
    [
        ("401", Categoria.FECHA, "72 horas"),
        ("CFDI40102", Categoria.CERTIFICADO, "sello"),
        ("CFDI40143", Categoria.DATOS_RECEPTOR, "RFC del receptor"),
        ("CFDI40103", Categoria.DATOS, "FormaPago"),
        ("XYZ", Categoria.DATOS, "rechazó"),
    ],
)
def test_errores_del_proveedor_en_espanol(codigo, categoria, texto):
    error = normalizar_error(codigo, "texto original")
    assert error.categoria == categoria and texto in error.mensaje


# ---------------------------------------------------------------- API: timeout y reintento


def test_timeout_despues_de_timbrar_consulta_y_no_timbra_dos_veces(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.sin_respuesta_despues = True
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 504 and "no respondió" in response.json()["detail"]
    leido = client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()
    assert leido["estado"] == "SELLADO" and leido["ultimo_error"]["categoria"] == "SIN_RESPUESTA"
    assert pac.envios == 1  # el proveedor sí lo timbró

    ok = _stamp(client, headers, doc["id"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["uuid_fiscal"] == next(iter(pac.timbres.values())).uuid
    assert pac.envios == 1  # se recuperó con la consulta, no con otro envío
    assert len(_xmls(db, doc["id"], "SELLADO")) == 1
    eventos = [e.evento for e in _bitacora(db, doc["id"])]
    assert "CONSULTA_TIMBRADO" in eventos


def test_timeout_antes_de_llegar_consulta_y_luego_envia(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.sin_respuesta_antes = True
    assert _stamp(client, headers, doc["id"]).status_code == 504
    assert pac.envios == 0

    ok = _stamp(client, headers, doc["id"])
    assert ok.status_code == 200 and ok.json()["estado"] == "TIMBRADO"
    assert pac.envios == 1
    fila = db.get(FiscalDocument, doc["id"])
    assert fila.timbrado_intentos == 2


def test_si_la_consulta_tampoco_responde_no_se_reenvia(client, timbrado, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.sin_respuesta_antes = True
    _stamp(client, headers, doc["id"])
    pac.consulta_sin_respuesta = True
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 504 and "sigue sin responder" in response.json()["detail"]
    assert pac.envios == 0


def test_envio_en_curso_no_se_duplica(client, db, timbrado, pac):
    """Un envío sin respuesta registrada y reciente (doble clic, o el proceso murió hace segundos)."""
    headers = _empresa(client)
    doc = _lista(client, headers)
    pac.rechazar_con = ("SALDO", "sin saldo")  # deja el documento SELLADO
    _stamp(client, headers, doc["id"])
    fila = db.get(FiscalDocument, doc["id"])
    fila.timbrado_enviado_at = dt.datetime.now(dt.timezone.utc)
    fila.ultimo_error = None
    db.commit()
    response = _stamp(client, headers, doc["id"])
    assert response.status_code == 409 and "se está timbrando" in response.json()["detail"]

    # Pasado el margen se trata como indeterminado: consulta (no lo tiene) y envía.
    fila.timbrado_enviado_at = dt.datetime.now(dt.timezone.utc) - timbrado_service.ENVIO_EN_CURSO * 2
    db.commit()
    assert _stamp(client, headers, doc["id"]).status_code == 200 and pac.envios == 1


def test_sin_respuesta_de_un_proveedor_no_se_manda_a_otro(client, firmante, pac):
    headers = _empresa(client)
    doc = _lista(client, headers)
    primero = cfdi_config.ServiciosTimbrado(proveedor=pac, firmante_para=lambda _o, _r: firmante)
    otro = ProveedorSimulado(nombre="contingencia")
    segundo = cfdi_config.ServiciosTimbrado(proveedor=otro, firmante_para=lambda _o, _r: firmante)
    try:
        fastapi_app.dependency_overrides[fiscal_router.servicios_timbrado] = lambda: primero
        pac.sin_respuesta_despues = True
        assert _stamp(client, headers, doc["id"]).status_code == 504
        fastapi_app.dependency_overrides[fiscal_router.servicios_timbrado] = lambda: segundo
        response = _stamp(client, headers, doc["id"])
    finally:
        fastapi_app.dependency_overrides.pop(fiscal_router.servicios_timbrado, None)
    assert response.status_code == 409 and "simulado" in response.json()["detail"]
    assert otro.envios == 0


# ---------------------------------------------------------------- API: cancelación


def test_cancelar_motivo_02_hasta_cancelado(client, db, timbrado, pac):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    libro_antes = _libro(client, headers)

    response = _cancel(client, headers, doc["id"], "02")
    assert response.status_code == 200, response.text
    assert response.json()["estado"] == "CANCELACION_EN_PROCESO"
    assert response.json()["cancelacion_motivo"] == "02"
    solicitud = pac.cancelaciones[-1]
    assert verificar_solicitud(solicitud) and doc["uuid_fiscal"].encode() in solicitud
    assert len(_xmls(db, doc["id"], "ACUSE_CANCELACION")) == 1
    firma = next(e for e in _bitacora(db, doc["id"]) if e.evento == "FIRMA_CANCELACION")
    assert firma.sha256 == hashlib.sha256(solicitud).hexdigest() and firma.user_id

    # Mientras el SAT no resuelve, sigue en proceso; el desenlace sale de la consulta.
    assert _status(client, headers, doc["id"])["estado"] == "CANCELACION_EN_PROCESO"
    assert _cancel(client, headers, doc["id"]).status_code == 409
    pac.resolver_cancelacion(doc["uuid_fiscal"], aceptada=True)
    estatus = _status(client, headers, doc["id"])
    assert (estatus["estado"], estatus["estatus_sat"], estatus["validez_fiscal"]) == ("CANCELADO", "Cancelado", False)
    assert estatus["cancelled_at"]

    # Cancelar el CFDI no cancela el ingreso ni toca el libro.
    assert _libro(client, headers) == libro_antes
    ingreso = client.get(f"/api/income/{doc['ingreso']['id']}", headers=headers).json()
    assert ingreso["status"] == "PAID" and ingreso["amount"] == "1160.00"
    assert _cancel(client, headers, doc["id"]).status_code == 409


def test_el_receptor_rechaza_la_cancelacion_y_se_puede_volver_a_pedir(client, timbrado, pac):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    assert _cancel(client, headers, doc["id"], "03").status_code == 200
    pac.resolver_cancelacion(doc["uuid_fiscal"], aceptada=False)
    assert _status(client, headers, doc["id"])["estado"] == "CANCELACION_RECHAZADA"
    otra = _cancel(client, headers, doc["id"], "03")
    assert otra.status_code == 200 and otra.json()["estado"] == "CANCELACION_EN_PROCESO"


def test_motivo_01_exige_la_factura_que_sustituye_timbrada(client, timbrado):
    headers = _empresa(client)
    cliente = _cliente(client, headers)
    original = _hasta_timbrado(client, headers)

    sin_folio = _cancel(client, headers, original["id"], "01")
    assert sin_folio.status_code == 422 and "motivo 01" in sin_folio.json()["detail"]
    inventado = _cancel(client, headers, original["id"], "01", "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")
    assert inventado.status_code == 422 and "timbrada" in inventado.json()["detail"]
    mismo = _cancel(client, headers, original["id"], "01", original["uuid_fiscal"])
    assert mismo.status_code == 422
    con_folio_y_02 = _cancel(client, headers, original["id"], "02", original["uuid_fiscal"])
    assert con_folio_y_02.status_code == 422
    assert client.post(
        f"/api/fiscal-mx/documents/{original['id']}/cancel", headers=headers, json={"motivo": "05"}
    ).status_code == 422

    nueva = _lista(client, headers, cliente["id"])
    nueva = _stamp(client, headers, nueva["id"]).json()
    ok = _cancel(client, headers, original["id"], "01", nueva["uuid_fiscal"].lower())
    assert ok.status_code == 200, ok.text
    assert ok.json()["cancelacion_folio_sustitucion"] == nueva["uuid_fiscal"]


def test_rechazo_de_la_solicitud_regresa_a_timbrado(client, timbrado, pac):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    pac.rechazar_cancelacion_con = ("205", "Folio Fiscal No existe")
    response = _cancel(client, headers, doc["id"])
    assert response.status_code == 422 and "todavía no registra" in response.json()["detail"]
    leido = client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()
    assert leido["estado"] == "TIMBRADO" and leido["ultimo_error"]["categoria"] == "REINTENTAR"


def test_cancelacion_sin_respuesta_se_puede_reintentar(client, timbrado, pac):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    pac.cancelacion_sin_respuesta = True
    response = _cancel(client, headers, doc["id"])
    assert response.status_code == 504
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}", headers=headers).json()["estado"] == "CANCELACION_EN_PROCESO"
    otra = _cancel(client, headers, doc["id"])
    assert otra.status_code == 200 and len(pac.cancelaciones) == 2


def test_solo_se_cancela_lo_timbrado(client, timbrado):
    headers = _empresa(client)
    doc = _lista(client, headers)
    response = _cancel(client, headers, doc["id"])
    assert response.status_code == 409 and "timbrada" in response.json()["detail"]


# ---------------------------------------------------------------- candado, permisos y aislamiento


def test_apagado_por_omision_responde_503(client):
    headers = _empresa(client)
    doc = _lista(client, headers)
    for respuesta in (_stamp(client, headers, doc["id"]), _cancel(client, headers, doc["id"])):
        assert respuesta.status_code == 503
        assert respuesta.json()["detail"].startswith("El timbrado aún no está disponible")
    estatus = _status(client, headers, doc["id"])
    assert (estatus["estado"], estatus["timbrado_disponible"]) == ("LISTO_PARA_TIMBRAR", False)


def test_configuracion_de_produccion(csd_archivos, monkeypatch):
    base = get_settings()
    assert base.cfdi_timbrado_habilitado is False  # nada se enciende sin pedirlo

    def construir(**cambios):
        return cfdi_config.construir(dataclasses.replace(base, **cambios))

    with pytest.raises(cfdi_config.TimbradoNoDisponible, match="aún no está disponible"):
        construir()
    for firmante, proveedor in (("local_pruebas", "simulado"), ("kms", "formas_digitales_pruebas"), ("kms", "simulado")):
        with pytest.raises(cfdi_config.TimbradoNoDisponible, match="producción"):
            construir(env="production", cfdi_timbrado_habilitado=True, cfdi_firmante=firmante, cfdi_proveedor=proveedor)
    with pytest.raises(cfdi_config.TimbradoNoDisponible, match="servicio de llaves"):
        construir(env="production", cfdi_timbrado_habilitado=True)  # kms + prodigia: los dos huecos
    with pytest.raises(cfdi_config.TimbradoNoDisponible, match="CFDI_CSD_PRUEBAS_CER"):
        construir(cfdi_timbrado_habilitado=True, cfdi_firmante="local_pruebas", cfdi_proveedor="simulado")

    # En desarrollo, con el CSD de prueba y el simulado, sí arma; Prodigia aún es un hueco.
    cer, key = csd_archivos
    monkeypatch.setenv("CFDI_CSD_PRUEBAS_CER", str(cer))
    monkeypatch.setenv("CFDI_CSD_PRUEBAS_KEY", str(key))
    monkeypatch.setenv("CFDI_CSD_PRUEBAS_CONTRASENA", CONTRASENA)
    with pytest.raises(cfdi_config.TimbradoNoDisponible, match="proveedor de timbrado"):
        construir(cfdi_timbrado_habilitado=True, cfdi_firmante="local_pruebas", cfdi_proveedor="prodigia")
    servicios = construir(cfdi_timbrado_habilitado=True, cfdi_firmante="local_pruebas", cfdi_proveedor="simulado")
    assert servicios.nombre_proveedor == "simulado"
    assert rfc_del_certificado(servicios.firmante_para("org", RFC_EMISOR).certificado()) == RFC_EMISOR


@pytest.mark.parametrize("rol", ["ACCOUNTANT", "MEMBER", "VIEWER"])
def test_solo_dueno_o_administrador_timbra_y_cancela(client, timbrado, rol):
    headers = _empresa(client)
    doc = _lista(client, headers)
    invitacion = client.post(
        "/api/organizations/current/members",
        headers=headers,
        json={"email": "equipo@example.com", "name": "Equipo", "role": rol, "password": "supersegura123"},
    )
    assert invitacion.status_code == 201, invitacion.text
    login = client.post("/api/auth/login", json={"email": "equipo@example.com", "password": "supersegura123"}).json()
    otro = auth_headers(login)
    assert _stamp(client, otro, doc["id"]).status_code == 403
    assert _cancel(client, otro, doc["id"]).status_code == 403
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}/status", headers=otro).status_code == 200


def test_administrador_si_timbra(client, timbrado):
    headers = _empresa(client)
    doc = _lista(client, headers)
    client.post(
        "/api/organizations/current/members",
        headers=headers,
        json={"email": "admin@example.com", "name": "Admin", "role": "ADMIN", "password": "supersegura123"},
    )
    admin = auth_headers(client.post("/api/auth/login", json={"email": "admin@example.com", "password": "supersegura123"}).json())
    assert _stamp(client, admin, doc["id"]).status_code == 200


def test_aislamiento_entre_empresas(client, timbrado):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    otra = _empresa(client, email="otra@example.com")
    assert _stamp(client, otra, doc["id"]).status_code == 404
    assert _cancel(client, otra, doc["id"]).status_code == 404
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}/status", headers=otra).status_code == 404
    assert client.get(f"/api/fiscal-mx/documents/{doc['id']}/stamped-xml", headers=otra).status_code == 404


def test_xml_timbrado_aun_no_existe(client, timbrado):
    headers = _empresa(client)
    doc = _lista(client, headers)
    response = client.get(f"/api/fiscal-mx/documents/{doc['id']}/stamped-xml", headers=headers)
    assert response.status_code == 404 and "aún no está timbrada" in response.json()["detail"]


def test_la_bitacora_no_se_modifica(client, db, timbrado):
    headers = _empresa(client)
    doc = _hasta_timbrado(client, headers)
    fila = _bitacora(db, doc["id"])[0]
    fila.mensaje = "otra cosa"
    with pytest.raises(BitacoraInmutable):
        db.flush()
    db.rollback()


@pytest.mark.postgres
def test_postgres_impide_modificar_la_bitacora(client, db, timbrado):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    headers = _empresa(client)
    _hasta_timbrado(client, headers)
    with pytest.raises(DBAPIError, match="no se modifica ni se borra"):
        with db.begin_nested():
            db.execute(text("UPDATE documentos_fiscales_bitacora SET mensaje = 'x'"))


# ---------------------------------------------------------------- Formas Digitales (respuestas grabadas, sin red)


class _Grabado:
    def __init__(self, *archivos):
        self._archivos = list(archivos)
        self.enviados = []

    def __call__(self, url, accion, cuerpo):
        self.enviados.append((url, cuerpo))
        archivo = self._archivos.pop(0)
        if archivo == "timeout":
            raise SinRespuesta("timed out")
        return (FIXTURES / archivo).read_bytes()


def test_formas_digitales_cumple_la_interfaz_y_no_corre_en_produccion():
    assert isinstance(FormasDigitalesPruebas("u", "p", _Grabado(), entorno="test"), ProveedorTimbrado)
    assert isinstance(ProveedorSimulado(), ProveedorTimbrado)
    with pytest.raises(ValueError, match="pruebas"):
        FormasDigitalesPruebas("u", "p", _Grabado(), entorno="production")
    with pytest.raises(ValueError, match="FD_USUARIO"):
        FormasDigitalesPruebas("", "", _Grabado(), entorno="test")


def test_formas_digitales_timbra_y_consulta_reenviando_el_mismo_xml():
    t = _Grabado("fd_timbrar_ok.xml", "fd_timbrar_ok.xml", "timeout")
    fd = FormasDigitalesPruebas("u", "p", t, entorno="test")
    r = fd.timbrar(b"<cfdi:Comprobante xmlns:cfdi='x'/>", "doc:1")
    assert r.estado is Estado.TIMBRADO and r.uuid == "8C8D31A9-21B1-4604-9EE0-DF8349849ED5"
    assert r.rfc_prov_certif == "SPR190613I52" and r.xml_timbrado
    consulta = fd.consultar_timbrado(b"<cfdi:Comprobante xmlns:cfdi='x'/>", "doc:1")
    assert consulta.uuid == r.uuid and t.enviados[0] == t.enviados[1]  # mismos bytes
    assert t.enviados[0][0] == URL_TIMBRADO_PRUEBAS
    assert fd.timbrar(b"<x/>", "doc:1").estado is Estado.INDETERMINADO


@pytest.mark.parametrize(
    ("archivo", "categoria", "codigo"),
    [
        ("fd_timbrar_401.xml", Categoria.FECHA, "401"),
        ("fd_timbrar_cfdi40147.xml", Categoria.DATOS_RECEPTOR, "CFDI40147"),
        ("fd_timbrar_credenciales.xml", Categoria.CREDENCIALES, "CFDI40999"),
    ],
)
def test_formas_digitales_rechazos(archivo, categoria, codigo):
    r = FormasDigitalesPruebas.interpretar_timbrado((FIXTURES / archivo).read_bytes())
    assert r.estado is Estado.RECHAZADO
    assert (r.error.categoria, r.error.codigo_proveedor) == (categoria, codigo) and r.error.mensaje


def test_formas_digitales_cancelacion_y_estatus(firmante):
    aceptada = FormasDigitalesPruebas.interpretar_cancelacion((FIXTURES / "fd_cancelar_201.xml").read_bytes())
    assert aceptada.estado is EstadoCancelacion.ACEPTADA and aceptada.acuse
    pendiente = FormasDigitalesPruebas.interpretar_cancelacion((FIXTURES / "fd_cancelar_205.xml").read_bytes())
    assert pendiente.estado is EstadoCancelacion.RECHAZADA and pendiente.error.categoria is Categoria.REINTENTAR
    estatus = FormasDigitalesPruebas.interpretar_estatus((FIXTURES / "fd_estatus_en_proceso.xml").read_bytes())
    assert (estatus.estado, estatus.estatus_cancelacion) == ("Vigente", "En proceso")

    # La solicitud se desarma en campos y la firma viaja tal cual.
    fd = FormasDigitalesPruebas("u", "p", _Grabado("fd_cancelar_201.xml"), entorno="test")
    sol = armar_solicitud(
        firmante, RFC_EMISOR, [FolioCancelacion("87CC3E45-05A9-45C3-936C-F5ABC784DC4F", "02")],
        dt.datetime(2026, 11, 25, 12, 42, 49), folio_sustitucion_vacio=fd.folio_sustitucion_vacio,
    )
    assert fd.cancelar(sol).estado is EstadoCancelacion.ACEPTADA


def test_las_grabadas_no_traen_credenciales():
    for archivo in FIXTURES.iterdir():
        contenido = archivo.read_bytes()
        for marca in (b"password>", b"usuario>", b"PRIVATE KEY"):
            assert marca not in contenido, archivo.name


# ---------------------------------------------------------------- con el CSD de prueba del SAT, si está a mano

DIR_CSD_SAT = Path(os.environ.get("SPIKE_CSD_DIR", Path.home() / ".cache" / "atlas-financials-spike-csd"))


@pytest.fixture(scope="module")
def firmante_sat():
    cer = sorted(DIR_CSD_SAT.glob("CSD_*EKU9003173C9*.cer"))
    key = sorted(DIR_CSD_SAT.glob("CSD_*EKU9003173C9*.key"))
    if not cer or not key:
        pytest.skip(f"Sin CSD de prueba del SAT en {DIR_CSD_SAT} (lo baja spikes/cfdi_sellado/descargar_recursos_sat.py)")
    return FirmanteLocalPruebas.desde_archivos(cer[0], key[0], CONTRASENA, entorno="test")


def test_csd_del_sat_reproduce_byte_a_byte_la_cancelacion_publica_de_formas_digitales(firmante_sat):
    """Mismo ejemplo que verificó el spike: el SAT de pruebas acepta esa firma."""
    sol = armar_solicitud(
        firmante_sat, RFC_EMISOR, [FolioCancelacion("B7EBEDF0-0AD8-4644-A6BA-EF650698E166", "02")],
        dt.datetime(2026, 1, 21, 13, 0, 39), "sha1", folio_sustitucion_vacio=True,
    )
    raiz = etree.fromstring(sol)
    assert raiz.findtext(f".//{{{NS_DSIG}}}DigestValue") == "xvzmo6rIOtDcN66fd/Dh9mL0IcA="
    assert raiz.findtext(f".//{{{NS_DSIG}}}SignatureValue").startswith("B2AJZyVyUOtFHbq+jwjsi8ILPI+043QM2BQnZtMyZbjw")
    assert numero_certificado(firmante_sat.certificado()) == "30001000000500003416"


def test_csd_del_sat_sella_y_verifica(firmante_sat):
    from tests.test_cfdi_documento_fiscal import _comprobante, _op
    from app.services.cfdi.armado import armar
    from app.services.cfdi.comprobante import xml_sin_sellar

    sellado = sellar(xml_sin_sellar(_comprobante(armar(_op("1160.00")))), firmante_sat)
    assert verificar_sello(sellado.xml) and xml_sat.errores_xsd(sellado.xml) == []
