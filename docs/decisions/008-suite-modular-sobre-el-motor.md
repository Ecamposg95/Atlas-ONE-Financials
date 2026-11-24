# ADR-008 — Suite modular sobre el motor existente

**Fecha:** 2026-11-23 · **Estado:** aceptada

## Contexto

Para evolucionar ARCA hacia Atlas ONE Financials se compararon tres estrategias: rebranding mínimo, suite financiera modular sobre el motor actual, y una arquitectura financiera transversal compartida por todas las suites de Atlas ONE. La auditoría (`docs/financials/01_REPOSITORY_AUDIT.md`) mostró que el núcleo contable ya existe y está probado.

## Decisión

Suite modular sobre el motor existente, en el mismo servicio (ADR-001 sigue vigente).

- El núcleo contable no depende de ningún otro módulo.
- Sólo los módulos de operación escriben al libro, y lo hacen mediante `app/services/accounting/rules.py`.
- Nada externo llama a `post_journal_entry`: lo que llega de fuera entra como propuesta o como operación validada.
- Los módulos nuevos (CFDI, conciliación, entitlements) se agregan uno a la vez, cada uno con su gate de invariantes.

## Consecuencias

- Sin microservicios y sin reescritura.
- Las integraciones con otras suites se hacen por contrato (eventos firmados e idempotentes), no compartiendo base de datos.
- Consolidación, planeación avanzada y multimoneda quedan fuera hasta que un cliente las requiera.
