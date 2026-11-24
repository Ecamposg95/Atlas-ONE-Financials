# ADR-006 — Nomenclatura: Atlas ONE Financials

**Fecha:** 2026-11-23 · **Estado:** aceptada

## Contexto

El producto nació como ARCA. Después se le llamó "ONE Finance" en el copy visible, con ARCA como nombre del motor y submarcas por módulo ("ONE Accounting", "ONE Treasury"…) en `docs/ATLAS_ONE_FINANCE_VISION.md`. Tres nombres para lo mismo confunden a clientes, partners y a quien escribe código.

## Decisión

- La suite se llama **Atlas ONE Financials**; nombre corto, **Atlas Financials**. Slug `financials`, identificador `FIN`.
- Los módulos llevan nombres descriptivos (Contabilidad, Tesorería, Fiscal…), sin marca propia.
- **ARCA** queda como alias histórico. No se escribe en copy visible.
- "ONE Finance" deja de usarse.

## Consecuencias

- El copy, `CLAUDE.md`, `AGENTS.md`, los loggers (`financials.*`), el paquete del frontend y el CI ya usan el nombre nuevo (sprint 1).
- Siguen con el nombre anterior, a propósito, los identificadores que alguien externo ya usa: llaves `arca-auth` y `arca-theme` de `localStorage`, variables `ARCA_URL` / `ARCA_API_KEY` y servidor MCP `arca`, `"service": "arca"` en `/api/health`, el servicio y el dominio de Railway. Se migran con alias de lectura dual según `docs/financials/04_REBRANDING_PLAN.md`.
- No se renombran tablas, columnas, migraciones aplicadas ni documentos históricos fechados.
