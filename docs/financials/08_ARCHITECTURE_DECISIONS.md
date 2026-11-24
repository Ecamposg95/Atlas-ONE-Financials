# 08 · Decisiones de arquitectura

_Atlas ONE Financials (antes ARCA) · Corte: 2026-11-23 · Fase 0 — Discovery_

## Resumen ejecutivo

Este documento reúne las decisiones de arquitectura de la evolución a Atlas ONE Financials. Continúa la numeración de `docs/decisions/` (001 a 005). Dos decisiones ya están tomadas por el founder (nomenclatura y estrategia); el resto son propuestas. Al aceptarse, cada una debe pasar a su propio archivo en `docs/decisions/`.

**ADR-007 (entidad legal y libros)** quedó aceptada con la opción B: una organización por razón social, agrupadas por encima. Los ADR 006, 007 y 008 ya viven en `docs/decisions/`.

## Decisiones vigentes (evidencia)

| ADR | Decisión | Archivo |
|---|---|---|
| 001 | Despliegue de servicio único | `docs/decisions/001-single-service-deployment.md` |
| 002 | Llaves primarias UUID | `docs/decisions/002-uuid-primary-keys.md` |
| 003 | Libro de partida doble | `docs/decisions/003-double-entry-ledger.md` |
| 004 | Dinero en Decimal | `docs/decisions/004-money-decimal.md` |
| 005 | Capa agéntica con aprobación humana | `docs/decisions/005-capa-agentica.md` |

Ninguna se modifica.

## Índice de decisiones nuevas

| ADR | Tema | Estado |
|---|---|---|
| 006 | Nomenclatura: Atlas ONE Financials | **Aceptada** (2026-11-23) |
| 007 | Entidad legal y libros | **Aceptada: opción B** (2026-11-23) |
| 008 | Estrategia B: monolito modular con límites de módulo | **Aceptada** (2026-11-23) |
| 009 | Versionado de API | Propuesta |
| 010 | Datos maestros entre suites | Propuesta |
| 011 | Eventos entrantes e idempotencia | Propuesta |
| 012 | Outbox para eventos salientes | Propuesta, diferida |
| 013 | Localización mexicana como capa | Propuesta |
| 014 | Entitlements y presets | Propuesta |
| 015 | Planeación y consolidación fuera de Financials | Propuesta |
| 016 | Sesión y almacenamiento de tokens | Propuesta |

---

## ADR-006 · Nomenclatura

**Estado:** Aceptada.

**Contexto:** el repositorio y sus reglas usaban "ONE Finance" como nombre visible, "ARCA" como motor y submarcas por módulo ("ONE Accounting", "ONE Treasury"…).

**Decisión:** la suite se llama Atlas ONE Financials; nombre corto, Atlas Financials. Los módulos llevan nombres descriptivos sin marca propia. ARCA queda como alias histórico.

**Consecuencias:** actualizar `CLAUDE.md`, `AGENTS.md` y el copy; `docs/ATLAS_ONE_FINANCE_VISION.md` queda superado en nomenclatura. Los identificadores internos se migran con alias según `04_REBRANDING_PLAN.md`.

---

## ADR-007 · Entidad legal y libros

**Estado:** Aceptada, opción B (founder, 2026-11-23). Texto vigente: `docs/decisions/007-entidad-legal-y-libros.md`.

**Contexto (evidencia):** hoy una organización es el tenant y tiene un solo libro, un catálogo y un juego de candados de periodo. `FiscalEntity` es una etiqueta opcional sobre pólizas y operaciones (`app/models/dimensions.py`). La Fe ya usa contribuyentes como etiqueta. El task pack pide no confundir tenant con razón social.

**Opciones:**

| | A. Libro por entidad legal dentro del tenant | B. Una organización por razón social, agrupadas | C. Mantener etiqueta |
|---|---|---|---|
| Modelo | Nuevo `Ledger` que pertenece a la entidad legal; pólizas, periodos y folios pasan a ser por libro | Nueva entidad "grupo" por encima de organizaciones; cada organización sigue igual | Sin cambio |
| Migración | Alta: toca el núcleo y a cada póliza existente | Baja: se agrega una capa, no se altera el libro | Ninguna |
| Aislamiento | Un tenant con varios libros; permisos por entidad | Reutiliza el aislamiento por organización ya probado | — |
| Consolidación | Dentro del tenant | Entre organizaciones del grupo | No disponible |
| Datos compartidos (clientes, proveedores) | Naturales | Requieren compartirse o duplicarse | Naturales |
| Reportes por razón social | Estados financieros formales por libro | Ya existen por organización | Sólo filtro por etiqueta; no hay balance formal |
| Riesgo con La Fe en producción | Alto | Bajo | Ninguno |

**Recomendación:** opción B como camino por defecto. Conserva el invariante mejor probado del sistema (aislamiento por organización), no altera el libro y `domains/portfolio` ya ofrece la vista multiempresa de un usuario. La opción A sólo se justifica si un cliente necesita compartir operación diaria entre razones sociales dentro de un mismo espacio de trabajo.

**Pendiente de verificar antes de decidir:** cómo usa La Fe hoy la etiqueta de contribuyente y si necesita balance formal por contribuyente.

**Consecuencias si se elige B:** nuevo concepto de grupo, permisos a nivel grupo, y los catálogos compartidos se resuelven por sincronización, no por tabla común.

---

## ADR-008 · Estrategia B: monolito modular con límites de módulo

**Estado:** Aceptada.

**Decisión:** se conserva el servicio único (ADR-001). Los módulos se organizan como en `03_DOMAIN_ARCHITECTURE.md`, con reglas de dependencia: el núcleo contable no depende de nadie; sólo Operaciones escribe al núcleo y lo hace mediante `rules.py`; nada externo llama a `post_journal_entry`.

**Consecuencias:** no hay microservicios. Los límites se vigilan con revisión y, como propuesta, con una prueba que falle si un módulo importa a otro fuera de lo permitido.

---

## ADR-009 · Versionado de API

**Estado:** Propuesta.

**Contexto:** todas las rutas cuelgan de `/api` sin versión. Ya hay consumidores externos: agentes con llave y el servidor MCP.

**Decisión propuesta:** exponer `/api/v1` como alias de las rutas actuales y mantener `/api` sin versión mientras existan consumidores. Los cambios incompatibles van a una versión nueva.

**Consecuencias:** costo bajo ahora; evita romper integraciones después.

---

## ADR-010 · Datos maestros entre suites

**Estado:** Propuesta.

**Decisión propuesta:** cada dato tiene un solo dueño. Commerce es dueño del cliente comercial y del inventario; HCM, del empleado; Financials, del catálogo de cuentas, las pólizas, los saldos, la cartera y, mientras no exista SCM, del proveedor. Financials guarda de lo ajeno sólo una referencia externa y lo necesario para la cartera.

**Consecuencias:** `Customer` necesita un campo de referencia externa por origen. No se duplican motores ni catálogos.

**Pendiente:** validar con los equipos de las otras suites; a la fecha del último registro (`docs/MEGA_PLAN_MVP.md`, 2026-10-12) ninguna mencionaba a ARCA.

---

## ADR-011 · Eventos entrantes e idempotencia

**Estado:** Propuesta.

**Contexto:** `docs/ARCHITECTURE.md` §8 describe un contrato de webhooks firmados que no está implementado. El origen de una póliza (`source_type`, `source_id`) se repite por diseño, así que la idempotencia de eventos necesita su propia llave.

**Decisión propuesta:** adoptar ese contrato como diseño: identificador de evento del origen, firma HMAC con ventana de tiempo, referencia externa única por empresa y origen, y estados aceptado, duplicado, rechazado y fallido. Los eventos se guardan antes de procesarse y entran al libro como propuesta u operación validada. La tabla de eventos entrantes lleva restricción única sobre la referencia externa.

**Consecuencias:** un reintento nunca duplica; un fallo de regla contable deja el evento reprocesable.

---

## ADR-012 · Outbox para eventos salientes

**Estado:** Propuesta, diferida.

**Contexto:** el bus actual es síncrono y en proceso (`app/core/events.py`); un evento puede perderse si el proceso cae tras el commit. Hoy no hay consumidores externos.

**Decisión propuesta:** introducir outbox durable sólo cuando exista el primer consumidor externo real. Hasta entonces el bus se queda.

**Consecuencias:** se evita infraestructura (worker, reintentos, monitoreo) sin uso.

---

## ADR-013 · Localización mexicana como capa

**Estado:** Propuesta.

**Decisión propuesta:** lo específico de México (CFDI, validaciones, mapeos del SAT, PAC) vive en un módulo de localización que produce documentos estructurados y propuestas. No contiene reglas contables: éstas siguen en `rules.py`. No se almacenan certificados ni llaves privadas hasta tener un diseño aprobado de cifrado, rotación y permisos.

**Consecuencias:** el núcleo queda independiente del país. Las piezas fiscales que ya existen (`services/taxes.py`, `deductibility.py`, `accounting/sat.py`) se reubican de forma gradual, sin cambio de comportamiento.

---

## ADR-014 · Entitlements y presets

**Estado:** Propuesta.

**Decisión propuesta:** los módulos habilitados por organización se guardan en base y se evalúan en el backend, además del rol. Un preset es un conjunto versionado de valores de configuración (módulos, navegación, catálogos iniciales, valores por defecto). Un preset nunca bifurca código.

**Consecuencias:** un módulo deshabilitado responde 403; la interfaz arma la navegación con lo que informa `/api/me`.

---

## ADR-015 · Planeación y consolidación fuera de Financials

**Estado:** Propuesta.

**Decisión propuesta:** escenarios, forecasting, FP&A y consolidación pertenecen a una futura suite EPM que lee de Financials. Financials puede ofrecer, como mucho, un presupuesto simple por categoría y periodo.

**Consecuencias:** no se construye un segundo motor ni se duplican datos. La capa de análisis existente (`domains/analytics`) es el antecedente: lee del libro y nunca escribe en él.

---

## ADR-016 · Sesión y almacenamiento de tokens

**Estado:** Propuesta.

**Contexto:** el frontend guarda access y refresh en `localStorage`; el access dura 12 horas por defecto (`app/config.py`).

**Opciones:** mantener el esquema y acortar la vida del access; o mover el refresh a cookie `HttpOnly` con protección CSRF.

**Recomendación:** acortar el access de inmediato; evaluar la cookie junto con el cambio de dominio, porque ambos tocan la sesión.

---

## Riesgos

| Riesgo | Decisión relacionada |
|---|---|
| Elegir la opción A de ADR-007 sin un cliente que la necesite | 007 |
| Dejar ADR-007 sin decidir y que CFDI nazca atado a la organización | 007, 013 |
| Construir outbox e integraciones antes de que exista el otro lado | 011, 012 |
| Presets que acaban requiriendo código propio | 014 |
| Datos maestros definidos sin acuerdo de las otras suites | 010 |

## Decisiones que requieren al founder

1. ~~ADR-007~~: resuelta, opción B.
2. ADR-015: ¿presupuesto simple en Financials, sí o no?
3. ADR-016: ¿cookie `HttpOnly` junto con el cambio de dominio?
4. Aceptación del resto de propuestas, o cambios.
