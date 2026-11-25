# Spike: sellar un CFDI 4.0 con un firmante externo

Prueba de concepto para la decisión **D1** del megaplan de CFDI (`docs/financials/09_MEGAPLAN_CFDI.md`): ¿podemos sellar sin que la llave del certificado de sello digital (CSD) esté en nuestro proceso, delegando la firma a un servicio de llaves como AWS KMS o Google Cloud KMS?

Nada de esto es código de producción ni vive en `app/`. Timbra y cancela sólo en los **ambientes de pruebas** de Formas Digitales y Solución Factible, con las credenciales de prueba que ellos publican; nunca en producción.

## Timbrado y cancelación en ambientes de pruebas (criterios 3 y 4 del ADR-017)

Corrido el 2026-11-25 con el CSD de prueba `EKU9003173C9`, sellado por `FirmanteLocal` a través del `Firmante` y cancelado con una solicitud que firmamos nosotros (`cancelacion.py`). Ningún proveedor recibió la llave, el `.key` ni un PFX.

### Respuesta corta

- **Criterio 3 (aceptación del proveedor): pasa en los dos.** Los dos timbraron el XML sellado por el `Firmante` sin tocar el sello (se volvió a verificar el sello en el XML timbrado).
- **Criterio 4 (cancelación con solicitud firmada por nosotros): pasa en los dos con RSA-SHA1; con RSA-SHA256 pasa en Formas Digitales y falla en Solución Factible.**
- **¿SHA-1 es obligatorio? Para el SAT, no.** El servicio de cancelación del SAT de pruebas, al que Formas Digitales reenvía la solicitud, aceptó solicitudes firmadas con `rsa-sha256` (respuesta 201) y rechazó las mismas con la firma alterada (302). O sea, verifica la firma SHA-256 de verdad; no la ignora. **Para Solución Factible, sí:** su propio verificador, que corre antes de mandar nada al SAT, rechaza `rsa-sha256` con 1801 "cannot find validation key" y acepta `rsa-sha1`.
- **Consecuencia para D1: AWS KMS sirve para cancelar**, siempre que el proveedor reenvíe la firma tal cual, como Formas Digitales. Con un proveedor que, como Solución Factible, sólo acepte SHA-1, el modo A necesitaría Google Cloud KMS en modo PKCS#1 sin resumen o caer al modo B. **Prodigia (el primario) no se probó**: su ambiente pide registro. Probar su `XML_CANCELACION` con SHA-256 es lo primero cuando haya cuenta.

### Qué aceptó cada ambiente

| | Formas Digitales | Solución Factible |
|---|---|---|
| Credenciales de prueba | Publicadas en https://forsedi.facturacfdi.mx/developers/webservice/timbrado/soap, recuadro "Datos de acceso (Pruebas)" (también en las páginas de cancelación). Variables `FD_USUARIO` y `FD_CONTRASENA` | Publicadas en https://www.solucionfactible.com/sfic/capitulos/timbrado/ws-timbrado.jsp, "Las credenciales que pueden ser usadas para conectarse al Webservice de prueba". Variables `SF_USUARIO` y `SF_CONTRASENA` |
| Timbrar (XML sellado por nosotros) | Sí. SOAP `TimbrarCFDI` en `dev33.facturacfdi.mx`. El timbre sale con `RfcProvCertif="SPR190613I52"` y `NoCertificadoSAT="30001000000500003456"`: pasa por la infraestructura de pruebas del SAT | Sí. SOAP `Timbrado.timbrar` en `testing.solucionfactible.com`. El timbre sale con `RfcProvCertif="SFE0807172W7"` y los mensajes dicen "[Servidor de pruebas]": es su propio simulador, no llega al SAT (el SAT de pruebas no encuentra esos UUID) |
| Reenviar el mismo XML sellado | Devuelve el mismo UUID, sin código ni aviso | Código 307 con el timbre original |
| Cancelar con firma RSA-SHA1 | **201**, "Solicitud de cancelación aceptada por el SAT", con acuse firmado por el SAT | **211**, "en proceso" |
| Cancelar con firma RSA-SHA256 | **201**, igual que SHA-1 | **1801**, "La solictud de cancelación no es válida. cannot find validation key" |
| Firma alterada (control negativo, SHA-1 y SHA-256) | 302, "Sello mal formado o inválido", en el acuse del SAT | SHA-1: 1802, "no ha pasado la verificación criptográfica". SHA-256: 1801, sin llegar a verificar |
| Consultar estatus | `ConsultarEstatusCFDI_2`: Vigente, cancelable sin aceptación, y "En proceso" tras cancelar | No publica una consulta general; el adaptador la delega |
| Tiempo por llamada (unas 15 llamadas a cada operación en FD y 10 en SF, desde esta máquina) | Timbrar 0.3 a 2.7 s, casi siempre bajo 1 s. Cancelar 1.4 a 3.3 s. Estatus 0.4 a 0.9 s | Timbrar 0.44 a 0.55 s. Cancelar 0.42 a 0.92 s |

El SAT de pruebas tarda en conocer un UUID recién timbrado. En Formas Digitales, durante ese tiempo, la cancelación responde **205** ("Folio Fiscal No existe") y el estatus "No Encontrado". Se observaron de 30 segundos a unos 8 minutos. Una vez aceptada (201), el estatus siguió en "En proceso" al menos 8 minutos; el desenlace final no se vio en esta corrida.

Corrección a `pac_fase0.md`: en Formas Digitales `dev33.facturacfdi.mx` es sólo el ambiente de pruebas de timbrado; producción es `v33.facturacfdi.mx`. La cancelación de pruebas vive en `dev-cancelacion.facturacfdi.mx`.

### Errores vistos y qué significan

| Proveedor | Código | Mensaje | Significado |
|---|---|---|---|
| FD | `CFDI40147` | DomicilioFiscalReceptor … lista de RFC inscritos | El receptor de prueba `URE180429TM6`/`86991` no está en su lista. Con `EWE1709045U0`/`44960`, que usan sus ejemplos, sí timbra |
| FD | `CFDI40102` | La digestión debe ser igual a la desencripción del sello | Sello que no corresponde a la cadena (se probó alterando el sello) |
| FD | `401` | Rango de la fecha de generación mayor a 72 horas | Comprobante fechado hace más de 72 horas |
| FD | `CFDI40999` | Usuario o contraseña incorrecto | Credenciales |
| FD, cancelación | `302` | Sello mal formado o inválido | La firma de la solicitud no verifica en el SAT. Lo vimos por dos causas reales, ya corregidas (abajo), y en los controles negativos |
| FD, cancelación | `205` | Folio Fiscal No existe | El SAT de pruebas aún no conoce el UUID: reintentar más tarde, no es un rechazo definitivo |
| FD, cancelación | `202` | Folio Fiscal previamente cancelado | Reintento de una cancelación ya aceptada |
| SF | `307` | El CFDI ya ha sido registrado | Reenvío del mismo XML; devuelve el timbre original |
| SF, cancelación | `211` | Se encuentra en proceso | Aceptada; el desenlace se consulta después |
| SF, cancelación | `1801` | cannot find validation key | Su verificador no acepta `rsa-sha256`. El texto es el de la API estándar de firmas XML de Java cuando el selector de llave no reconoce el algoritmo **(inferencia, no confirmado con ellos)** |
| SF, cancelación | `1802` | No ha pasado la verificación criptográfica | Firma inválida |

### Dos causas de firma inválida que encontramos y que el módulo real debe cuidar

1. **Formas Digitales no recibe el XML de la solicitud: recibe sus campos y lo rearma.** Lo rearma siempre con `FolioSustitucion=""`, aunque el motivo no sea 01. Si firmamos sin ese atributo, el resumen no coincide y el SAT responde 302. Se descubrió reproduciendo **byte a byte** la firma de su ejemplo público de `Cancelacion40_2` (está como prueba). `armar_solicitud(..., folio_sustitucion_vacio=True)` lo resuelve. Su ejemplo codifica `X509Certificate` dos veces en base64; probamos las dos formas y las dos funcionan.
2. **La canonicalización de lxml 6.1.3 con libxml2 2.14.6 está rota para subárboles:** al canonicalizar `SignedInfo` dentro del documento, los nietos salen con `xmlns=""`, el `SignedInfo` firmado no es el que verifica el SAT y la respuesta es 302. `satcfdi` no lo sufre porque canonicaliza `SignedInfo` como documento aparte. `cancelacion.c14n()` hace lo mismo y hay una prueba de regresión con un XML mínimo.

### Cómo se cancela sin entregar la llave

`armar_solicitud` arma el `Cancelacion` del SAT (`http://cancelacfd.sat.gob.mx`) con la misma firma XML-DSig que `satcfdi` (C14N inclusiva, *enveloped*, `Reference URI=""`, `X509IssuerSerial` y certificado). Con SHA-1 da exactamente la misma firma que `satcfdi`; con SHA-256 cambia `SignatureMethod` a `xmldsig-more#rsa-sha256` y `DigestMethod` a `xmlenc#sha256`. La firma va por el `Firmante`: SHA-256 con `firmar()` (lo que hace KMS) y SHA-1 con `firmar_sha1()`, que sólo tiene `FirmanteLocal`. Con `FirmanteAwsKms`, pedir SHA-1 lanza `AlgoritmoNoSoportado`. La solicitud firmada por el KMS simulado es idéntica a la firmada con la llave local.

## Resultado del sellado

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
.venv/bin/python -m pytest -v                # 49 pruebas sin red (2 más se saltan)

# Contra los ambientes de pruebas (llama a la red; FD tarda hasta unos minutos):
SPIKE_SANDBOX=1 FD_USUARIO=… FD_CONTRASENA=… SF_USUARIO=… SF_CONTRASENA=… \
  .venv/bin/python -m pytest tests/test_sandbox.py -v -s
```

Las credenciales de prueba no están en el repo: se copian de las páginas de cada proveedor citadas arriba. Las respuestas grabadas en `tests/grabadas/` son respuestas reales del 2026-11-25, sin credenciales (una prueba lo revisa).

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
- `cancelacion.py`: `armar_solicitud` (SHA-1 o SHA-256 por el `Firmante`), `verificar_solicitud` y `c14n` (evita el error de libxml2).
- `proveedor_timbrado.py`: la interfaz `ProveedorTimbrado` del ADR-018 (`timbrar`, `cancelar`, `consultar_estatus`), los resultados y un transporte HTTP inyectable. Sin red o con timeout, timbrar devuelve `INDETERMINADO`.
- `pac_formas_digitales.py` y `pac_solucion_factible.py`: adaptadores SOAP, sólo con URL de pruebas. Ninguno de los dos recibe un identificador idempotente; el doble timbrado lo evitan por contenido (ver la tabla).
- `tests/test_cancelacion.py`: la firma SHA-1 es idéntica a la de `satcfdi` y a la del ejemplo público de Formas Digitales; SHA-256 verifica; KMS simulado firma SHA-256 igual que la llave local y no puede SHA-1; regresión de la canonicalización.
- `tests/test_proveedores.py`: los adaptadores contra las respuestas grabadas, cómo desarma la solicitud el adaptador de Formas Digitales y que las grabadas no traigan credenciales.
- `tests/test_sandbox.py`: el recorrido completo contra los dos ambientes de pruebas, sólo con `SPIKE_SANDBOX=1`.

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
- Se timbró y canceló sólo en ambientes de pruebas. Que el SAT de pruebas acepte RSA-SHA256 en la cancelación no prueba que el de producción lo haga; es lo más probable, pero queda **sin verificar** hasta la primera cancelación real.
- El ambiente de Solución Factible es un simulador propio: su 211 no dice nada del SAT. Lo que sí dice es cómo valida la firma antes de enviarla.
- El receptor de `comprobante_de_prueba` (`URE180429TM6`/`86991`) no está en la lista del ambiente de Formas Digitales; las pruebas contra los ambientes usan `EWE1709045U0`/`44960`, tomado de sus ejemplos.
- No se probó el motivo 01 con folio sustituto, ni cancelaciones con aceptación del receptor, ni varias solicitudes por petición.
- Sólo se probó una factura de ingreso sin complementos. Pagos 2.0 y nómina 1.2 usan otras XSLT incluidas, que se bajan pero no se prueban.
- El arranque del venv sin `ensurepip` es una peculiaridad de esta máquina.

## Qué falta probar con un KMS real para cerrar D1

1. Hacer los pasos 2 a 4 con el CSD de prueba `EKU9003173C9` en una cuenta de AWS (o GCP) de pruebas. **Hecho cuando:** `ImportKeyMaterial` responde bien y `GetPublicKey` coincide con el `.cer`. Es lo que revisa `FirmanteAwsKms.__init__`.
2. Sellar con `FirmanteAwsKms` y comparar con `FirmanteLocal`. **Hecho cuando:** los sellos son idénticos byte por byte.
3. Timbrar ese XML en el ambiente de pruebas del proveedor elegido en D2 (Prodigia). **Hecho cuando:** devuelve el timbre fiscal digital. Es el "Hecho cuando" de la fase 1. **Hecho en Formas Digitales y Solución Factible con `FirmanteLocal`;** falta Prodigia (su ambiente pide registro) y repetirlo con el sello de un KMS real.
4. Medir la latencia de `Sign` desde Railway y el costo por firma (alrededor de 0.15 USD por cada 10,000 firmas más 1 USD por llave al mes, según la investigación).
5. Repasar la operación: IAM mínima (`kms:Sign` y `kms:GetPublicKey`, con la importación en otra identidad), registro en CloudTrail de cada `Sign` cruzado con la bitácora de sellos, qué pasa al vencer el CSD (expiración del material o `ScheduleKeyDeletion`) y la renovación como llave nueva.
6. ~~Si el proveedor pide la solicitud de cancelación firmada con el CSD (XML-DSig), comprobar que sale con el mismo `Firmante`.~~ **Hecho:** sale con el mismo `Firmante`, y Formas Digitales y el SAT de pruebas aceptan RSA-SHA256. Falta: confirmar que Prodigia (`XML_CANCELACION`) reenvía la firma SHA-256 sin rechazarla como Solución Factible, y preguntar por escrito a cada proveedor qué algoritmo aceptan (ya está en el borrador de correo de la fase 0).
7. Ver el desenlace de una cancelación aceptada: el estatus pasó a "En proceso" y no se esperó a "Cancelado".
