"""Interfaz ``Firmante`` y sus implementaciones.

El sello del CFDI 4.0 es RSASSA-PKCS1-v1_5 con SHA-256 sobre los bytes UTF-8 de
la cadena original (Anexo 20, rubro I.B). Un ``Firmante`` recibe esos bytes y
devuelve la firma binaria; quien lo llama no sabe si la llave vive en memoria,
en AWS KMS o en Google Cloud KMS.

- ``FirmanteLocal``: llave en memoria (software). Es la que corre en las pruebas.
- ``FirmanteAwsKms``: delega a ``kms:Sign``. **NO PROBADO contra AWS real.**
  Sus pruebas usan un cliente simulado que imita la semántica de ``Sign``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


@runtime_checkable
class Firmante(Protocol):
    """Lo único que el sellado necesita de quien custodia la llave."""

    def firmar(self, datos: bytes) -> bytes:
        """RSASSA-PKCS1-v1_5 + SHA-256 sobre ``datos`` (la cadena original en UTF-8)."""
        ...

    def certificado(self) -> x509.Certificate:
        """Certificado X.509 del CSD cuya llave privada produce la firma."""
        ...


def cargar_certificado(cer_der: bytes) -> x509.Certificate:
    return x509.load_der_x509_certificate(cer_der)


def numero_certificado(cert: x509.Certificate) -> str:
    """NoCertificado del SAT: el serial X.509 está codificado como texto ASCII."""
    serial = cert.serial_number
    return serial.to_bytes((serial.bit_length() + 7) // 8, "big").decode("ascii")


def descifrar_llave_csd(key_der: bytes, contrasena: str | bytes) -> rsa.RSAPrivateKey:
    """El .key del SAT es PKCS#8 cifrado (EncryptedPrivateKeyInfo, PBES2) en DER."""
    if isinstance(contrasena, str):
        contrasena = contrasena.encode()
    llave = serialization.load_der_private_key(key_der, password=contrasena)
    if not isinstance(llave, rsa.RSAPrivateKey):
        raise ValueError("La llave del CSD no es RSA")
    return llave


def llave_corresponde(llave: rsa.RSAPrivateKey, cert: x509.Certificate) -> bool:
    fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return llave.public_key().public_bytes(*fmt) == cert.public_key().public_bytes(*fmt)


class FirmanteLocal:
    """Llave del CSD en memoria. Equivale al respaldo de D1 (llave descifrada sólo al sellar)."""

    def __init__(self, cert: x509.Certificate, llave: rsa.RSAPrivateKey):
        if not llave_corresponde(llave, cert):
            raise ValueError("La llave privada no corresponde al certificado")
        self._cert = cert
        self._llave = llave

    @classmethod
    def desde_archivos(cls, cer: Path, key: Path, contrasena: str) -> "FirmanteLocal":
        return cls(cargar_certificado(cer.read_bytes()), descifrar_llave_csd(key.read_bytes(), contrasena))

    def firmar(self, datos: bytes) -> bytes:
        return self._llave.sign(datos, padding.PKCS1v15(), hashes.SHA256())

    def firmar_sha1(self, datos: bytes) -> bytes:
        """RSA-SHA1: sólo para la solicitud de cancelación (ver ``cancelacion.py``)."""
        return self._llave.sign(datos, padding.PKCS1v15(), hashes.SHA1())

    def certificado(self) -> x509.Certificate:
        return self._cert


class FirmanteAwsKms:
    """Firma dentro de AWS KMS con una llave RSA_2048 importada del CSD.

    **NO PROBADO contra AWS.** Escrito según la API documentada de ``kms:Sign``:

    - Se calcula SHA-256 localmente y se manda con ``MessageType='DIGEST'``.
      Con ``RAW`` KMS acepta hasta 4096 bytes de mensaje y una cadena original
      con muchos conceptos lo rebasa; con ``DIGEST`` el tamaño es fijo (32 bytes)
      y la cadena original (datos fiscales) nunca sale del proceso.
    - ``SigningAlgorithm='RSASSA_PKCS1_V1_5_SHA_256'`` produce exactamente
      RSASSA-PKCS1-v1_5 con DigestInfo SHA-256: el mismo sello que una firma local.
    - El certificado NO vive en KMS (KMS sólo guarda el par de llaves): se
      guarda aparte (base de datos) y al construir se comprueba que su llave
      pública coincide con ``GetPublicKey``.

    ``cliente`` es un ``boto3.client('kms')`` o cualquier objeto con los métodos
    ``sign`` y ``get_public_key`` con la misma firma (las pruebas usan uno simulado).
    """

    ALGORITMO = "RSASSA_PKCS1_V1_5_SHA_256"

    def __init__(self, key_id: str, cert: x509.Certificate, cliente: Any | None = None, verificar_publica: bool = True):
        if cliente is None:
            try:
                import boto3  # noqa: PLC0415 — dependencia opcional
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("boto3 no está instalado (pip install boto3)") from e
            cliente = boto3.client("kms")
        self._cliente = cliente
        self._key_id = key_id
        self._cert = cert
        if verificar_publica:
            resp = cliente.get_public_key(KeyId=key_id)
            if resp.get("KeySpec") != "RSA_2048" or resp.get("KeyUsage") != "SIGN_VERIFY":
                raise ValueError(f"La llave {key_id} no es RSA_2048/SIGN_VERIFY")
            spki = cert.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            if resp["PublicKey"] != spki:
                raise ValueError("La llave de KMS no corresponde al certificado del CSD")

    def firmar(self, datos: bytes) -> bytes:
        resp = self._cliente.sign(
            KeyId=self._key_id,
            Message=hashlib.sha256(datos).digest(),
            MessageType="DIGEST",
            SigningAlgorithm=self.ALGORITMO,
        )
        return resp["Signature"]

    def certificado(self) -> x509.Certificate:
        return self._cert
