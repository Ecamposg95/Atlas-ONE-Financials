# ADR-017 — Custodia de la llave del certificado de sello digital

**Fecha:** 2026-11-25 · **Estado:** aceptada (decisión D1 del founder, `docs/financials/09_MEGAPLAN_CFDI.md`)

> Numeración: 009 a 016 están reservados para las propuestas de `docs/financials/08_ARCHITECTURE_DECISIONS.md`. Este ADR es el "ADR nuevo de custodia de llaves" que pide la fase 0 del megaplan y toma el siguiente número libre.
>
> Nada de esto está construido. Este ADR fija el diseño y la prueba que lo cierra; no afirma cumplimiento normativo. Lo marcado **(sin verificar)** sale de conocimiento general o de fuentes secundarias y debe confirmarse en la fase 1.

## Contexto

- Para timbrar, Financials sellará cada CFDI con el certificado de sello digital (CSD) de la empresa cliente: SHA-256 sobre la cadena original, firmado con su llave privada RSA de 2048 bits (Anexo 20). El proveedor de timbrado sólo recibe el XML ya sellado (ADR-018).
- Con un CSD robado (llave y contraseña) un tercero puede emitir y cancelar comprobantes a nombre del cliente. El CFF (art. 17-J) obliga al titular a actuar con diligencia, a pedir la revocación ante cualquier riesgo, y lo hace responsable de no hacerlo a tiempo. Sólo el cliente puede revocar el certificado, porque se hace con su e.firma.
- La e.firma equivale a la firma autógrafa y permite generar CSD nuevos. El timbrado no la necesita.
- OWASP pide llaves nunca en claro en reposo, la llave que cifra separada de los datos, y desaconseja guardar llaves en variables de entorno.
- Railway ofrece variables selladas, pero su documentación no describe servicio de llaves, cifrado en reposo, rotación ni bitácora de acceso a secretos.
- `docs/ARCHITECTURE.md` proponía cifrar con Fernet y una llave maestra en variable de entorno (`FISCAL_MASTER_KEY`). Ese plan queda por debajo de OWASP y este ADR lo sustituye.
- ADR-013 (propuesta) prohíbe guardar certificados o llaves hasta tener un diseño aprobado de cifrado, rotación y permisos. Este ADR es ese diseño.
- Ninguna empresa ha probado de punta a punta firmar un CFDI con una llave del SAT importada a un servicio de llaves en la nube. Lo que sí está documentado: AWS KMS importa llaves RSA 2048 en PKCS#8 DER y firma con PKCS#1 v1.5 y SHA-256; Google Cloud KMS lista el algoritmo `RSA_SIGN_PKCS1_2048_SHA256` e importa en PKCS#8 DER.

Fuentes: `research_notes/Timbrado CFDI y conexión Atlas/seguridad_csd_y_legal.md` (secciones 1 a 6 y 9) y `reports/Timbrado CFDI y conexión Atlas.md` (carpetas locales, fuera de git).

## Decisión

**Financials custodia la llave del CSD de cada empresa en un servicio de llaves externo a Railway.** Primer candidato: AWS KMS; Google Cloud KMS es equivalente funcional. El proveedor de timbrado nunca recibe la llave.

### Modo A, preferido: la llave firma dentro del servicio y nunca sale

1. Al dar de alta el certificado, el `.key` se descifra con la contraseña del cliente sólo en memoria, se convierte a PKCS#8 DER sin cifrar, se envuelve con la llave pública de importación del servicio y se importa como llave asimétrica no exportable, una por certificado.
2. La contraseña y el material local se descartan en ese momento. Financials no vuelve a necesitarlos.
3. Para sellar, Financials calcula el SHA-256 de la cadena original y pide la firma al servicio (en AWS, `Sign` con `RSASSA_PKCS1_V1_5_SHA_256` y tipo de mensaje digest **(sin verificar el nombre exacto en la referencia de la API)**).
4. La fecha de expiración del material importado se fija en la fecha de fin de vigencia del certificado.

### Modo B, respaldo si la prueba de la fase 1 falla: cifrado por sobre

1. Una llave de datos AES-256-GCM por empresa, generada por el servicio y guardada envuelta por la llave maestra, que vive en el servicio y no sale de él.
2. La llave del CSD se guarda en PostgreSQL sólo cifrada con esa llave de datos. Los datos autenticados del cifrado amarran el texto cifrado a `organization_id` y al número de serie del certificado, para que un registro copiado a otra empresa no descifre.
3. Se descifra sólo en memoria, sólo al sellar o firmar una cancelación, y se descarta al terminar la operación. Sin caché, salvo que el volumen lo exija; entonces, caché en memoria con vida corta y documentada.
4. Igual que en el modo A, la contraseña original se descarta al dar de alta.

### Reglas que aplican a los dos modos

- **Nunca** se guarda la llave en claro, ni en PostgreSQL, ni en variables de Railway, ni en logs, ni en el rastreador de errores. Las credenciales del servicio de llaves son lo único que vive en Railway, en variables selladas de producción.
- **Nunca** se pide ni se acepta la e.firma. El alta rechaza cualquier certificado que no sea de sello y lo dice en pantalla. Qué extensión del certificado distingue un CSD de una e.firma está **(sin verificar)**; se resuelve en la fase 1 con certificados de prueba del SAT.
- **Interfaz estrecha.** Un solo módulo de sellado habla con el servicio de llaves y expone dos operaciones: `sellar(organization_id, certificado_id, cadena_original) -> sello` y `firmar_cancelacion(organization_id, certificado_id, solicitud) -> solicitud_firmada`. Ninguna ruta de la API, herramienta de agente ni ruta de soporte devuelve una llave o una contraseña. Cambiar del modo A al B, o al revés, cambia la implementación, no los llamadores.
- **Permisos mínimos.** La credencial del servicio sólo puede firmar (modo A) o descifrar y generar llaves de datos (modo B) sobre las llaves de Financials, con contexto de cifrado por empresa donde el servicio lo permita.
- **Alta del certificado:** sólo OWNER o ADMIN de la organización, con reautenticación en ese momento. Nunca personal de Atlas en nombre del cliente. Se valida que `.cer` y `.key` corresponden, que el RFC del certificado es el de la organización, que es de sello y que está vigente. Se guarda el `.cer` (público), su número de serie, vigencia y huella. Al reemplazar un certificado se avisa a todos los administradores de la organización.
- **Ambientes.** Las variables selladas no se copian a entornos de vista previa. En pruebas y vista previa sólo se usan certificados de prueba del SAT con su propia llave maestra o sus propias llaves.

## Prueba que decide entre el modo A y el modo B (fase 1)

Se hace con un certificado de prueba del SAT, en la cuenta del servicio de llaves que se usará en producción, y en el ambiente de pruebas del proveedor de timbrado elegido. El resultado se agrega a este ADR como anexo con fecha.

| # | Criterio | El modo A pasa si |
|---|---|---|
| 1 | Importación | El `.key` del SAT, convertido a PKCS#8 DER, se importa sin error como llave RSA 2048 de firma |
| 2 | Sello válido | El sello del servicio verifica con la llave pública del `.cer` (OpenSSL y `satcfdi`) y coincide byte a byte con el sello que produce `satcfdi` con la llave local sobre la misma cadena |
| 3 | Aceptación del proveedor | El proveedor de timbrado acepta el XML y lo timbra; no lo rechaza por sello (CFDI40102 ni códigos 302 a 304) |
| 4 | Cancelación | Una solicitud de cancelación firmada con la misma llave es aceptada por el proveedor |
| 5 | Llave ausente | Búsqueda en base, respaldos, variables y logs de la prueba: la llave no aparece en ningún lado |
| 6 | Latencia | Tiempo de firma medido en 100 llamadas; el umbral aceptable se fija antes de correr la prueba, pensando en el lote de nómina |
| 7 | Costo y cuotas | Costo mensual por certificado y cuota de llaves por cuenta compatibles con el número de clientes esperado |

Si fallan 1 a 5, se usa el modo B. Si fallan 6 o 7, se decide entre modo B y modo A con ajustes (lotes, otra región, aumento de cuota). Si el modo A pasa, el modo B no se construye.

## Bitácora

Cada uso del certificado queda en una bitácora de sólo agregar, por organización:

- fecha y hora, organización, usuario o proceso que originó la emisión;
- número de serie del certificado y operación (sello o firma de cancelación);
- documento interno y UUID cuando exista;
- SHA-256 de la cadena original o de la solicitud;
- resultado del proveedor y identificador de la petición al servicio de llaves.

Nunca se registra material de llave ni contraseña. Una conciliación diaria cruza esta bitácora con el registro del servicio de llaves (CloudTrail en AWS): una firma o descifrado sin renglón en la bitácora es alerta de primer nivel.

Alertas: volumen de sellos por organización fuera de su línea base, emisión fuera del horario habitual, ráfagas de cancelaciones, firmas pedidas desde un origen no esperado, certificado por vencer.

Retención: al menos lo mismo que los XML (cinco años desde la declaración relacionada). El plazo final lo fija el abogado (`docs/financials/11_BRIEF_LEGAL_CFDI.md`).

## Rotación y borrado

| Qué | Cuándo | Cómo |
|---|---|---|
| CSD del cliente | Vigencia máxima de cuatro años; antes si el cliente lo renueva o revoca | Avisos a 60, 30 y 7 días del vencimiento; al vencer se bloquea la emisión con mensaje claro. Renovar le toca al cliente, porque requiere su e.firma. El certificado nuevo es una llave nueva; la anterior se desactiva y se programa su borrado |
| Llave maestra (modo B) | Rotación periódica que ofrezca el servicio | Rotación gestionada por el servicio; las llaves de datos se vuelven a envolver **(sin verificar el procedimiento exacto por servicio)** |
| Credencial del servicio de llaves en Railway | Periódica, y al salir alguien con acceso | Rotación manual: crear la nueva, desplegar, revocar la anterior. Railway no ofrece identidad federada documentada hacia AWS o Google **(sin verificar en 2026)**, así que es una credencial estática |
| Material del CSD | Al terminar el contrato, al reemplazar el certificado, al vencer o a petición del cliente | Borrado de la llave importada (modo A) o destrucción de la llave de datos de la empresa (modo B). Esto vuelve inútil también lo que quede en respaldos de PostgreSQL. Se conservan el `.cer` y la bitácora |

No se guarda copia de respaldo recuperable de la llave del CSD: si se pierde, el cliente genera otro certificado.

## Procedimiento ante incidente

Se activa ante sospecha, no sólo ante certeza: acceso no explicado al servicio de llaves, firma sin renglón en la bitácora, fuga de la credencial del servicio, o aviso del cliente.

1. **Contener.** Revocar la credencial del servicio de llaves o deshabilitar las llaves afectadas; pausar la emisión de las organizaciones afectadas. Anotar hora y quién lo hizo.
2. **Delimitar.** Con la bitácora y el registro del servicio, listar certificados, ventana de tiempo y documentos sellados o cancelados en esa ventana.
3. **Avisar al cliente de inmediato**, por el canal pactado en contrato y dentro del plazo que fije el abogado (propuesta de trabajo: no más de 24 horas desde la sospecha razonable). El aviso dice qué pasó, qué certificados están expuestos, qué documentos se emitieron o cancelaron en la ventana, y que debe revocar el certificado en el portal del SAT. Sin este aviso el cliente no puede cumplir el art. 17-J.
4. **Borrar** el material afectado según la tabla anterior. La emisión se reanuda sólo con un certificado nuevo dado de alta por el cliente.
5. **Revisar** con el cliente los comprobantes de la ventana, y cancelar los que él no reconozca.
6. **Cerrar** con un informe: causa, línea de tiempo, alcance y cambios. Evaluar con el abogado si procede aviso a otros titulares o a la autoridad de datos personales.

Este ADR no cubre la restricción del certificado por el SAT (art. 17-H Bis). Ese caso no es un incidente de seguridad: la pantalla lo muestra distinto de un error técnico y pausa la emisión de la organización.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Fernet con llave maestra en variable de entorno (plan de `docs/ARCHITECTURE.md`) | OWASP lo desaconseja; quien vea las variables o comprometa el proceso tiene todas las llaves; sin bitácora de uso de la llave maestra |
| Delegar la custodia al proveedor o a un revendedor (Facturapi, Facturama) | Cambiar de proveedor obliga a pedir otra vez todos los certificados; su documentación pública no describe cómo los guardan; la credencial de su API se vuelve llave de todas las empresas. Ocho proveedores revocados en 2026 hacen de la portabilidad un requisito |
| Módulo de seguridad en hardware dedicado | Miles de dólares al mes; desproporcionado para el tamaño del equipo |
| Vault autoalojado en Railway | La llave de apertura acaba en la misma plataforma; no mejora el modelo de amenaza |
| Gestores de secretos (Doppler, Infisical) | Distribuyen variables; no firman ni cifran por sobre. Pueden servir para rotar la credencial del servicio de llaves, no para custodiar llaves de clientes |

## Consecuencias

- Facturar depende de que el servicio de llaves esté disponible; una caída detiene la emisión, no los datos.
- Costo de referencia en AWS: 1 USD al mes por llave importada más cerca de 0.15 USD por cada 10,000 firmas (sin capa gratuita para llaves asimétricas). Crece en línea con el número de certificados custodiados.
- Una llamada de red por sello. El timbrado de nómina por lote debe medirse en la prueba.
- Un atacante con la credencial del servicio puede pedir firmas mientras la tenga, pero en el modo A no puede llevarse la llave: revocar la credencial termina el incidente. Aun así el aviso al cliente es obligatorio.
- Se agregan a la fase 1: cuenta del servicio, módulo de sellado, alta de certificados, bitácora, conciliación con el registro del servicio, alertas y el procedimiento de incidente probado en simulacro.
- El contrato con el cliente debe recoger la autorización de uso del sello, el aviso de incidentes y el borrado (`docs/financials/11_BRIEF_LEGAL_CFDI.md`).

## Pendiente de verificar

- Formato del `.key` del SAT (PKCS#8 cifrado en DER) y extensión que distingue CSD de e.firma.
- Nombre exacto del algoritmo de firma en la API del servicio elegido, cuotas de llaves y de firmas por segundo.
- Precio vigente de Google Cloud KMS, si se compara.
- Cifrado en reposo y bitácora de variables en Railway; federación de identidad hacia la nube del servicio de llaves.
