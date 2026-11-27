# CLAUDE.md — Atlas ONE Financials (antes ARCA)

Lee `AGENTS.md` primero: ahí viven los invariantes financieros que NUNCA se rompen (partida doble, tenant isolation, Decimal para dinero, saldos solo vía `record_transaction`, reglas contables solo en `app/services/accounting/rules.py`).

## Contexto rápido

- **Qué es:** Atlas ONE Financials, suite financiera del ecosistema Atlas ONE (ADR-006). ARCA es el nombre anterior y queda como alias histórico (llaves de `localStorage`, servidor MCP: no renombrar sin alias, ver `docs/financials/04_REBRANDING_PLAN.md`). En copy visible al usuario escribe "Atlas ONE Financials" o, si el espacio es corto, "Atlas Financials"; nunca "ARCA" ni "ONE Finance". Los módulos llevan nombres descriptivos, sin marca propia. Estrategia y decisiones: `docs/financials/` y `docs/decisions/`. Plataforma de administración financiera y contable para pymes mexicanas. UX en lenguaje de empresario (español); motor contable formal por debajo. Spec: `docs/TASK_PACK.md`; estado: `docs/MVP_STATUS.md`.
- **Stack:** FastAPI 0.127 + SQLAlchemy 2 + Pydantic v2 + Alembic + PostgreSQL · React 18 + TS + Vite + Tailwind + TanStack Query v5 + Zustand · Docker en VPS de IONOS detrás de Caddy.
- **Layout:** dominios en `app/domains/<x>/` (router/service/schemas); modelos en `app/models/` (registrar módulos nuevos en su `__init__.py` o create_all/autogenerate los omiten); motor contable en `app/services/accounting/`.

## Comandos

```bash
source .venv/bin/activate
pytest                          # 39+ tests, SQLite en memoria
ruff check .
alembic upgrade head && uvicorn app.main:app --reload
cd frontend && npm run dev      # proxy /api → :8000
cd frontend && npm run typecheck && npm run build
```

## Convenciones

- API `/api/<dominio>` plural sin slash final; paginación `{items,total,limit,offset}`; errores `{"detail":"mensaje en español"}`; nunca ORM crudo.
- Migraciones `AAAAMMDD_NN_slug.py` con `revision="AAAAMMDD_NN"`; un solo head; nunca `create_all()` en producción.
- Montos: `Decimal`/`Numeric(14,2)`; schemas con `Field(gt=0, allow_inf_nan=False)`; el front manda strings.
- Commits: Conventional Commits en español.
- UI: marca Atlas Tech (skill `atlas-tech-brand`: ember + índigo, claro Niebla y oscuro Horizon, Inter; nunca peso 700) con La Fe en su verde como marca por empresa (`[data-brand]`). Tokens semánticos Tailwind (`bg-surface`, `text-muted`…), cero colores crudos; cifras con clase `.figures` (Inter con `tabular-nums`; la protagonista con `.figure-hero`); paneles con `.panel` (radio 10px, borde, sin sombra); copy en español, empty states con CTA.

## Deployment

VPS de IONOS (`atlas-prod-01`, 74.208.190.44), el mismo de Atlas ONE, HRFlow y RMAZH. Dominio: https://financials.atlasone.com.mx (DNS en Cloudflare, sin proxy; Caddy saca el certificado). **push a main = deploy**: la tarea `Deploy a IONOS` de `.github/workflows/ci.yml` (si backend y frontend pasan y la variable del repo `DESPLIEGUE_IONOS=true`) sube el código a `/srv/apps/financials/src`, construye el `Dockerfile` y levanta `deploy/ionos/docker-compose.yml` (contenedor `financials`, red `edge`), y verifica que el contenedor corre el commit nuevo y que `/api/health/deep` ve la base. El arranque ejecuta `alembic upgrade head`. Base: PostgreSQL 18 compartido del servidor (contenedor `postgres`), base `atlas_financials` con usuario propio; entra en el respaldo nocturno `/srv/backups/pg_backup.sh` (14 días). Variables en `/srv/apps/financials/.env` (`ENV`, `DATABASE_URL`, `SECRET_KEY`). Railway quedó retirado el 2026-11-27 (app sin despliegue ni fuente; su PostgreSQL se conserva unos días como respaldo).
