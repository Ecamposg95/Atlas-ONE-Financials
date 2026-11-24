# ADR-007 — Entidad legal y libros: una organización por razón social

**Fecha:** 2026-11-23 · **Estado:** aceptada

## Contexto

Una organización es el tenant y tiene un solo libro: un catálogo, una serie de folios y un juego de candados de periodo. `FiscalEntity` existe, pero es una etiqueta opcional sobre pólizas y operaciones (`app/models/dimensions.py`); no posee libro propio. Un grupo con varias razones sociales necesita estados financieros formales por cada una.

Se evaluaron tres caminos: (A) un libro por entidad legal dentro del mismo tenant, (B) una organización por razón social, agrupadas por encima, y (C) dejar la etiqueta.

## Decisión

**Opción B.** Cada razón social es una organización, con su libro completo. Un **grupo** las reúne por encima.

- El libro no cambia: pólizas, folios, periodos y catálogo siguen siendo por organización.
- El aislamiento por organización, que es el invariante mejor probado del sistema, se conserva intacto.
- `FiscalEntity` sigue siendo una etiqueta de análisis dentro de una organización; no se convierte en libro.
- La vista multiempresa de un usuario ya existe (`app/domains/portfolio`); el grupo la formaliza.

## Consecuencias

- Nuevo concepto de grupo y permisos a nivel grupo, cuando haya un cliente que lo requiera. No se construye ahora.
- Los catálogos compartidos entre razones sociales (clientes, proveedores, catálogo de cuentas) se resuelven por sincronización o plantilla, no por tabla común.
- La consolidación, cuando llegue, opera entre organizaciones de un grupo y pertenece a la futura suite EPM (ADR-015, propuesta).
- CFDI y conciliación bancaria se diseñan por organización: el receptor de un comprobante es la razón social de la organización.
- Se descarta mover pólizas existentes a un modelo de libros múltiples; no hay migración del núcleo.

## Pendiente

Revisar cómo usa La Fe la etiqueta de contribuyente y si necesita balance formal por contribuyente; si es así, su camino es separar organizaciones, no convertir la etiqueta en libro.
