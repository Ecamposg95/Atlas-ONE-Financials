# Spike: sellar un CFDI 4.0 con un firmante externo

Prueba de concepto para la decisión **D1** del megaplan de CFDI (`docs/financials/09_MEGAPLAN_CFDI.md`): ¿podemos sellar sin que la llave del certificado de sello digital (CSD) esté en nuestro proceso, delegando la firma a un servicio de llaves como AWS KMS o Google Cloud KMS?

Nada de esto es código de producción ni vive en `app/`. No timbra contra ningún proveedor.

## Resultado

**Sí, del lado nuestro funciona.** Con el CSD de prueba del SAT (`EKU9003173C9`, certificado `30001000000500003416`):

1. `satcfdi` arma una factura de ingreso 4.0 con IVA 16 %.
2. La cadena original se le entrega a un `Firmante`, que sólo recibe bytes y devuelve la firma.
3. Se inserta el sello y el XML **valida contra el `cfdv40.xsd` oficial** del SAT y **el sello verifica** con el certificado embebido, regenerando la cadena con la **XSLT oficial** `cadenaoriginal_4_0.xslt`. Ninguna de las dos usa las copias que trae `satcfdi`.
4. Un adaptador escrito para AWS KMS (`Sign` con `MessageType=DIGEST` y `RSASSA_PKCS1_V1_5_SHA_256`) produce **el mismo sello, byte por byte**, que la firma local. PKCS#1 v1.5 es determinista, así que esta comparación es exacta. Ojo: el KMS es un **simulador** que respeta el contrato documentado de la API; nunca se habló con AWS.

**¿`satcfdi` deja meter la firma externa?** Sí, y sin parches. `CFDI.sign(signer)` sólo lee `signer.certificate_number` y `signer.certificate_base64()` y llama a `signer.sign_sha256(cadena_bytes)`. No pide la llave ni revisa el tipo. `SignerExterno` (en `sellado.py`) hereda de `satcfdi.models.Certificate`, que no tiene llave, y manda `sign_sha256` al `Firmante`. El riesgo es que ese contrato es interno de `satcfdi` y no está documentado como extensible, por eso la versión va fija en `requirements.txt`. Como respaldo, `sellar_xml` sella cualquier XML 4.0 sin `satcfdi`, usando lxml y la XSLT oficial, y da el mismo sello.

### Hallazgos que importan para el diseño

- **El `.key` del SAT es PKCS#8 cifrado** (`EncryptedPrivateKeyInfo`, PBES2/PBKDF2) en DER, RSA 2048 con exponente 65537. Una vez descifrado, es PKCS#8 DER sin cifrar, que es justo lo que pide `ImportKeyMaterial` de AWS (RFC 5208, dos primos) y Google Cloud KMS. No hace falta convertir con `openssl`. Esto cierra el punto que `seguridad_csd_y_legal.md` dejaba sin verificar.
- **Hay que firmar el digest, no la cadena.** `kms:Sign` con `MessageType=RAW` acepta como máximo 4096 bytes, y una factura con 60 conceptos ya los rebasa (hay una prueba de eso). Con `DIGEST` calculamos el SHA-256 nosotros y a KMS sólo viajan 32 bytes; de paso, los datos fiscales nunca salen del proceso.
- **El certificado no vive en KMS.** KMS guarda el par de llaves; el `.cer` va a la base de datos. El adaptador revisa al construirse que la llave pública de `GetPublicKey` sea la del certificado, para que una llave equivocada falle antes de sellar.
- **La XSLT oficial del SAT tiene inclusiones rotas.** `divisas.xslt` da 404. El script de descarga la cambia por una hoja vacía y lo anota en `recursos_sat/FALTANTES.txt`. No afecta a comprobantes sin ese complemento, pero el módulo real debe guardar sus propias copias de las XSLT en vez de bajarlas cada vez.
- El sello sale igual con la cadena de `satcfdi` que con la XSLT oficial procesada por lxml (libxslt, XSLT 1.0 en modo compatible, aunque la hoja dice 2.0).

## Cómo correrlo

```bash
cd spikes/cfdi_sellado
python3 -m venv .venv            # en esta máquina no hay ensurepip:
#   python3 -m venv --without-pip .venv
#   curl -sSLo /tmp/pip.pyz https://bootstrap.pypa.io/pip/pip.pyz && .venv/bin/python /tmp/pip.pyz install pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python descargar_recursos_sat.py   # XSD/XSLT del SAT y CSD de prueba
.venv/bin/python -m pytest -v                # 13 pruebas
```

`descargar_recursos_sat.py` baja:

| Recurso | Fuente oficial | Dónde queda |
|---|---|---|
| `cfdv40.xsd`, `catCFDI.xsd`, `tdCFDI.xsd` | `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd` y lo que importa | `recursos_sat/` (ignorada por git) |
| `cadenaoriginal_4_0.xslt`, `utilerias.xslt` y los XSLT de complementos | `http://www.sat.gob.mx/sitio_internet/cfd/4/cadenaoriginal_4_0/cadenaoriginal_4_0.xslt` | `recursos_sat/` |
| CSD de prueba (`Certificados_de_Prueba.zip`) | Enlazado desde `http://omawww.sat.gob.mx/tramitesyservicios/Paginas/certificado_sello_digital.htm`: `…/Paginas/documentos/Certificados_de_Prueba.zip`. El Anexo 29 lo ubica en Factura electrónica › Material adicional › Certificados de prueba | **Fuera del repo**: `~/.cache/atlas-financials-spike-csd/` (o `SPIKE_CSD_DIR`) |

Del zip sólo se extrae el CSD de `EKU9003173C9` (`CSD_Sucursal_1_…cer/.key`), no la e.firma. La contraseña de prueba, `12345678a`, es pública: viene en el `Contraseña.txt` del zip. El zip descargado el 2026-11-25 tiene SHA-256 `23563077…f2ebeb8a`; si el SAT lo cambia, el script avisa. Nunca se commitea una llave, aunque sea de prueba. Las pruebas se saltan, con un mensaje claro, si faltan los recursos.

## Archivos

- `firmante.py`: el protocolo `Firmante` (`firmar(datos) -> bytes`, `certificado()`), `FirmanteLocal` (llave en memoria) y `FirmanteAwsKms` (**NO PROBADO**, `boto3` es opcional).
- `importar_csd_kms.py`: convierte el `.key` del SAT en material PKCS#8 y lo envuelve con `RSA_AES_KEY_WRAP_SHA_256`, ambas cosas probadas. También trae `importar_csd_a_kms`, el flujo completo con boto3, **NO PROBADO**.
- `sellado.py`: el adaptador para `satcfdi`, el comprobante de prueba y `sellar_xml` sin `satcfdi`.
- `verificacion_sat.py`: cadena original, validación XSD y verificación del sello con los recursos oficiales, sin red.
- `tests/test_sellado.py`: firma externa con `satcfdi` y sin él, KMS simulado igual a la firma local, cadena de más de 4096 bytes, detección de alteraciones, llave ajena, XSD inválido, material y envoltura para KMS.

## Cómo se importaría la llave del CSD a AWS KMS

1. El cliente sube su `.cer`, su `.key` y su contraseña. En memoria se descifra el `.key` y se revisa que corresponda al `.cer`, que sea RSA 2048 y que sea CSD y no e.firma.
2. `CreateKey` con `Origin=EXTERNAL`, `KeySpec=RSA_2048` y `KeyUsage=SIGN_VERIFY`.
3. `GetParametersForImport` con `WrappingAlgorithm=RSA_AES_KEY_WRAP_SHA_256` y `WrappingKeySpec=RSA_4096` devuelve la llave pública de envoltura y un token que vence a las 24 horas.
4. Se envuelve localmente: una AES-256 nueva envuelve el PKCS#8 con key wrap con relleno (RFC 5649), y esa AES se cifra con RSA-OAEP-SHA256. Luego `ImportKeyMaterial`, y el material y la contraseña se descartan.
5. Desde ese momento, sellar es `Sign(KeyId, SHA256(cadena), DIGEST, RSASSA_PKCS1_V1_5_SHA_256)`. La app sólo necesita `kms:Sign` y `kms:GetPublicKey` sobre esa llave.

Google Cloud KMS funciona igual: un *import job* `RSA_OAEP_4096_SHA256_AES_256` con el mismo esquema de envoltura, el algoritmo `RSA_SIGN_PKCS1_2048_SHA256` y `asymmetricSign` con `digest.sha256`. Su adaptador serían unas 20 líneas con la misma interfaz.

**Por qué este paso es el riesgo.** Todo lo demás es criptografía estándar y aquí ya se demostró que funciona. Lo que no se puede probar sin una cuenta es si KMS acepta *este* material: un RSA 2048 generado por el SAT, con sus propios parámetros (CRT, longitud de primos), dentro de PKCS#8. Tampoco se sabe si el `Sign` real cuadra con el sello local; debería, porque PKCS#1 v1.5 es determinista. Si la importación falla, D1 se va al respaldo: llave cifrada por empresa bajo una llave maestra en KMS, descifrada en memoria al sellar, que es justo `FirmanteLocal`.

## Límites

- No se habló con ningún KMS. `FirmanteAwsKms` e `importar_csd_a_kms` siguen la API documentada, pero sus pruebas corren contra un simulador.
- No se timbró. Que el XML valide y el sello verifique no garantiza que el proveedor lo acepte: faltan las validaciones de la matriz de errores, como padrón, catálogos y la ventana de 72 horas. El receptor `URE180429TM6` y el CP `42501` son datos de prueba comunes, sin cotejar contra el padrón de pruebas del proveedor.
- Sólo se probó una factura de ingreso sin complementos. Pagos 2.0 y nómina 1.2 usan otras XSLT incluidas, que se bajan pero no se prueban.
- El arranque del venv sin `ensurepip` es una peculiaridad de esta máquina.

## Qué falta probar con un KMS real para cerrar D1

1. Hacer los pasos 2 a 4 con el CSD de prueba `EKU9003173C9` en una cuenta de AWS (o GCP) de pruebas. **Hecho cuando:** `ImportKeyMaterial` responde bien y `GetPublicKey` coincide con el `.cer`. Es lo que revisa `FirmanteAwsKms.__init__`.
2. Sellar con `FirmanteAwsKms` y comparar con `FirmanteLocal`. **Hecho cuando:** los sellos son idénticos byte por byte.
3. Timbrar ese XML en el ambiente de pruebas del proveedor elegido en D2 (Prodigia). **Hecho cuando:** devuelve el timbre fiscal digital. Es el "Hecho cuando" de la fase 1.
4. Medir la latencia de `Sign` desde Railway y el costo por firma (alrededor de 0.15 USD por cada 10,000 firmas más 1 USD por llave al mes, según la investigación).
5. Repasar la operación: IAM mínima (`kms:Sign` y `kms:GetPublicKey`, con la importación en otra identidad), registro en CloudTrail de cada `Sign` cruzado con la bitácora de sellos, qué pasa al vencer el CSD (expiración del material o `ScheduleKeyDeletion`) y la renovación como llave nueva.
6. Si el proveedor pide la solicitud de cancelación firmada con el CSD (XML-DSig), comprobar que sale con el mismo `Firmante`.
