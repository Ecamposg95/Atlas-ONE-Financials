# Contrato de eventos entre sistemas · v1

_Atlas ONE Financials · 2026-11-25 · Estado: **propuesta de diseño**. Nada de esto está construido: no existe el endpoint receptor, ni la cola de salida, ni la conexión por empresa. Es la base de la fase 3 (conexión con Atlas ONE) y de la fase 6B (contrato y conexión con RRHH) del megaplan de CFDI (`docs/financials/09_MEGAPLAN_CFDI.md`), y concreta los ADR-010, 011 y 012._

Este contrato define cómo Atlas ONE (punto de venta) y HRFlow (RRHH) le avisan a Financials lo que pasó, y cómo Financials les responde con lo que timbró. Ninguno de los dos sistemas toca certificados ni habla con el SAT: mandan hechos de negocio ya calculados, Financials los valida y, si cuadran, los convierte en operaciones, pólizas y comprobantes.

Los puntos marcados **[contador]** o **[abogado]** necesitan esa revisión antes de construirse. Nada de este documento es asesoría fiscal.

## Contenido

| Archivo | Qué es |
|---|---|
| `v1/comunes.schema.json` | Tipos compartidos: monto, tasa, cantidad, fecha con zona, RFC, claves del SAT, renglón de venta, enlaces, motivo de rechazo |
| `v1/sobre.schema.json` | Sobre común de todo evento |
| `v1/cabeceras.schema.json` | Cabeceras HTTP con la firma |
| `v1/acuse.schema.json` | Respuesta síncrona de quien recibe un evento |
| `v1/pos.venta.registrada.schema.json` | Venta cobrada o a crédito, con renglones, base e impuesto por tasa |
| `v1/pos.venta.cancelada.schema.json` | Venta anulada completa |
| `v1/pos.devolucion.aprobada.schema.json` | Devolución parcial o total con sus propios importes |
| `v1/pos.abono.registrado.schema.json` | Abono a ventas a crédito, repartido por venta |
| `v1/pos.caja.cerrada.schema.json` | Cierre de sesión de caja |
| `v1/pos.factura.solicitada.schema.json` | El cliente pide la factura de un ticket |
| `v1/rrhh.nomina.autorizada.schema.json` | Corrida de nómina autorizada, calculada y clasificada |
| `v1/financials.cfdi.actualizado.schema.json` | Financials avisa al punto de venta el estado de un CFDI |
| `v1/financials.nomina.timbrada.schema.json` | Financials devuelve a RRHH el resultado por recibo |
| `v1/ejemplos/` | Un ejemplo válido por evento, acuses, cabeceras y el vector de prueba de la firma |

Las pruebas están en `tests/test_contratos_eventos.py`: validan cada ejemplo contra su esquema, contienen la **implementación de referencia de las reglas de cuadre** (funciones `cuadre_*`) y prueban que se rechazan montos flotantes, tasas en porcentaje, cuadres rotos y combinaciones inválidas de datos laborales. El receptor, cuando se construya, debe pasar los mismos casos.

## Transporte

- **Hacia Financials:** `POST /api/integrations/{emisor}/events`, con `emisor` ∈ `atlas-one`, `hrflow`. Un evento por petición. Cuerpo JSON en UTF-8.
- **Hacia Atlas ONE:** Financials hace `POST` a la URL configurada en la conexión, con el mismo sobre, las mismas cabeceras y el mismo acuse. Atlas ONE necesita una ruta nueva para recibirlos; su único precedente de servidor a servidor es la llave de canal (`app/core/security/channel_keys.py`).
- **Hacia HRFlow:** su API no está expuesta a internet (sólo la web, detrás de Caddy). Propuesta: HRFlow **consulta** `GET /api/integrations/hrflow/events?despues_de=<id_evento>` firmando la petición, y recibe los eventos `financials.nomina.timbrada` pendientes en orden. Así no se toca el Caddy compartido con Atlas ONE y rmazh. Si después se abre una ruta pública, el cuerpo de los eventos no cambia.

Las respuestas de Financials salen de una cola durable (ADR-012). Este contrato es el "primer consumidor externo real" que el ADR esperaba para construirla.

## Sobre común

Todo evento lleva estos campos; el contenido propio va en `datos`.

| Campo | Regla |
|---|---|
| `id_evento` | UUID que genera el emisor **al crear** el evento y guarda en su cola. Un reintento reenvía el mismo id. |
| `tipo` | `<dominio>.<entidad>.<hecho>`: `pos.venta.registrada`, `rrhh.nomina.autorizada`, `financials.cfdi.actualizado`. |
| `version_esquema` | `"1.0"`. Mayor = carpeta (`v1`); menor = campos opcionales nuevos. |
| `emisor` | `atlas-one`, `hrflow` o `atlas-financials`. |
| `organizacion_origen` | `{id}` de la empresa **en el sistema emisor**, siempre como cadena. HRFlow manda también `slug`. |
| `organizacion_destino` | Sólo en eventos de Financials: la empresa tal como la conoce quien recibe. |
| `ocurrido_en` | Hora local del hecho con desfase numérico (`2026-11-24T13:45:10-06:00`). No se acepta `Z` ni hora sin zona. |
| `zona_horaria` | Zona IANA de la sucursal o la empresa. El receptor verifica que el desfase corresponda a esa zona en ese instante. |
| `clave_idempotencia` | `<emisor>:<organización>:<entidad>:<id>:<hecho>`, por ejemplo `atlas-one:42:venta:3f0c…:registrada`. |
| `causado_por` | En respuestas de Financials: el `id_evento` que las provocó. Obligatorio en `financials.*`. |
| `datos` | Contenido del evento; cada esquema lo cierra con `additionalProperties: false`. |

La firma no va en el cuerpo: va en cabeceras, porque firma el cuerpo crudo.

## Firma y verificación

Cabeceras (`v1/cabeceras.schema.json`):

| Cabecera | Valor |
|---|---|
| `X-Atlas-Event-Id` | Igual a `id_evento` del cuerpo |
| `X-Atlas-Timestamp` | Segundos Unix del momento de **firmar** (no del hecho) |
| `X-Atlas-Key-Id` | Qué secreto de la conexión se usó |
| `X-Atlas-Signature` | `sha256=<hex en minúsculas>` |
| `Content-Type` | `application/json; charset=utf-8` |

**Cómo firma el emisor**

1. Serializa el cuerpo una sola vez y guarda esos bytes exactos.
2. Toma la hora actual en segundos Unix: `ts`.
3. Calcula `HMAC-SHA256(secreto, ts + "." + cuerpo)` y lo escribe en hexadecimal.
4. Envía los bytes del paso 1 sin volver a serializar. En cada reintento repite los pasos 2 y 3 con la hora nueva; el `id_evento` y el cuerpo no cambian.

**Cómo verifica el receptor**, en este orden y antes de leer el JSON:

1. Busca la conexión por `emisor` (de la ruta) y `X-Atlas-Key-Id`. Si no existe o está revocada: 401.
2. Rechaza si `|ahora − ts| > 300` segundos: 401 `fuera_de_ventana`.
3. Recalcula la firma sobre `ts + "." + cuerpo crudo` y compara en tiempo constante (`hmac.compare_digest`). Si no coincide: 401 `firma_invalida`.
4. Sólo entonces lee el JSON, valida el esquema y comprueba que `X-Atlas-Event-Id == id_evento` y que `organizacion_origen.id` sea la de la conexión. **La empresa de Financials sale de la conexión, nunca del cuerpo** (invariante 4 de `AGENTS.md`).

Firmar la marca de tiempo junto con el cuerpo impide reusar una firma vieja con otra hora; la ventana limita la repetición y la idempotencia cubre lo que quede dentro de la ventana. Es un cambio respecto a `docs/ARCHITECTURE.md` §8, que firmaba sólo el cuerpo.

**Rotación:** cada conexión admite dos secretos vigentes a la vez, identificados por `X-Atlas-Key-Id`. Se da de alta el nuevo, el emisor empieza a usarlo y luego se revoca el viejo. El secreto se muestra una sola vez al darlo de alta. A diferencia de las llaves de agente, no basta con guardar su hash: verificar un HMAC exige el secreto en claro, así que se guarda cifrado y nunca aparece en logs ni respuestas.

**Vector de prueba:** `v1/ejemplos/firma.vector.json` trae un secreto público, una marca de tiempo, un cuerpo y la firma esperada. Cualquier implementación (Python en Financials, Python en Atlas ONE, TypeScript en HRFlow) debe producir exactamente esa firma.

## Reglas de dinero y cantidades

- **Montos:** cadena con exactamente dos decimales, sin signo, sin separador de miles: `"173.93"`. Nunca número JSON. Cabe en `Numeric(14,2)`. Sólo `diferencia` del cierre de caja admite signo.
- **Tasas:** fracción con cuatro decimales: 16 % es `"0.1600"`. Se rechazan `"16"`, `"16.0000"`, `"0.16"` y `0.16`. IVA sólo admite `0.0000`, `0.0800` y `0.1600`; exento no lleva tasa ni importe. IEPS por cuota queda fuera de v1.
- **Cantidades:** cadena decimal mayor que cero con hasta seis decimales (`"1.250"`). Atlas ONE guarda la cantidad como `Float`: tiene que convertirla a decimal **antes** de calcular importes, no al serializar.
- **Precio unitario:** cadena de dos a seis decimales, sin impuestos.
- **Días pagados de nómina:** cadena con hasta tres decimales (`"15"`, `"5.500"`).

## Reglas de cuadre

**Financials rechaza lo que no cuadra. No redondea, no corrige, no reparte diferencias.** Un evento que no cuadra recibe 422 con el código `cuadre_*` y el emisor tiene que corregir su cálculo. La implementación de referencia son las funciones `cuadre_*` de `tests/test_contratos_eventos.py`.

Notación: `r2(x)` es redondeo a dos decimales con mitad hacia arriba.

### Venta y devolución, por renglón

1. `importe = r2(cantidad × valor_unitario)`.
2. `descuento ≤ importe`.
3. En cada impuesto, `base = importe − descuento`.
4. Con `tipo_factor = Tasa`, el `importe` del impuesto debe caer en el intervalo del Anexo 20 con dos decimales: desde `(base − 0.005) × tasa` truncado hasta `(base + 0.005 − 10⁻¹²) × tasa` redondeado hacia arriba. Para base 46.50 al 16 % eso es 7.43 a 7.45.
5. `total = importe − descuento + Σ importes de impuestos`.
6. `objeto_impuesto = "02"` exige al menos un impuesto; cualquier otro valor exige la lista vacía (esquema).
7. Cada combinación impuesto + tipo de factor + tasa aparece una sola vez por renglón.

### Venta y devolución, por documento

1. `subtotal = Σ importe`; `descuento = Σ descuento`.
2. `totales.impuestos` tiene una entrada por combinación impuesto + tipo de factor + tasa, y su base e importe son **la suma exacta** de los renglones (no se recalculan sobre la base total).
3. `total = subtotal − descuento + Σ importes de impuestos`, y además `total = Σ total de renglones`.

Con esto desaparece el centavo de diferencia de Atlas ONE: el documento ya no se calcula aparte, es la suma de sus renglones.

### Pagos

- **Venta:** `Σ pagos = total + propina + recargo_tarjeta − saldo_pendiente`. En contado `saldo_pendiente = "0.00"` y hay al menos un pago; en crédito hay cliente. Los pagos van netos de cambio.
- **Devolución:** `Σ reembolsos = total` de la devolución. Financials además verifica contra lo que ya recibió que la cantidad devuelta de cada renglón no supere lo vendido menos lo ya devuelto.
- **Abono:** `Σ aplicaciones.importe = pago.importe`; en cada aplicación `saldo_insoluto = saldo_anterior − importe` e `importe ≤ saldo_anterior`. Financials compara `saldo_anterior` contra su cartera.
- **Cancelación:** `total_cancelado` es igual al total de la venta registrada.
- **Factura solicitada:** `total_ticket` es igual al total de la venta menos lo devuelto.

### Cierre de caja

1. `Σ cobros_por_metodo = total_cobrado`, un renglón por método.
2. `efectivo.cobros` es el renglón `CASH`.
3. `esperado = fondo_inicial + cobros + entradas − salidas − reembolsos`.
4. `diferencia = contado − esperado` (negativa = faltante).
5. Financials compara `numero_ventas` con las ventas que recibió de esa sesión; si faltan, el cierre queda `en_espera` (ver Orden).

### Nómina, por recibo

1. `total_gravado = Σ importe_gravado`; `total_exento = Σ importe_exento`; `total_percepciones = total_gravado + total_exento`.
2. `total_impuestos_retenidos = Σ deducciones con tipo 002`; `total_otras_deducciones` = el resto; `total_deducciones` = ambas.
3. `total_otros_pagos = Σ otros pagos`.
4. `neto = total_percepciones + total_otros_pagos − total_deducciones`, nunca negativo: si las deducciones superan, RRHH lo resuelve antes de autorizar.
5. Hay percepciones u otros pagos con importe.
6. No se retiene ISR si todo es exento.
7. En otro pago 002 (subsidio), `subsidio_causado ≥ importe`.
8. Reglas de forma (esquema): con `registro_patronal` son obligatorios `num_seguridad_social`, `fecha_inicio_rel_laboral`, `antiguedad`, `riesgo_puesto` y `salario_diario_integrado`; sin él no debe ir ninguno. Contrato 01 a 08 exige registro patronal y régimen 02, 03 o 04; contrato 09 en adelante, cualquier otro régimen. Percepción 019 exige `horas_extra`. CLABE de 18 posiciones va sin `banco`; cuenta de 10, 11 o 16, con `banco`. Ordinaria no usa periodicidad 99; extraordinaria sí.

### Nómina, por corrida

1. `numero_recibos` = recibos en el evento; ids de recibo y de empleado sin repetir.
2. Los cuatro totales de la corrida son la suma de los recibos **de ese evento**.
3. `fecha_inicial_pago ≤ fecha_final_pago`; ninguna relación laboral empieza después del periodo.

Financials **no recalcula** ISR, IMSS, subsidio ni exenciones: valida que lo que viene sea coherente consigo mismo. Que los importes sean correctos es responsabilidad de RRHH **[contador]**.

## Mapeo de identificadores

| Dato | Atlas ONE | HRFlow | Financials | Regla |
|---|---|---|---|---|
| Empresa | Entero (`organization.id`) | `Empresa.id` (cuid) y `slug` | UUID | Una conexión por empresa y emisor guarda el par. El evento lleva el id del origen como cadena; Financials resuelve su UUID desde la conexión autenticada |
| Sucursal | Entero (`branches.id`) | `Sucursal.id` (cuid) | No existe | Viaja con nombre, código postal y zona. Commerce es dueño de la sucursal (ADR-010); Financials guarda el código postal para agrupar la factura global |
| Cliente | Entero | — | UUID | Referencia externa `atlas-one:<org>:<cliente>` en el contacto (ADR-010) |
| Venta | UUID (`sales_documents.id`) | — | Operación con origen | `venta.id_origen`; el folio del ticket (`<sucursal>-<serie>-<folio>`, hasta 100 caracteres) es el `NoIdentificacion` de la global |
| Renglón | Posición | — | Concepto | `numero`; las devoluciones lo referencian |
| Empleado | — | cuid de 25 caracteres | No se guarda como maestro | Referencia `hrflow:<empresa>:<empleado>`; `num_empleado` del recibo sale del código corto (1 a 15 caracteres), nunca del cuid |
| Corrida | — | No existe hoy; debe crearse | Lote de recibos | `corrida.id_origen` + `version` |
| Recibo | — | No existe hoy | CFDI tipo N | `id_recibo_origen`; sustitución con `sustituye` |
| CFDI | Campo nuevo en la venta | Campo nuevo en el recibo | Documento fiscal | Financials es dueño del UUID; los demás guardan copia |

Si una empresa del punto de venta o de RRHH factura bajo más de una razón social, ADR-007 obliga a separarla en varias organizaciones de Financials y el mapeo deja de ser uno a uno: v1 no lo soporta.

## Idempotencia

- La clave es `clave_idempotencia`, única por emisor y organización, con restricción única en la tabla de eventos entrantes (ADR-011). No se usa `source_type`/`source_id` de las pólizas, que se repiten por diseño.
- **Mismo `id_evento`** (reintento): responde 200 `duplicado` con el acuse original.
- **Distinto `id_evento`, misma clave, mismo contenido de `datos`**: 200 `duplicado` con `id_evento_original`. Se compara un hash del cuerpo de `datos` normalizado.
- **Misma clave, contenido distinto**: 422 `clave_reutilizada`. Un hecho no cambia; si cambió, es otro hecho con otra clave (por ejemplo, una devolución).
- **Un evento rechazado (422) no consume la clave:** el emisor corrige y vuelve a mandar con la misma clave y un `id_evento` nuevo.
- Financials guarda el evento **antes** de procesarlo. Si una regla contable falla, queda `fallido` y se reprocesa sin que el emisor reenvíe.
- Las respuestas de Financials también traen clave (`atlas-financials:<org>:cfdi:<uuid>:<estado>`); quien las recibe debe deduplicar igual.

## Orden y dependencias

La cola de Atlas ONE entrega en orden de creación, pero con reintentos el orden de llegada no está garantizado. Financials no depende del orden de llegada sino de **dependencias explícitas**:

| Evento | Depende de |
|---|---|
| `pos.venta.cancelada`, `pos.devolucion.aprobada`, `pos.factura.solicitada` | `pos.venta.registrada` de esa venta |
| `pos.abono.registrado` | `pos.venta.registrada` de cada venta aplicada |
| `pos.caja.cerrada` | Todas las ventas de la sesión (por `numero_ventas`) |
| `rrhh.nomina.autorizada` versión n > 1 | La versión n − 1 de la misma corrida, ya procesada |

Si falta una dependencia, el evento se guarda y se responde 202 `en_espera`. Se procesa en cuanto llega lo que falta. A las 24 horas sin dependencia pasa a rechazado con `dependencia_faltante` y aparece en la conciliación diaria. Una versión de corrida más vieja que la última procesada se rechaza con `version_obsoleta`.

## Reintentos

| Respuesta | Qué hace el emisor |
|---|---|
| 202 `aceptado` o `en_espera` | Marca entregado |
| 200 `duplicado` | Marca entregado |
| 401 | No reintenta en automático; alerta (secreto, reloj o conexión mal configurados). Corrige y reintenta el mismo evento |
| 404 (conexión no configurada) | Reintenta con espera larga (cada hora, hasta 72 h) por si la conexión se está dando de alta |
| 422 `rechazado` | No reintenta el mismo cuerpo. Corrige y emite un `id_evento` nuevo con la misma clave |
| 429, 5xx, tiempo agotado, sin red | Reintenta con el mismo `id_evento`: 1, 5, 25, 125 y 625 segundos; al quinto fallo queda `FALLIDO` y alerta |

Los mismos tiempos aplican a Financials cuando entrega a Atlas ONE. La cola de Atlas ONE ya hace 5 intentos con espera base de 30 s (`app/core/outbox.py`); basta con apuntarla a un despachador HTTP. Además, una conciliación diaria por rango de fechas compara ventas del punto de venta, documentos fiscales y libro, y recupera lo que se haya perdido.

## Respuestas de Financials

Hay dos niveles y no deben confundirse:

1. **Acuse síncrono** (`v1/acuse.schema.json`): dice si el evento se guardó. `aceptado` no significa timbrado.
2. **Eventos de resultado**, asíncronos:
   - `financials.cfdi.actualizado`: uno por cambio de estado de un comprobante (`timbrado`, `rechazado`, `cancelacion_en_proceso`, `cancelado`, `cancelacion_rechazada`). Lleva UUID, serie, folio, total, enlaces firmados a XML y PDF con caducidad, y motivo de rechazo en español. Cuando es una factura global lleva `ventas_cubiertas` para que el punto de venta no permita facturar esos tickets dos veces.
   - `financials.nomina.timbrada`: resultado por recibo de una versión de corrida. Un rechazo se corrige enviando una versión nueva con `alcance: "correccion"` y sólo ese recibo; el lote no se repite.

Los enlaces caducan: quien recibe descarga y guarda su copia. Financials conserva el XML cinco años.

Quien consume eventos de Financials debe **ignorar campos que no conoce**; Financials, como receptor, es estricto y rechaza campos desconocidos para detectar errores de captura como `subtotl`.

### Códigos de rechazo

Los mensajes van en español y en lenguaje de empresario. `reintentable: true` significa que Financials lo reintentará solo.

| Código | Cuándo |
|---|---|
| `firma_invalida`, `fuera_de_ventana`, `conexion_no_configurada` | Autenticación (401/404) |
| `esquema_invalido` | No cumple el JSON Schema; `ruta` señala el campo |
| `version_no_soportada` | `version_esquema` mayor que la que conoce Financials |
| `cuadre_renglon`, `cuadre_documento`, `cuadre_pagos`, `cuadre_recibo`, `cuadre_corrida`, `cuadre_caja` | Reglas de cuadre |
| `zona_inconsistente` | El desfase de `ocurrido_en` no corresponde a `zona_horaria` |
| `clave_reutilizada` | Misma clave de idempotencia con otro contenido |
| `dependencia_faltante`, `version_obsoleta` | Orden |
| `venta_ya_facturada`, `devolucion_excede_venta`, `saldo_no_coincide` | Contra el estado que ya tiene Financials |
| `receptor_rfc_no_inscrito`, `receptor_datos_no_coinciden`, `rechazo_proveedor` | Validación contra el padrón o respuesta del proveedor de timbrado (en eventos de resultado) |

## Versionado

- La versión mayor es la carpeta (`v1/`). Un cambio incompatible (quitar un campo, cambiar su significado, volver obligatorio uno opcional) crea `v2/` y ambas conviven mientras haya emisores en `v1`.
- La versión menor (`1.1`, `1.2`) sólo agrega campos **opcionales**. Como Financials rechaza campos desconocidos, **Financials publica primero** el esquema nuevo y después los emisores lo usan.
- Un evento con `version_esquema` mayor a la conocida se rechaza con `version_no_soportada`; no se adivina.
- Los catálogos del SAT no están en los esquemas (salvo patrones de forma): se cargan como datos versionados con vigencia y se validan en el receptor.

## Incompatibilidades resueltas

| Tema | Atlas ONE | HRFlow | Financials | Cómo lo resuelve el contrato |
|---|---|---|---|---|
| Identificador de empresa | Entero | cuid + slug | UUID | Cadena con el id del origen; la conexión guarda el mapeo; HRFlow manda ambos |
| Identificador de cliente | Entero | — | UUID | Referencia externa por origen en el contacto |
| Identificador de empleado | — | cuid de 25 caracteres | No guarda empleados | Referencia externa; `num_empleado` del código corto |
| Corrida de nómina | — | No existe; reaprobar sobrescribe | Necesita algo inmutable | `corrida.id_origen` + `version`; la corrida autorizada no cambia, la corrección es versión nueva |
| Tasa de impuesto | Porcentaje (16.0) | Fracción en `Float` | Fracción (0.1600) | Fracción con cuatro decimales en cadena; el evento de nómina no manda tasas sino importes |
| Cantidad | `Float` | Días como entero | Sin renglones | Cadena decimal; días con hasta tres decimales |
| Dinero | `Numeric(10,2)` | `Decimal` en base, flotante en cálculo y API | `Numeric(14,2)` | Cadenas con dos decimales; HRFlow deja de calcular en flotante antes de emitir |
| Cuadre | Subtotal + impuesto puede diferir un centavo del total | Redondeo por empleado sobre flotante | Deriva el impuesto del total | Base e impuesto por renglón; el documento es la suma exacta de renglones; Financials rechaza lo que no cuadre |
| IVA en ventas sin factura | Cero si no se pidió factura | — | Lo necesita para la global | Toda venta viaja con su IVA calculado, pida factura o no (trabajo en Atlas ONE) |
| Claves del SAT | No existen | No existen | Las necesita para timbrar | Obligatorias por renglón y por concepto de nómina (trabajo en ambos orígenes) |
| Formas de pago | `CASH/CARD/TRANSFER/OTHER` | Sin forma de pago | Catálogo del SAT | Viaja el método de origen y, si se sabe, `forma_pago_sat`; si falta, la conexión tiene un mapeo configurable. `CARD` sin distinguir es decisión pendiente |
| Devolución | Reescribe la venta original | — | Reverso por póliza espejo | Evento propio con sus importes; la venta registrada nunca se modifica |
| Abono a cuenta global | Admite abono sin venta | — | Cartera por documento | El evento exige el reparto por venta |
| Fechas | UTC | Medianoche UTC; fecha de pago = clic | Fecha de negocio por zona | Hora local con desfase y zona IANA; fechas de nómina como fecha de calendario; fecha de pago real |
| Propina y recargo de tarjeta | Columnas aparte; el recargo fuera del total | — | Sin cuenta ni regla | Campos propios fuera de `total`; tratamiento **[contador]** |
| Incentivo de puntualidad | — | Fuera de la nómina | La póliza debe cuadrar con los recibos | Si el contador decide que va al recibo, viaja como percepción (010 en el ejemplo) **[contador]** |
| Errores de API | — | `{"error": …}` | `{"detail": …}` | El acuse lleva `detail` y `errores` estructurados |
| Red | VPS IONOS | API no expuesta | Railway, dominio público | Ida por HTTPS; vuelta a HRFlow por consulta |

## Decisiones de diseño a revisar

Para el founder:

1. **Toda venta viaja a Financials**, no sólo las facturadas. Es lo que permite la factura global y la póliza de ventas, pero multiplica el volumen (del orden de 60 ventas diarias por tienda) y obliga a Atlas ONE a calcular IVA siempre.
2. **Firmar `marca de tiempo + "." + cuerpo`** y agregar `X-Atlas-Key-Id`, en vez de firmar sólo el cuerpo como decía `docs/ARCHITECTURE.md` §8.
3. **Hora local obligatoria** (`-06:00`), sin aceptar `Z`. Obliga a Atlas ONE a dejar de mandar UTC en los eventos.
4. **Financials rechaza, no corrige.** Un centavo de diferencia es un 422. Es más estricto que hoy, pero evita que cada sistema tenga su versión de la cifra.
5. **Abono repartido por el punto de venta.** Atlas ONE tendría que repartir el abono a cuenta global antes de emitir (por ejemplo, a la venta más antigua).
6. **La vuelta a HRFlow por consulta** en vez de ruta pública.
7. **Corrección de nómina por versión** con sólo los recibos que cambian, y sustitución de recibos timbrados con `sustituye`.
8. **Receptor estricto** (`additionalProperties: false`) y orden de despliegue "Financials primero".
9. **Datos personales en el evento de nómina:** RFC, CURP, NSS y salario viajan porque el recibo los contiene; la cuenta bancaria es opcional y se recomienda no mandarla.

Dependen del contador **[contador]**:

- Si la propina cobrada con tarjeta es ingreso de la empresa o del trabajador, y a qué cuenta va.
- Si el recargo por pagar con tarjeta es parte del precio (y lleva IVA) o un concepto aparte.
- Mapeo por defecto de `CARD` (04 crédito o 28 débito) y de `OTHER`, y confirmar las claves del catálogo `c_FormaPago` vigente.
- Ticket que ya entró a una global y luego pide factura (D5 del megaplan): define qué emite Financials al recibir `pos.factura.solicitada` de una venta ya cubierta.
- Si el incentivo de puntualidad va al recibo y con qué clave.
- Las claves de percepción y deducción del ejemplo (001, 010, 046; 001, 002) son ilustrativas; los importes no son un cálculo fiscal.
- Pólizas de nómina: provisión, retenciones, cuotas patronales y pago.

Dependen del abogado **[abogado]**: base legal y aviso de privacidad para transmitir RFC, CURP, NSS y salario de HRFlow a Financials (D6 del megaplan).

## Lo que el contrato no cubre en v1

- Ventas en moneda extranjera, IEPS por cuota, retenciones en ventas (no pueden ir a la global), ventas por cuenta de terceros, anticipos.
- Nómina con varios complementos en un CFDI, separación e indemnización, jubilación y subcontratación (los nodos existen en el SAT; se agregan en una versión menor cuando RRHH los calcule).
- El punto de venta anterior (`Atlas-Rmazh`): no tiene cola durable (D4).
- Cómo calcula RRHH la nómina: eso es la fase 6A.
