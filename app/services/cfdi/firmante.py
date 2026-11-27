"""Quien custodia la llave del certificado de sello digital (CSD) y firma (ADR-017).

El sello del CFDI 4.0 es RSASSA-PKCS1-v1_5 con SHA-256 sobre los bytes UTF-8 de
la cadena original (Anexo 20). Un ``Firmante`` recibe esos bytes y devuelve la
firma: quien lo llama no sabe si la llave vive en memoria o en un servicio de
llaves. Ninguna función de este módulo devuelve la llave.

- ``FirmanteLocalPruebas``: llave en memoria, **sólo para pruebas y
  desarrollo** con el CSD de prueba del SAT (o uno sintético). Se niega a
  construirse con ``ENV=production``.
- ``FirmanteKms``: hueco para el modo A del ADR-017 (la llave firma dentro de
  AWS KMS o Google Cloud KMS y nunca sale). Aún no hay cuenta: construirlo
  lanza ``FirmanteNoDisponible`` con un mensaje claro. El spike
  ``spikes/cfdi_sellado/firmante.py::FirmanteAwsKms`` tiene la implementación
  escrita contra la API documentada (``Sign`` con ``MessageType=DIGEST``),
  probada sólo contra un simulador.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

# x500UniqueIdentifier: en un CSD del SAT trae "RFC / RFC del representante".
_OID_RFC = NameOID.X500_UNIQUE_IDENTIFIER


class ErrorFirmante(Exception):
    """Error de custodia o de firma, con mensaje en español para la pantalla."""


class FirmanteNoDisponible(ErrorFirmante):
    """No hay firmante configurado o no está permitido en este ambiente."""


@runtime_checkable
class Firmante(Protocol):
    """Lo único que el sellado necesita de quien custodia la llave."""

    #: Identifica la implementación en la bitácora (``local_pruebas``, ``aws_kms``…).
    tipo: str

    def firmar(self, datos: bytes) -> bytes:
        """RSASSA-PKCS1-v1_5 + SHA-256 sobre ``datos``."""
        ...

    def certificado(self) -> x509.Certificate:
        """Certificado X.509 del CSD cuya llave produce la firma."""
        ...


# ---------------------------------------------------------------- certificado


def cargar_certificado(contenido: bytes) -> x509.Certificate:
    """``.cer`` del SAT (DER) o PEM."""
    if contenido.lstrip().startswith(b"-----BEGIN"):
        return x509.load_pem_x509_certificate(contenido)
    return x509.load_der_x509_certificate(contenido)


def numero_certificado(cert: x509.Certificate) -> str:
    """``NoCertificado`` del SAT: el serial X.509 trae los 20 dígitos como texto ASCII."""
    serial = cert.serial_number
    crudo = serial.to_bytes((serial.bit_length() + 7) // 8, "big")
    try:
        texto = crudo.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ErrorFirmante("El certificado no tiene el número de serie con el formato del SAT.") from exc
    if not (len(texto) == 20 and texto.isdigit()):
        raise ErrorFirmante("El certificado no tiene el número de serie con el formato del SAT.")
    return texto


def rfc_del_certificado(cert: x509.Certificate) -> str | None:
    """RFC del titular (primer elemento de ``x500UniqueIdentifier``)."""
    attrs = cert.subject.get_attributes_for_oid(_OID_RFC)
    if not attrs:
        return None
    valor = attrs[0].value
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "replace")
    return valor.split("/")[0].strip().upper() or None


def certificado_der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def descifrar_llave(contenido: bytes, contrasena: str | bytes | None) -> rsa.RSAPrivateKey:
    """``.key`` del SAT (PKCS#8 cifrado en DER) o una llave PEM."""
    if isinstance(contrasena, str):
        contrasena = contrasena.encode()
    try:
        if contenido.lstrip().startswith(b"-----BEGIN"):
            llave = serialization.load_pem_private_key(contenido, password=contrasena or None)
        else:
            llave = serialization.load_der_private_key(contenido, password=contrasena or None)
    except (ValueError, TypeError) as exc:
        raise ErrorFirmante("No se pudo abrir la llave del certificado: revisa el archivo y la contraseña.") from exc
    if not isinstance(llave, rsa.RSAPrivateKey):
        raise ErrorFirmante("La llave del certificado no es RSA.")
    return llave


def llave_corresponde(llave: rsa.RSAPrivateKey, cert: x509.Certificate) -> bool:
    fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return llave.public_key().public_bytes(*fmt) == cert.public_key().public_bytes(*fmt)


def verificar_firma(cert: x509.Certificate, firma: bytes, datos: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415

    try:
        cert.public_key().verify(firma, datos, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False
    return True


# ---------------------------------------------------------------- implementaciones


def _entorno_actual() -> str:
    from app.config import get_settings  # noqa: PLC0415 — evita ciclo al importar

    return get_settings().env


class FirmanteLocalPruebas:
    """Llave del CSD en memoria. **Sólo pruebas y desarrollo.**

    Con ``ENV=production`` no se construye: en producción la llave vive en el
    servicio de llaves (ADR-017) y nunca en el proceso ni en variables.
    """

    tipo = "local_pruebas"

    def __init__(self, cert: x509.Certificate, llave: rsa.RSAPrivateKey, *, entorno: str | None = None):
        if (entorno or _entorno_actual()) == "production":
            raise FirmanteNoDisponible(
                "La firma con llave local es sólo para pruebas: en producción se firma con el servicio de llaves."
            )
        if not llave_corresponde(llave, cert):
            raise ErrorFirmante("La llave no corresponde al certificado.")
        numero_certificado(cert)  # falla temprano si el serial no es del SAT
        self._cert = cert
        self._llave = llave

    @classmethod
    def desde_archivos(
        cls, cer: Path | str, key: Path | str, contrasena: str | None, *, entorno: str | None = None
    ) -> FirmanteLocalPruebas:
        return cls(
            cargar_certificado(Path(cer).read_bytes()),
            descifrar_llave(Path(key).read_bytes(), contrasena),
            entorno=entorno,
        )

    def firmar(self, datos: bytes) -> bytes:
        return self._llave.sign(datos, padding.PKCS1v15(), hashes.SHA256())

    def firmar_sha1(self, datos: bytes) -> bytes:
        """RSA-SHA1: sólo para solicitudes de cancelación de proveedores que no aceptan SHA-256."""
        return self._llave.sign(datos, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303

    def certificado(self) -> x509.Certificate:
        return self._cert


class FirmanteKms:
    """Modo A del ADR-017: la llave firma dentro del servicio de llaves y nunca sale.

    **Aún no conectado**: no hay cuenta de AWS KMS ni de Google Cloud KMS.
    Cuando exista, la implementación es la de
    ``spikes/cfdi_sellado/firmante.py::FirmanteAwsKms``: SHA-256 local, ``Sign``
    con ``MessageType=DIGEST`` y ``RSASSA_PKCS1_V1_5_SHA_256``, y al construir
    se compara ``GetPublicKey`` con el ``.cer`` guardado. Necesita además el
    alta de certificados por empresa (fase 1) para saber qué llave usar.
    """

    tipo = "kms"
    #: Cambia a True con la implementación real (cuenta, permisos y alta de certificados).
    DISPONIBLE = False
    MENSAJE = (
        "El servicio de llaves para sellar facturas aún no está conectado. "
        "El timbrado se habilitará cuando esté listo."
    )

    def __init__(self, *_args, **_kwargs):
        raise FirmanteNoDisponible(self.MENSAJE)

    def firmar(self, datos: bytes) -> bytes:  # pragma: no cover — no se puede construir
        raise FirmanteNoDisponible("El servicio de llaves aún no está conectado.")

    def certificado(self) -> x509.Certificate:  # pragma: no cover
        raise FirmanteNoDisponible("El servicio de llaves aún no está conectado.")
