# ADR-011 — Eventos entrantes e idempotencia

**Fecha:** 2026-11-25 · **Estado:** propuesta (pendiente de aceptación del founder; redacción formal de la propuesta de `docs/financials/08_ARCHITECTURE_DECISIONS.md`)

> El número 011 viene reservado desde el documento 08. Nada de esto está construido: no existen el endpoint, ni las tablas `inbound_events` o `integration_connections`.

## Contexto

- Atlas ONE (punto de venta) y HRFlow (RRHH) van a pedir documentos fiscales y operaciones a Financials (`docs/financials/09_MEGAPLAN_CFDI.md`, fases 3 y 6). Hoy ningún sistema le envía nada.
- `docs/ARCHITECTURE.md` §8 describe un contrato de webhooks firmados que no está implementado.
- El origen de una póliza (`source_type`, `source_id`) se repite por diseño: una venta puede producir varias pólizas. La idempotencia de eventos necesita su propia llave.
- Atlas ONE tiene una cola durable de salida con reintentos (`app/core/outbox.py` en su repositorio), así que el mismo evento llegará más de una vez. HRFlow no tiene integración saliente.
- Invariantes que no cambian (`AGENTS.md`): la organización sale de una membresía o conexión validada, nunca del cuerpo; nada externo llama a `post_journal_entry`; las reglas contables viven en `rules.py`.

## Decisión propuesta

### Entrada

`POST /api/integrations/{source}/events`, con `source` en una lista cerrada (`atlas-one`, `hrflow`, y las que se agreguen por ADR).

| Cabecera | Valor |
|---|---|
| `X-Atlas-Signature` | `sha256=<HMAC-SHA256(secreto de la conexión, cuerpo crudo)>` |
| `X-Atlas-Timestamp` | Segundos Unix; fuera de ±300 s se rechaza |
| `X-Atlas-Event-Id` | Identificador del evento en el origen |

Cuerpo mínimo: `event`, `occurred_at` (hora con zona), `external_reference` (única por empresa y origen), `organization_external_id`, y el contenido del evento.

### Conexión

Una `integration_connection` por organización y origen guarda: el identificador de la empresa en el origen, el secreto (cifrado, con hasta dos secretos activos para rotar sin corte), los mapeos (sucursal, forma de pago) y si está activa. **La organización de Financials sale de la conexión**, nunca del cuerpo.

### Guardar antes de procesar

1. Se verifica la firma y la ventana; si fallan, 401 y no se guarda el cuerpo.
2. Se busca la conexión; si no existe o está inactiva, 404.
3. Se inserta el evento en `inbound_events` con restricción única sobre `(organization_id, source, external_reference)` y la huella SHA-256 del cuerpo.
4. Si la restricción choca:
   - misma huella: **duplicado**, 200 con el resultado original;
   - huella distinta: **conflicto**, 409 y alerta. Una corrección del origen debe llegar como evento propio (cancelación, devolución, corrección), no reutilizando la referencia.
5. Se valida el contenido contra su esquema; si falla, el evento queda **rechazado** con el motivo y se responde 422.
6. Se procesa: el evento entra como operación validada (vía el servicio del dominio, que usa `rules.py`) o como propuesta para aprobación humana, según el tipo de evento y la configuración de la conexión.
7. Si el procesamiento falla (regla contable, periodo cerrado, dato faltante), el evento queda **fallido** con el error, reprocesable, y se responde 202. Al tercer fallo se alerta. Nunca un 500 silencioso.

Estados: `ACEPTADO`, `DUPLICADO`, `RECHAZADO`, `FALLIDO`; `PROCESADO` al terminar con éxito.

### Reglas del contenido

Tomadas de la tabla de contrato del megaplan:

- Montos y cantidades como cadenas decimales; nunca números de punto flotante.
- Tasas como fracción con cuatro decimales (`"0.1600"`).
- Base e impuesto por renglón; Financials rechaza lo que no cuadre.
- Hora con zona y código postal de la sucursal, para fechar el comprobante.
- Una devolución o cancelación es un evento propio con su importe; nunca reescribe la venta original.

### Respuesta al origen

El resultado del timbrado (UUID, estado, enlaces) vuelve al origen. Eso es un evento saliente y depende de ADR-012 (outbox, hoy diferida): el primer consumidor real será el punto de venta, así que la fase 3 obliga a decidir ADR-012.

## Consecuencias

- Un reintento nunca duplica; un fallo deja el evento reprocesable sin pedirle nada al origen.
- Nueva superficie pública: requiere límite de peticiones por conexión y pruebas de aislamiento (una conexión no puede escribir en otra organización).
- Pruebas obligatorias: mismo evento dos veces, misma referencia con contenido distinto, firma inválida, ventana vencida, organización ajena en el cuerpo ignorada.
- Reconciliación diaria contra la API de lectura del origen, cuando exista, para detectar eventos que nunca llegaron.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Usar `source_type`/`source_id` de la póliza como llave de idempotencia | Se repite por diseño |
| Base de datos compartida entre suites | Rompe ADR-008 (integración por contrato) y el aislamiento por organización |
| Llamadas directas del origen a los endpoints actuales con llave de agente | Las llaves de agente sólo proponen y no tienen semántica de evento ni idempotencia por referencia |

## Pendiente

- Aceptación del founder.
- Acordar con Atlas ONE y HRFlow el catálogo de eventos y sus esquemas versionados.
