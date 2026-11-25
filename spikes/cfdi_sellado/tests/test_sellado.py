"""El sello de un CFDI 4.0 se puede delegar a un firmante que sólo ve bytes."""

import base64
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap_with_padding
from lxml import etree
from satcfdi.create.cfd import cfdi40

from conftest import CONTRASENA_PRUEBA
from firmante import Firmante, FirmanteAwsKms, FirmanteLocal, descifrar_llave_csd, numero_certificado
from importar_csd_kms import envolver_rsa_aes_key_wrap_sha256, material_pkcs8_desde_csd
from sellado import comprobante_de_prueba, sellar_con_satcfdi, sellar_xml
from verificacion_sat import cadena_original, errores_xsd, verificar_sello


# ---------------------------------------------------------------- dobles de prueba


class FirmanteEspia:
    """Envuelve a otro firmante y registra exactamente qué bytes recibió."""

    def __init__(self, interno: Firmante):
        self.interno = interno
        self.recibidos: list[bytes] = []

    def firmar(self, datos: bytes) -> bytes:
        assert isinstance(datos, bytes)
        self.recibidos.append(datos)
        return self.interno.firmar(datos)

    def certificado(self) -> x509.Certificate:
        return self.interno.certificado()


class KmsSimulado:
    """Imita ``kms:Sign``/``kms:GetPublicKey`` para una llave RSA_2048 importada.

    NO es KMS: sólo reproduce el contrato documentado (DIGEST de 32 bytes,
    RSASSA_PKCS1_V1_5_SHA_256, respuesta con ``Signature`` en binario) para
    probar el adaptador. La llave vive aquí como viviría dentro de KMS.
    """

    def __init__(self, key_id: str, llave: rsa.RSAPrivateKey):
        self.key_id = key_id
        self._llave = llave
        self.llamadas: list[dict] = []

    def get_public_key(self, KeyId):
        assert KeyId == self.key_id
        spki = self._llave.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return {"KeyId": KeyId, "PublicKey": spki, "KeySpec": "RSA_2048", "KeyUsage": "SIGN_VERIFY"}

    def sign(self, KeyId, Message, MessageType, SigningAlgorithm):
        self.llamadas.append({"MessageType": MessageType, "len": len(Message), "alg": SigningAlgorithm})
        assert KeyId == self.key_id
        assert SigningAlgorithm == "RSASSA_PKCS1_V1_5_SHA_256"
        if MessageType == "RAW":
            if len(Message) > 4096:
                raise ValueError("ValidationException: Message must be <= 4096 bytes")
            firma = self._llave.sign(Message, padding.PKCS1v15(), hashes.SHA256())
        else:
            assert MessageType == "DIGEST" and len(Message) == 32
            firma = self._llave.sign(Message, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
        return {"KeyId": KeyId, "Signature": firma, "SigningAlgorithm": SigningAlgorithm}


@pytest.fixture(scope="module")
def llave_csd(key_path):
    return descifrar_llave_csd(key_path.read_bytes(), CONTRASENA_PRUEBA)


@pytest.fixture
def kms(llave_csd):
    return KmsSimulado("arn:aws:kms:us-east-1:000000000000:key/simulada", llave_csd)


def _sello(xml: bytes) -> str:
    return etree.fromstring(xml).get("Sello")


# ---------------------------------------------------------------- el CSD de prueba


def test_csd_de_prueba_es_rsa2048_pkcs8_cifrado(cer_path, key_path, llave_csd):
    cert = x509.load_der_x509_certificate(cer_path.read_bytes())
    assert llave_csd.key_size == 2048
    assert llave_csd.public_key().public_numbers().e == 65537
    # .key = EncryptedPrivateKeyInfo: sin contraseña no abre.
    with pytest.raises(TypeError):
        serialization.load_der_private_key(key_path.read_bytes(), password=None)
    assert numero_certificado(cert) == "30001000000500003416"
    assert "EKU9003173C9" in cert.subject.rfc4514_string()


# ---------------------------------------------------------------- camino satcfdi


def test_satcfdi_acepta_firma_externa_y_el_xml_valida(firmante_local):
    espia = FirmanteEspia(firmante_local)
    xml = sellar_con_satcfdi(comprobante_de_prueba(), espia)

    # El firmante recibió una sola vez exactamente la cadena original oficial.
    assert len(espia.recibidos) == 1
    cadena = cadena_original(xml)
    assert espia.recibidos[0] == cadena.encode("utf-8")
    assert cadena.startswith("||4.0|SPK|1|2026-11-25T10:00:00|03|30001000000500003416|")
    assert cadena.endswith("||")

    assert errores_xsd(xml) == []
    verificar_sello(xml)


def test_cadena_de_satcfdi_coincide_con_la_xslt_oficial(firmante_local):
    comprobante = comprobante_de_prueba()
    xml = sellar_con_satcfdi(comprobante, firmante_local)
    assert comprobante.cadena_original() == cadena_original(xml)


# ---------------------------------------------------------------- camino sin satcfdi


def test_sellar_xml_sin_satcfdi_da_el_mismo_sello(firmante_local):
    sin_sellar = comprobante_de_prueba().xml_bytes()
    xml = sellar_xml(sin_sellar, firmante_local)
    assert errores_xsd(xml) == []
    verificar_sello(xml)
    # PKCS#1 v1.5 es determinista: mismo comprobante, misma llave => mismo sello.
    assert _sello(xml) == _sello(sellar_con_satcfdi(comprobante_de_prueba(), firmante_local))


# ---------------------------------------------------------------- adaptador de KMS (simulado)


def test_kms_simulado_produce_el_mismo_sello_que_la_firma_local(firmante_local, cer_path, kms):
    cert = x509.load_der_x509_certificate(cer_path.read_bytes())
    firmante_kms = FirmanteAwsKms(kms.key_id, cert, cliente=kms)
    assert isinstance(firmante_kms, Firmante)

    xml_kms = sellar_con_satcfdi(comprobante_de_prueba(), firmante_kms)
    xml_local = sellar_con_satcfdi(comprobante_de_prueba(), firmante_local)

    assert kms.llamadas == [{"MessageType": "DIGEST", "len": 32, "alg": "RSASSA_PKCS1_V1_5_SHA_256"}]
    assert _sello(xml_kms) == _sello(xml_local)
    assert errores_xsd(xml_kms) == []
    verificar_sello(xml_kms)


def test_cadena_mayor_a_4096_bytes_obliga_a_firmar_el_digest(firmante_local, cer_path, kms):
    comprobante = comprobante_de_prueba()
    comprobante["Conceptos"] = [
        cfdi40.Concepto(
            clave_prod_serv="84111506",
            cantidad=Decimal("1"),
            clave_unidad="E48",
            descripcion=f"Concepto {i} con una descripción larga para inflar la cadena original",
            valor_unitario=Decimal("10.00"),
            objeto_imp="02",
            impuestos=cfdi40.Impuestos(
                traslados=cfdi40.Traslado(impuesto="002", tipo_factor="Tasa", tasa_o_cuota=Decimal("0.160000")),
            ),
        )
        for i in range(60)
    ]
    comprobante.compute()
    cert = x509.load_der_x509_certificate(cer_path.read_bytes())
    xml = sellar_con_satcfdi(comprobante, FirmanteAwsKms(kms.key_id, cert, cliente=kms))

    assert len(cadena_original(xml).encode("utf-8")) > 4096
    with pytest.raises(ValueError, match="4096"):
        kms.sign(kms.key_id, cadena_original(xml).encode(), "RAW", "RSASSA_PKCS1_V1_5_SHA_256")
    assert errores_xsd(xml) == []
    verificar_sello(xml)


def test_adaptador_kms_rechaza_llave_que_no_es_del_certificado(cer_path):
    ajena = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = x509.load_der_x509_certificate(cer_path.read_bytes())
    with pytest.raises(ValueError, match="no corresponde"):
        FirmanteAwsKms("otra", cert, cliente=KmsSimulado("otra", ajena))


# ---------------------------------------------------------------- la verificación sí detecta fallas


def test_alterar_el_xml_rompe_el_sello(firmante_local):
    xml = sellar_con_satcfdi(comprobante_de_prueba(), firmante_local)
    alterado = xml.replace(b'Total="3480.00"', b'Total="3481.00"')
    assert alterado != xml
    with pytest.raises(ValueError, match="no verifica"):
        verificar_sello(alterado)


def test_firma_con_otra_llave_no_verifica(firmante_local):
    ajena = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Impostor:
        def firmar(self, datos):
            return ajena.sign(datos, padding.PKCS1v15(), hashes.SHA256())

        def certificado(self):
            return firmante_local.certificado()

    with pytest.raises(ValueError, match="no verifica"):
        verificar_sello(sellar_con_satcfdi(comprobante_de_prueba(), Impostor()))


def test_firmante_local_rechaza_llave_ajena(firmante_local):
    ajena = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError):
        FirmanteLocal(firmante_local.certificado(), ajena)


def test_xsd_oficial_detecta_un_comprobante_invalido(firmante_local):
    xml = sellar_con_satcfdi(comprobante_de_prueba(), firmante_local)
    raiz = etree.fromstring(xml)
    del raiz.attrib["LugarExpedicion"]
    assert errores_xsd(etree.tostring(raiz))


# ---------------------------------------------------------------- material para importar a KMS


def test_material_para_kms_es_pkcs8_sin_cifrar_y_corresponde_al_cer(key_path, firmante_local):
    material = material_pkcs8_desde_csd(key_path.read_bytes(), CONTRASENA_PRUEBA)
    llave = serialization.load_der_private_key(material, password=None)
    FirmanteLocal(firmante_local.certificado(), llave)  # lanza si no corresponde


def test_envoltura_rsa_aes_key_wrap_sha256_es_reversible(key_path):
    material = material_pkcs8_desde_csd(key_path.read_bytes(), CONTRASENA_PRUEBA)
    # Hace las veces de la llave pública de envoltura que da GetParametersForImport.
    envoltura = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    publica_der = envoltura.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    envuelto = envolver_rsa_aes_key_wrap_sha256(material, publica_der)

    aes = envoltura.decrypt(
        envuelto[:512],
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    assert len(aes) == 32
    assert aes_key_unwrap_with_padding(aes, envuelto[512:]) == material
    assert base64.b64encode(material) not in base64.b64encode(envuelto)
