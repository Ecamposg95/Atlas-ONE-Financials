"""Importación de la llave de un CSD a AWS KMS (material de llave RSA 2048).

Lo que SÍ se prueba localmente:
- ``material_pkcs8_desde_csd``: el .key del SAT (PKCS#8 cifrado) se convierte en
  PKCS#8 DER sin cifrar, que es el formato que exige ``ImportKeyMaterial`` para
  llaves asimétricas (RFC 5208, dos primos).
- ``envolver_rsa_aes_key_wrap_sha256``: el envoltorio ``RSA_AES_KEY_WRAP_SHA_256``
  (AES-256 con key wrap con relleno RFC 5649, y esa AES cifrada con RSAES-OAEP
  SHA-256 con la llave pública de envoltura de KMS). Se prueba desenvolviendo
  con una llave de envoltura generada localmente.

Lo que NO se ha probado (no hay cuenta de AWS en esta máquina):
- ``importar_csd_a_kms``: crear la llave ``EXTERNAL``, pedir parámetros de
  importación, subir el material y firmar. Es el paso que cierra D1: que KMS
  acepte el material de un CSD del SAT y que ``Sign`` produzca un sello que el
  proveedor de timbrado acepte.
"""

from __future__ import annotations

import os
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.keywrap import aes_key_wrap_with_padding

from firmante import descifrar_llave_csd


def material_pkcs8_desde_csd(key_der: bytes, contrasena: str) -> bytes:
    """PKCS#8 DER sin cifrar. Vive sólo en memoria y se descarta tras importar."""
    llave = descifrar_llave_csd(key_der, contrasena)
    if llave.key_size != 2048:
        raise ValueError(f"Se esperaba RSA 2048 y el CSD trae {llave.key_size} bits")
    return llave.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def envolver_rsa_aes_key_wrap_sha256(material: bytes, llave_publica_envoltura_der: bytes) -> bytes:
    """Algoritmo de envoltura ``RSA_AES_KEY_WRAP_SHA_256`` de AWS KMS.

    Resultado = RSA-OAEP-SHA256(llave_aes) || AES-KWP(llave_aes, material).
    (Google Cloud KMS usa el mismo esquema en ``RSA_OAEP_4096_SHA256_AES_256``.)
    """
    publica = serialization.load_der_public_key(llave_publica_envoltura_der)
    if not isinstance(publica, rsa.RSAPublicKey):
        raise ValueError("La llave de envoltura debe ser RSA")
    llave_aes = os.urandom(32)
    try:
        aes_cifrada = publica.encrypt(
            llave_aes,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        return aes_cifrada + aes_key_wrap_with_padding(llave_aes, material)
    finally:
        del llave_aes


def importar_csd_a_kms(
    key_der: bytes,
    contrasena: str,
    descripcion: str,
    cliente: Any | None = None,
) -> str:  # pragma: no cover — NO PROBADO contra AWS
    """Crea una llave KMS ``EXTERNAL`` RSA_2048 y le importa la llave del CSD.

    Devuelve el ``KeyId``. Requiere permisos ``kms:CreateKey``,
    ``kms:GetParametersForImport`` y ``kms:ImportKeyMaterial``; el servicio que
    sella sólo debería tener ``kms:Sign`` y ``kms:GetPublicKey`` sobre esa llave.
    """
    if cliente is None:
        import boto3  # noqa: PLC0415 — dependencia opcional

        cliente = boto3.client("kms")

    llave = cliente.create_key(
        Origin="EXTERNAL",
        KeySpec="RSA_2048",
        KeyUsage="SIGN_VERIFY",
        Description=descripcion,
    )
    key_id = llave["KeyMetadata"]["KeyId"]

    params = cliente.get_parameters_for_import(
        KeyId=key_id,
        WrappingAlgorithm="RSA_AES_KEY_WRAP_SHA_256",
        WrappingKeySpec="RSA_4096",
    )
    material = material_pkcs8_desde_csd(key_der, contrasena)
    try:
        envuelto = envolver_rsa_aes_key_wrap_sha256(material, params["PublicKey"])
    finally:
        del material

    cliente.import_key_material(
        KeyId=key_id,
        ImportToken=params["ImportToken"],
        EncryptedKeyMaterial=envuelto,
        # El CSD vence a los 4 años; KMS no lo sabe. Se podría fijar
        # KEY_MATERIAL_EXPIRES con ValidTo = notAfter del certificado.
        ExpirationModel="KEY_MATERIAL_DOES_NOT_EXPIRE",
    )
    return key_id
