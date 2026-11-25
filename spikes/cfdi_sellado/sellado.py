"""Armado y sellado de un CFDI 4.0 con un ``Firmante`` externo.

Dos caminos, ambos probados:

1. ``sellar_con_satcfdi``: ``satcfdi`` arma el comprobante (cálculo de
   impuestos, totales y orden de nodos) y ``CFDI.sign(signer)`` sella. ``sign``
   no exige una llave: sólo llama a ``signer.certificate_number``,
   ``signer.certificate_base64()`` y ``signer.sign_sha256(cadena_bytes)``. Un
   adaptador que hereda de ``satcfdi.models.Certificate`` (sin llave) y delega
   ``sign_sha256`` al ``Firmante`` basta para inyectar la firma externa.
2. ``sellar_xml``: sin ``satcfdi``. Recibe cualquier XML 4.0 sin sellar, pone
   ``NoCertificado`` y ``Certificado``, calcula la cadena con la XSLT oficial
   del SAT y pone el ``Sello``. Es el respaldo si ``satcfdi`` cambia su contrato.
"""

from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal

from cryptography.hazmat.primitives import serialization
from lxml import etree
from OpenSSL import crypto
from satcfdi.create.cfd import cfdi40
from satcfdi.models import Certificate

from firmante import Firmante, numero_certificado
from verificacion_sat import cadena_original


class SignerExterno(Certificate):
    """Lo que ``satcfdi`` llama "Signer", pero sin llave: firma el ``Firmante``."""

    def __init__(self, firmante: Firmante):
        super().__init__(crypto.X509.from_cryptography(firmante.certificado()))
        self._firmante = firmante

    def sign_sha256(self, data: bytes) -> str:
        return base64.b64encode(self._firmante.firmar(data)).decode("ascii")

    def sign_sha1(self, data: bytes) -> str:  # CFDI 4.0 no usa SHA-1
        raise NotImplementedError("El sello de CFDI 4.0 es SHA-256")


def comprobante_de_prueba(fecha: datetime | None = None) -> cfdi40.Comprobante:
    """Factura de ingreso con IVA 16 % entre dos RFC de prueba del SAT."""
    return cfdi40.Comprobante(
        emisor=cfdi40.Emisor(rfc="EKU9003173C9", nombre="ESCUELA KEMPER URGATE", regimen_fiscal="601"),
        lugar_expedicion="42501",
        receptor=cfdi40.Receptor(
            rfc="URE180429TM6",
            nombre="UNIVERSIDAD ROBOTICA ESPAÑOLA",
            domicilio_fiscal_receptor="86991",
            regimen_fiscal_receptor="601",
            uso_cfdi="G03",
        ),
        conceptos=[
            cfdi40.Concepto(
                clave_prod_serv="84111506",
                cantidad=Decimal("2"),
                clave_unidad="E48",
                descripcion="Servicio de contabilidad mensual — prueba de sellado",
                valor_unitario=Decimal("1500.00"),
                objeto_imp="02",
                impuestos=cfdi40.Impuestos(
                    traslados=cfdi40.Traslado(impuesto="002", tipo_factor="Tasa", tasa_o_cuota=Decimal("0.160000")),
                ),
            ),
        ],
        serie="SPK",
        folio="1",
        forma_pago="03",
        metodo_pago="PUE",
        fecha=fecha or datetime(2026, 11, 25, 10, 0, 0),
    )


def sellar_con_satcfdi(comprobante: cfdi40.Comprobante, firmante: Firmante) -> bytes:
    comprobante.sign(SignerExterno(firmante))
    return comprobante.xml_bytes()


def sellar_xml(xml_sin_sellar: bytes, firmante: Firmante) -> bytes:
    raiz = etree.fromstring(xml_sin_sellar, etree.XMLParser(no_network=True, resolve_entities=False))
    cert = firmante.certificado()
    # NoCertificado entra en la cadena original; Certificado y Sello no.
    raiz.set("NoCertificado", numero_certificado(cert))
    raiz.set("Certificado", base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode("ascii"))
    raiz.set("Sello", "")
    sin_sello = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
    raiz.set("Sello", base64.b64encode(firmante.firmar(cadena_original(sin_sello).encode("utf-8"))).decode("ascii"))
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
