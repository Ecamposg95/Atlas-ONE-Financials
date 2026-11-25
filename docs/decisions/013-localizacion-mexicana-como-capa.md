# ADR-013 — Localización mexicana como capa

**Fecha:** 2026-11-25 · **Estado:** propuesta (pendiente de aceptación del founder; redacción formal de la propuesta de `docs/financials/08_ARCHITECTURE_DECISIONS.md`)

> El número 013 viene reservado desde el documento 08. Nada de esto está construido.

## Contexto

- Financials va a emitir, cancelar y conservar CFDI (`docs/financials/09_MEGAPLAN_CFDI.md`). Hoy no tiene código de CFDI.
- Ya existen piezas fiscales repartidas: `app/services/taxes.py` (IVA y retenciones), `app/services/deductibility.py` (aviso de deducibilidad), `app/services/accounting/sat.py` y `sat_codes.json` (contabilidad electrónica y código agrupador). Ninguna regla fiscal ha sido validada por un contador (`docs/financials/07_SECURITY_AND_COMPLIANCE.md`).
- `docs/financials/03_DOMAIN_ARCHITECTURE.md` define el módulo Localización MX: dueño de documentos fiscales, validaciones y mapeos del SAT; puede leer Operaciones y Núcleo; no puede contener lógica contable.
- Los catálogos del SAT cambian durante el año (la versión del 20-11-2026 se publicó cuatro días antes de la investigación).
- Riesgo señalado en el documento 03: que la localización acabe con lógica contable y rompa el invariante 9 de `AGENTS.md`.

## Decisión propuesta

Todo lo específico de México vive en un módulo de localización con límites explícitos.

**Es dueño de:**

- El documento fiscal: tipo (ingreso, egreso, pago, nómina), conceptos, impuestos, relaciones, estado ante el SAT, UUID, XML sellado, XML timbrado, acuses, y el enlace a la operación que lo originó.
- Validaciones previas: estructura, catálogos, cuadre, padrón del receptor.
- Catálogos y matrices de error del SAT, **como datos versionados con vigencia**, nunca como enumeraciones en código.
- Mapeos: forma de pago, clave de producto y unidad, régimen, uso de CFDI.
- El módulo de sellado (ADR-017) y los adaptadores de proveedor de timbrado (ADR-018).

**No hace:**

- **No contiene reglas contables.** Un documento fiscal no crea pólizas. La operación de origen (ingreso, cuenta por cobrar, venta de punto de venta, nómina) crea su póliza en `rules.py`, como hoy. El documento fiscal se liga a la operación; la operación al libro.
- No llama a `post_journal_entry` ni a `record_transaction`.
- No decide si algo es ingreso, ni cuándo: emitir un CFDI no equivale a reconocer ingreso ni a cobrar (`07_SECURITY_AND_COMPLIANCE.md`, distinciones del diseño).

**Almacenamiento de certificados:** prohibido hasta tener un diseño aprobado de cifrado, rotación y permisos. ADR-017 (aceptada) es ese diseño; el almacenamiento sólo se habilita tal como lo describe.

**Reubicación gradual:** `taxes.py`, `deductibility.py` y `accounting/sat.py` se mueven a la capa cuando se toquen por otra razón, sin cambio de comportamiento y con sus pruebas intactas. No hay migración de una sola vez.

**Dirección de dependencias:** Localización lee Operaciones y Núcleo. Operaciones no importa Localización salvo por una interfaz para pedir un documento. Una prueba de límites de módulo (propuesta en ADR-008) vigila que Localización no importe `engine.py` ni escriba pólizas.

## Consecuencias

- El núcleo contable sigue independiente del país.
- Las pólizas de venta, global, pagos, egresos y nómina se diseñan como reglas en `rules.py`, con revisión de contador (`docs/financials/10_CUESTIONARIO_CONTADOR_CFDI.md`), no dentro del módulo fiscal.
- Una actualización de catálogos del SAT es una carga de datos, no un despliegue de código.
- Hay que decidir dónde vive el código (por ejemplo, un dominio `app/domains/fiscal_mx/` más un paquete de servicios); se decide al empezar la fase 2.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| CFDI dentro de cada dominio (ingresos, cuentas por cobrar, nómina) | Duplica armado, sellado y catálogos; mezcla reglas fiscales con operación |
| Módulo fiscal que también arma pólizas | Rompe el invariante 9 y crea un segundo lugar de lógica contable |
| Servicio aparte para CFDI | Contradice ADR-001 y ADR-008 sin necesidad a esta escala |

## Pendiente

- Aceptación del founder.
- Nombre y ubicación del paquete.
