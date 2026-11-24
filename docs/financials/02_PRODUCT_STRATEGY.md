# 02 · Estrategia de producto

_Atlas ONE Financials (antes ARCA) · Corte: 2026-11-23 · Fase 0 — Discovery_

## Resumen ejecutivo

**Decisión tomada (founder, 2026-11-23):** el producto se llama **Atlas ONE Financials** y evoluciona con la **estrategia B: suite financiera modular sobre el motor existente**. Los módulos llevan nombres descriptivos, sin marca propia. ARCA queda como alias histórico del motor.

El producto ya resuelve el núcleo contable de una pyme mexicana. La estrategia consiste en no reescribirlo, cerrar las dos brechas que más pesan en México (CFDI y conciliación bancaria), y preparar los contratos para integrarse con el resto de Atlas ONE sin acoplarse a suites que todavía no existen.

## North Star

> Construir el núcleo financiero de las organizaciones: una plataforma que centralice, automatice y conecte la gestión contable, financiera, fiscal y patrimonial, con inteligencia artificial supervisada y trazabilidad de extremo a extremo.

Se conserva el principio de producto vigente en `AGENTS.md`: el usuario registra en lenguaje de empresario y el sistema produce contabilidad formal por debajo. La visión enterprise no lo sustituye; lo extiende hacia arriba.

## Identidad y nomenclatura

| Elemento | Definición | Estado |
|---|---|---|
| Suite | Atlas ONE Financials | Decidido |
| Nombre corto | Atlas Financials | Decidido |
| Nombre anterior | ARCA (alias histórico del motor) | Decidido |
| Repositorio | `Ecamposg95/Atlas-ONE-Financials` | Hecho |
| Slug / identificador | `financials` / `FIN` | Propuesto |
| Subdominio | `financials.atlastech.mx` | Pendiente de aprobación |
| Módulos | Nombres descriptivos (Contabilidad, Tesorería, Fiscal…) | Decidido |

**Consecuencia:** la visión anterior (`docs/ATLAS_ONE_FINANCE_VISION.md`) usa "ONE Finance" y submarcas "ONE Accounting", "ONE Treasury", etc. Queda superada en nomenclatura; su contenido funcional sigue siendo referencia. `CLAUDE.md` y `AGENTS.md` todavía ordenan escribir "ONE Finance" en el copy y deben actualizarse en el sprint de rebranding (ver `04_REBRANDING_PLAN.md`).

## Las tres alternativas evaluadas

| Criterio | A. Rebranding mínimo | B. Suite modular sobre ARCA | C. Arquitectura transversal Atlas ONE |
|---|---|---|---|
| Qué es | Cambiar nombre e identidad | Módulos nuevos sobre el mismo libro, con contratos de integración | Servicios financieros compartidos por todas las suites |
| Costo | Bajo | Medio | Alto |
| Riesgo | Bajo | Medio, acotado por módulo | Alto; depende de suites que no existen |
| Tiempo relativo | 1× | 3–4× por módulo, entregable por partes | 10×+ antes del primer valor |
| Mantenibilidad | Igual que hoy | Buena si se respetan límites de módulo | Incierta |
| Impacto comercial | Sólo percepción | Cada módulo es vendible | Diferido |
| Capacidad enterprise | Ninguna nueva | Crece de forma incremental | Máxima, en teoría |

**Por qué B:** el activo más valioso es un libro correcto y probado (ver `01_REPOSITORY_AUDIT.md`). B lo conserva y agrega valor vendible por pasos. A se ejecuta como primer paso de B. C se deja preparada: los contratos de eventos de B son los mismos que C necesitaría.

## Respuestas a las preguntas del task pack (§13)

| Pregunta | Respuesta | Sustento |
|---|---|---|
| ¿Qué es ERP financiero real y qué es sólo ingresos y gastos? | El libro, periodos, cierres, AR/AP, activos, préstamos y reportes son ERP real. Fiscal y tesorería son parciales. | Evidencia en `01_REPOSITORY_AUDIT.md` |
| ¿Existe un mayor de partida doble? | Sí. | `app/services/accounting/engine.py` |
| ¿Compartir servicios con Atlas ONE o integrar aplicaciones? | Integrar aplicaciones independientes por contratos. | Las otras suites corren en otros hosts (`docs/ARCHITECTURE.md` §10) |
| ¿Fuente de verdad de clientes, proveedores, inventario? | Propuesta: Commerce es dueño de clientes comerciales e inventario; Financials es dueño de saldos, cartera y proveedores financieros, con referencia externa. | Requiere ADR (ver `08_ARCHITECTURE_DECISIONS.md`) |
| ¿Múltiples entidades legales sin romper tenants? | Decisión abierta; hoy la entidad fiscal es etiqueta. | `app/models/dimensions.py` |
| ¿Qué complejidad ocultar al emprendedor? | Catálogo, pólizas, folios y periodos; ya se hace. | Navegación actual en `AppLayout.tsx` |
| ¿Qué va en Financials y qué en EPM? | Presupuesto simple por categoría puede vivir en Financials; escenarios, FP&A y consolidación esperan a EPM. | Propuesta |
| ¿Qué se construye, integra o pospone? | Ver sección siguiente. | — |
| ¿Menor MVP vendible? | Lo que hoy está en producción más importación de CFDI. | Hipótesis comercial a validar |
| ¿Diferenciadores de Cortex sin riesgo contable? | Propuestas con evidencia y aprobación humana; el modelo nunca asienta. | `AgentProposal`, ADR-005 |

## Qué construir, integrar y posponer

| Decisión | Capacidad | Razón |
|---|---|---|
| **Construir** | Importación y validación de CFDI recibidos y emitidos | Indispensable en México; el XML ya se adjunta |
| **Construir** | Conciliación bancaria con estado de cuenta importado | Cierra Cash Management |
| **Construir** | Entitlements por módulo y presets | Habilita planes comerciales |
| **Construir** | Contrato de eventos entrantes con idempotencia | Habilita Commerce → Financials |
| **Integrar** | Timbrado (PAC) | No conviene construir un PAC |
| **Integrar** | Nómina (HRFlow / HCM) | Financials recibe el asiento, no calcula nómina |
| **Posponer** | Consolidación, intercompany, multimoneda | Sin cliente que lo pida; alto costo de modelo |
| **Posponer** | EPM (escenarios, FP&A) | Suite futura |
| **Posponer** | Microservicios | El monolito modular es suficiente (ADR-001) |
| **No hacer** | Declaraciones automáticas ante el SAT | Riesgo fiscal y de responsabilidad |

## Niveles de experiencia y oferta

Los tres niveles comparten la misma base transaccional; cambian navegación, vocabulario y módulos habilitados.

| Nivel | Usuario | Qué ve | Estado hoy |
|---|---|---|---|
| Entrepreneur | Dueño sin formación contable | Inicio, dinero, ventas, gastos, por cobrar y por pagar | Implementado |
| Business | Pyme con contador o despacho | Lo anterior más contabilidad, cierres, fiscal, activos, aprobaciones | Implementado en su mayoría; falta CFDI y conciliación |
| Enterprise | Grupo con varias razones sociales | Libros por entidad, dimensiones, segregación de funciones, consolidación | Ausente |

## Referentes

Oracle Fusion Cloud Financials, Oracle Cloud EPM, SAP S/4HANA Finance, Microsoft Dynamics 365 Finance, Odoo Accounting y CONTPAQi quedan como referentes de modularidad y de nomenclatura.

**Límite de esta entrega:** no se investigó la documentación vigente de esos productos ni la del SAT. Ninguna afirmación de este paquete sobre equivalencia funcional o normativa debe tomarse como verificada. La investigación es una tarea del backlog (`06_ROADMAP_BACKLOG.md`, épica de cumplimiento).

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Vender capacidades enterprise que no existen | Publicar sólo lo marcado como implementado en la auditoría |
| Perder la simplicidad del emprendedor al crecer hacia enterprise | Presets y niveles de experiencia; el vocabulario contable se queda dentro de Contabilidad |
| Afirmar cumplimiento fiscal sin validación | Revisión por contador y contra documentación oficial antes de cualquier copy fiscal |
| Dispersar esfuerzo en muchos módulos | Un módulo a la vez, con gate de invariantes |

## Decisiones pendientes

1. Subdominio y fecha de migración a `financials.atlastech.mx`.
2. Modelo de entidad legal (libro por razón social dentro del tenant, o una organización por razón social).
3. Planes comerciales y qué módulos entran en cada uno.
4. Si el presupuesto simple entra en Financials o espera a EPM.
