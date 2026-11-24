# 01 · Auditoría del repositorio

_Atlas ONE Financials (antes ARCA) · Corte: 2026-11-23, commit `46f5285` · Fase 0 — Discovery_

## Resumen ejecutivo

El repositorio contiene un núcleo contable real y en producción, no un registro de ingresos y gastos: mayor de partida doble con un único punto de asiento, reglas contables centralizadas, folios inmutables, candados de periodo y ejercicio, reversos en lugar de borrados, y una capa de agentes que sólo propone. Lo que el task pack llama "Financial Core" (fase 2) ya existe en su mayor parte.

Las brechas están en tres frentes: **fiscal** (no hay CFDI), **tesorería** (no hay conciliación bancaria) y **empresa** (no hay entidad legal con libro propio, consolidación, presupuestos, entitlements ni versionado de API). Además, `docs/ARCHITECTURE.md` describe como si existieran piezas que el código no tiene (webhooks de integración, outbox, secretos fiscales cifrados).

## Alcance y método

- **Qué se revisó:** estructura de `app/`, modelos, routers, servicios, pruebas, migraciones, frontend, CI, despliegue y documentación; búsquedas por palabra clave para confirmar ausencias.
- **Qué no se hizo:** lectura línea por línea de cada servicio, ejecución de la suite de pruebas en esta fase, revisión de la base de producción ni de los respaldos de Railway.
- **Cómo leer las etiquetas:** *Implementada* = hay modelo, endpoint y pruebas; *Parcial* = existe una parte utilizable; *Ausente* = cero coincidencias en `app/`; *No verificable* = no se puede determinar desde el repositorio.

## Inventario técnico (evidencia)

| Elemento | Hallazgo | Evidencia |
|---|---|---|
| Backend | FastAPI + SQLAlchemy 2 + Pydantic v2 + Alembic, ~22,500 líneas de Python | `app/`, `requirements.txt` |
| Frontend | React 18 + TypeScript + Vite + Tailwind + TanStack Query + Zustand, ~19,800 líneas | `frontend/src/` |
| Arquitectura | Monolito modular de servicio único; FastAPI sirve `/api/*` y la SPA construida | `app/main.py`, `docs/decisions/001-single-service-deployment.md` |
| Dominios | 32 dominios con router / service / schemas | `app/domains/` |
| Endpoints | ~155 (conteo de decoradores `@router.*`; aproximado) | `app/domains/*/router.py` |
| Modelos | 41 clases ORM en 28 módulos | `app/models/` |
| Migraciones | 26, un solo head, convención `AAAAMMDD_NN_slug.py` | `alembic/versions/` |
| Pruebas | ~636 funciones de prueba en 68 archivos `test_*.py` | `tests/` |
| CI | GitHub Actions: Postgres 16, `ruff`, `pytest`, typecheck del frontend | `.github/workflows/ci.yml` |
| Despliegue | Railway, push a `main` = deploy; ajustes del servicio en IaC | `railpack.json`, `.railway/railway.ts` |
| ADRs | 5 decisiones registradas (servicio único, UUID, partida doble, Decimal, capa agéntica) | `docs/decisions/` |

## Inventario funcional contra el mapa del task pack

| Dominio | Estado | Evidencia | Brecha |
|---|---|---|---|
| General Ledger | Implementada | `app/services/accounting/engine.py::post_journal_entry`, `rules.py` (20 reglas), `folios.py`, `coa.py`; `domains/accounting` (17 endpoints: catálogo, pólizas manuales, reverso, balanza); `domains/periods`, `domains/opening`; `tests/test_ledger.py`, `test_folios.py`, `test_cierre_periodo.py`, `test_cierre_anual.py`, `test_reversos.py` | Un solo libro por organización; sin libros múltiples |
| Accounts Receivable | Implementada | `domains/receivables`, `domains/income`, `models/receivable.py`; antigüedad en `GET /api/reports/aging` (`tests/test_antiguedad.py`) | No existe entidad `PaymentAllocation`; los cobros se aplican dentro del documento |
| Accounts Payable | Implementada | `domains/payables`, `domains/expenses`, `models/payable.py`; autorización por monto en `app/services/approvals.py` (`tests/test_autorizacion.py`) | Igual que AR respecto a aplicación de pagos |
| Cash Management | Parcial | `domains/financial_accounts`, `domains/transactions`, `domains/cash_cuts`, `models/settlement.py` (liquidaciones de procesador), `GET /api/reports/cash-flow` y `cash-projection` | **Conciliación bancaria ausente** (cero coincidencias de "concilia/reconcil" en `app/`); no hay estado de cuenta bancario importado |
| Tax | Parcial | `app/services/taxes.py`, `deductibility.py`; retenciones (`tests/test_retenciones.py`); reporte de IVA; contabilidad electrónica y balanza SAT (`services/accounting/sat.py`, `tests/test_sat_xml.py`); exportación CONTPAQi (`contpaqi.py`) | **CFDI ausente** (cero coincidencias de "cfdi" en `app/`); los XML sólo se guardan como adjuntos (`services/attachments.py`) |
| Expenses | Parcial | `domains/expenses`, adjuntos (`models/attachment.py`), aprobaciones, recurrentes (`domains/recurring`) | Sin viáticos ni reembolsos |
| Fixed Assets | Implementada | `domains/fixed_assets`, `domains/loans`; `tests/test_activos_fijos.py`, `test_prestamos.py`, `test_patrimonio.py` | Saldos al corte distintos del original (pendiente en `docs/MVP_STATUS.md`) |
| Financial Reporting | Implementada | `domains/reports` (10 endpoints: resultados, balance, flujo, IVA, proyección, antigüedad, patrimonio, series, CSV); exportación a Excel (`reports/export.py`) | Sin estados NIF formales verificados en esta fase |
| Financial Planning | Ausente | "budget" sólo aparece como presupuesto de IA (`services/ai/budget.py`); las metas 2027 de La Fe viven como puntos de análisis (`models/historical.py`) | Presupuestos, escenarios, forecasting |
| Consolidation | Ausente | Existe cartera multiempresa por usuario (`domains/portfolio`) | Intercompany, eliminaciones, multimoneda |
| Governance & Compliance | Parcial | `models/change_log.py`, `domains/history`; 5 roles (`require_role` en `app/security/deps.py`); candados (`models/period.py`, `fiscal_year.py`) | Sin matriz de segregación de funciones, sin rate limiting, sin permisos por entidad legal |
| Financial Intelligence | Implementada | Asistente (`app/services/ai/`, `domains/assistant`), API de agentes con llaves (`domains/agent_api`, `agent_keys`, `app/security/agent.py`), propuestas (`domains/proposals`), servidor MCP (`tools/arca_mcp.py`) | Sin `ANTHROPIC_API_KEY` en producción; sin detección de anomalías ni conciliación asistida |

## Capacidades transversales

| Capacidad | Estado | Evidencia |
|---|---|---|
| Multi-tenancy | Implementada | `TenantMixin` con `organization_id` NOT NULL; `get_current_org_id` toma la organización de la membresía; `tests/test_tenant_isolation.py` |
| Entidad legal | Parcial | `models/fiscal_entity.py` existe, pero es una etiqueta opcional (`models/dimensions.py`: "Son etiquetas: no tocan la partida doble") |
| Sucursal / unidad de negocio | Parcial | `models/business_unit.py`, también como dimensión opcional |
| Multimoneda | Ausente en la práctica | Columnas `currency` con `MXN` por defecto en `organization.py`, `financial_account.py`, `transaction.py`; cero coincidencias de tipo de cambio |
| Versionado de API | Ausente | Todo cuelga de `/api`; no existe `/v1` |
| Eventos de dominio | Parcial | Bus síncrono en proceso (`app/core/events.py`); se publican `journal_entry.created`, `expense.*`, `payable.*`, `receivable.created`, `proposal.*` |
| Outbox / webhooks de integración | Ausente | Cero coincidencias de `outbox_events`, `inbound_events`, `integration_connections` o `/integrations` en `app/` y `alembic/` |
| Idempotencia | Parcial | Procesos periódicos por `source_id` (`AGENTS.md` invariante 14); importación por folio o hash; no hay restricción única en BD sobre `source_id` |
| Entitlements / feature flags | Ausente | Cero coincidencias |
| Auditoría | Implementada | `change_log` append-only con valores anteriores; bitácora de acciones de agente (`models/agent.py`) |
| Respaldos y restauración | No verificable | No hay scripts ni runbooks de respaldo en el repositorio |
| Observabilidad | Parcial | Healthcheck y loggers `arca.*`; sin métricas ni alertas |

## Divergencias entre documentación y código

`docs/ARCHITECTURE.md` (fechado 2026-10-12) mezcla lo construido con lo planeado sin distinguirlo:

- §8 describe `POST /api/integrations/{source}/events`, `inbound_events` y `outbox_events`. **No existen en el código.**
- §9 afirma "Secretos fiscales (CSD, e.firma) cifrados por empresa (Fernet…)". **No hay nada de eso en `app/`.**
- §9 lista "rate limiting y bloqueo temporal en auth". **Ausente** (también reconocido como deuda en `docs/MVP_STATUS.md`).
- §7 habla de 21 herramientas de agente; `docs/MVP_STATUS.md` cita un catálogo de 18. El número vigente no se verificó.

Esto es un riesgo comercial y de seguridad: un partner o un auditor que lea el documento asumirá controles que no están.

## Activos reutilizables

- Motor contable y sus invariantes (`AGENTS.md`, 20 reglas no negociables ya vigiladas por pruebas).
- Patrón de propuesta con aprobación humana (`AgentProposal`), que ya sirve para agentes, asistente y autorización por monto.
- Capa de importación con vista previa y confirmación todo-o-nada (`domains/imports`).
- Capa de análisis separada del libro (`domains/analytics`), que nunca crea pólizas.
- Marca por empresa (`organizations.brand`, `frontend/src/lib/brand.ts`), base para presets visuales.
- Componentes de interfaz: `Table`, `ListFilters`, `Pagination`, `Money`, `HistoryTimeline`, `CommandPalette` (`frontend/src/components/ui/`).

## Riesgos de producción

| Riesgo | Detalle |
|---|---|
| Cliente real en producción | La Fe opera con histórico cargado; cualquier cambio al modelo de tenant o al libro la afecta |
| Sin rate limiting ni lockout en `/auth` | Expuesto a fuerza bruta |
| Tokens en `localStorage` | `frontend/src/stores/authStore.ts` persiste access y refresh bajo la llave `arca-auth` |
| Adjuntos en PostgreSQL | `attachment_blobs` guarda bytes en la base; crece con el uso |
| Balance sólo en aplicación | No hay `CheckConstraint` en BD; el cuadre depende de que todo pase por `post_journal_entry` |
| Respaldos no verificados | No hay evidencia de prueba de restauración |
| Bus de eventos no durable | Un evento se pierde si el proceso cae después del commit |

## Decisiones pendientes

1. ¿Se corrige `docs/ARCHITECTURE.md` para separar "hoy" de "plan", o se reemplaza por `03_DOMAIN_ARCHITECTURE.md`?
2. ¿Quién valida el estado de los respaldos de Railway y con qué frecuencia se prueba la restauración?
