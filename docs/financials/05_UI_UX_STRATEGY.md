# 05 · Estrategia de UI/UX y presets

_Atlas ONE Financials (antes ARCA) · Corte: 2026-11-23 · Fase 0 — Discovery_

## Resumen ejecutivo

La interfaz actual ya cumple el nivel Entrepreneur: navegación en lenguaje de empresario, tablas con filtros y exportación, y la contabilidad formal aislada en su propia sección. La propuesta no rediseña; reorganiza la navegación por módulo para que crezca hacia Business y Enterprise, y define presets como **configuración** (módulos, vocabulario, navegación), nunca como código duplicado.

Los presets dependen de una pieza que hoy no existe: entitlements por organización.

## Estado actual (evidencia)

**Navegación** (`frontend/src/components/layout/AppLayout.tsx`):

```text
(sin sección)  Inicio · Asistente · Análisis · Agentes · Mis empresas
Dinero         Movimientos · Cuentas · Caja · Patrimonio · Importar
Ventas         Ingresos · Por cobrar · Clientes
Gastos         Gastos · Por pagar · Proveedores
Finanzas       Proyectos · Reportes · Contabilidad · Propuestas
```

**Pantallas:** 21 páginas en `frontend/src/features/` y 24 rutas.

**Sistema de diseño:**

- Tokens semánticos de Tailwind (`bg-surface`, `text-muted`…), sin colores crudos (`CLAUDE.md`).
- Cifras con `.figures` (Geist, `tabular-nums`); paneles con `.panel`.
- Marca por empresa mediante `[data-brand]` (`frontend/src/index.css`, `frontend/src/lib/brand.ts`).
- 20 componentes compartidos en `frontend/src/components/ui/`.

**Componentes reutilizables para densidad enterprise:** `Table`, `TableTools`, `ListFilters`, `Pagination`, `Money`, `StatusBadge`, `HistoryTimeline`, `JournalEntryModal`, `DimensionFields`, `CommandPalette`.

**Capacidades de experiencia ya presentes:** filtros en la URL, descarga a Excel, detalle con historial de cambios, vista del documento origen desde un movimiento, paleta de comandos, estados vacíos con acción.

## Arquitectura de información propuesta

El task pack sugiere once entradas en inglés. La interfaz es en español; se propone el mismo esqueleto traducido y mapeado a lo que existe.

| Entrada propuesta | Equivalente del task pack | Pantallas actuales que absorbe | Estado |
|---|---|---|---|
| Inicio | Overview | Inicio, Análisis | Existe |
| Contabilidad | Accounting | Contabilidad (catálogo, pólizas, balanza, cierres, apertura) | Existe |
| Por cobrar | Receivables | Ingresos, Por cobrar, Clientes | Existe |
| Por pagar | Payables | Por pagar, Proveedores | Existe |
| Tesorería | Treasury | Movimientos, Cuentas, Caja, Importar | Existe; falta conciliación |
| Fiscal | Tax | Reporte de IVA, exportaciones SAT y CONTPAQi (hoy dentro de Contabilidad y Reportes) | Parcial; falta CFDI |
| Gastos | Expenses | Gastos, Recurrentes | Existe |
| Activos | Assets | Patrimonio (activos fijos, préstamos) | Existe |
| Planeación | Planning | — | Ausente; no se muestra |
| Reportes | Reports | Reportes, Proyectos | Existe |
| Administración | Administration | Configuración, Equipo, Agentes, Mis empresas, Propuestas | Existe |

Reglas:

- Una entrada sólo aparece si el módulo está habilitado y el rol puede usarlo. Nunca se muestra un módulo vacío "próximamente".
- El asistente deja de ser una página aparte como único acceso: se ofrece también en contexto (panel lateral) sin sacar al usuario de su tarea.
- Propuestas conserva un contador visible en el encabezado, porque es trabajo pendiente y no configuración.

## Tres niveles de experiencia

| Aspecto | Entrepreneur | Business | Enterprise |
|---|---|---|---|
| Vocabulario | "Vendí", "gasté", "me deben" | Mixto; términos contables en Contabilidad y Fiscal | Contable y financiero completo |
| Navegación | Inicio, Dinero, Ventas, Gastos | Las once entradas, según módulos | Lo anterior más selector de entidad legal y libro |
| Densidad | Media; cifras protagonistas | Alta en tablas | Alta; dimensiones y filtros avanzados |
| Aprobaciones | Opcionales | Por monto | Por monto, entidad y segregación de funciones |
| Estado hoy | Implementado | Implementado en su mayoría | Ausente |

La base transaccional es la misma en los tres. Cambiar de nivel es cambiar configuración, no migrar datos.

## Navegación por rol

Roles vigentes: OWNER, ADMIN, ACCOUNTANT, MEMBER, VIEWER (`AGENTS.md`). Contabilidad sólo es visible para los tres primeros.

| Entrada | OWNER | ADMIN | ACCOUNTANT | MEMBER | VIEWER |
|---|---|---|---|---|---|
| Inicio | ✓ | ✓ | ✓ | ✓ | ✓ |
| Contabilidad, Fiscal | ✓ | ✓ | ✓ | — | — |
| Por cobrar, Por pagar, Gastos | ✓ | ✓ | ✓ | Captura con límite | Lectura |
| Tesorería | ✓ | ✓ | ✓ | Caja propia | Lectura |
| Activos, Reportes | ✓ | ✓ | ✓ | — | Lectura |
| Administración | ✓ | ✓ | Parcial | — | — |

Esta tabla es propuesta. El detalle vigente por endpoint está en `07_SECURITY_AND_COMPLIANCE.md` y la interfaz debe derivarlo de `/api/me`, no decidirlo por su cuenta.

## Flujos prioritarios

| Flujo | Nivel | Estado | Pendiente |
|---|---|---|---|
| Registrar venta o gasto y ver el efecto en el dinero | Entrepreneur | Existe | — |
| Cobrar o pagar un documento, total o parcial | Todos | Existe | — |
| Autorizar una operación por monto | Business | Existe | — |
| Cierre de mes | Business | Existe | Lista de verificación previa al cierre |
| Importar CFDI y convertirlo en gasto o ingreso | Business | Ausente | Diseño completo |
| Conciliar un estado de cuenta | Business | Ausente | Diseño completo |
| Cambiar de entidad legal y ver su libro | Enterprise | Ausente | Depende del ADR de entidad legal |

### Wireframe textual: importación de CFDI (propuesta)

```text
Fiscal › Comprobantes recibidos
┌──────────────────────────────────────────────────────────────────────┐
│ [Subir XML]  [Filtros: fecha · emisor · estado · tipo]   [Excel]      │
├────────┬──────────────┬──────────┬───────────┬──────────┬────────────┤
│ Fecha  │ Emisor       │ Total    │ IVA       │ Estado   │ Acción     │
│ 12 nov │ Proveedor SA │ 11,600.00│  1,600.00 │ Sin ligar│ Crear gasto│
│ 12 nov │ Papelería X  │    580.00│     80.00 │ Ligado   │ Ver gasto  │
│ 11 nov │ Renta Y      │ 23,200.00│  3,200.00 │ Duplicado│ Ver origen │
└────────┴──────────────┴──────────┴───────────┴──────────┴────────────┘
Detalle (panel lateral): datos del comprobante · conceptos · impuestos ·
gasto propuesto (categoría, cuenta, proveedor) · [Aprobar] [Rechazar]
```

### Wireframe textual: conciliación bancaria (propuesta)

```text
Tesorería › Conciliación › BBVA 1234 · noviembre 2026
Saldo según banco 245,300.00   Saldo en libros 243,120.00   Diferencia 2,180.00
┌───────────────────────────────┬──────────────────────────────────────┐
│ Estado de cuenta (sin ligar)  │ Movimientos en libros (sin ligar)     │
│ 03 nov  Depósito     5,800.00 │ 03 nov  Cobro F-102         5,800.00  │
│ 05 nov  Comisión       180.00 │ —  sugerencia: crear gasto "Comisión" │
│ 07 nov  SPEI         2,000.00 │ —  sin coincidencia                   │
└───────────────────────────────┴──────────────────────────────────────┘
[Ligar selección]  [Aceptar sugerencias]  [Cerrar conciliación]
```

En ambos flujos las sugerencias entran por el mecanismo de propuestas existente y nada se asienta sin aprobación.

## Presets

Un preset es un conjunto de valores de configuración. No existe como concepto en el código; hoy sólo hay `organizations.business_type` y `organizations.brand`.

| Preset | Módulos habilitados | Vocabulario | Particularidades |
|---|---|---|---|
| Emprendedor | Inicio, Dinero, Ventas, Gastos, Reportes básicos | Empresario | Contabilidad oculta; asistente al frente |
| PyME | Todo lo existente | Mixto | Aprobaciones por monto, cierres mensuales |
| Retail | PyME + cortes de caja, procesadores, unidades de negocio, importación de punto de venta | Mixto | Ya probado con La Fe (cortes, procesador, Toronja) |
| Servicios profesionales | PyME + proyectos, retenciones | Mixto | Rentabilidad por proyecto; retenciones de ISR e IVA |
| Grupo empresarial | Todo + entidad legal, dimensiones, consolidación | Contable | Depende de capacidades ausentes |

**Qué configura un preset:** módulos habilitados, entradas de navegación, catálogo de cuentas y categorías iniciales, etiquetas, valores por defecto de aprobaciones.

**Qué no puede hacer un preset:** bifurcar componentes, cambiar reglas contables ni sustituir la autorización del backend.

**Verificación:** cada preset debe poder expresarse como un documento de configuración sobre capacidades existentes. Los tres primeros y el de servicios ya son expresables; el de grupo empresarial no.

## Principios

- Tablas, filtros, búsqueda y exportación antes que tarjetas decorativas.
- Todo importe navega hasta su documento origen y su póliza.
- Estados explícitos (pendiente, pagado, cancelado, por autorizar) con el mismo componente en toda la aplicación.
- Formato monetario mexicano y cifras alineadas.
- Accesibilidad: contraste, foco visible, `prefers-reduced-motion` (ya respetado en Inicio).
- Copy en español; el nombre visible es Atlas ONE Financials.

## Decisiones pendientes

1. ¿Se adopta la navegación por módulo ahora o al introducir entitlements?
2. ¿El asistente en contexto es panel lateral o se mantiene sólo la página?
3. ¿Dónde se define un preset: tabla en base de datos o archivo versionado?
4. ¿Existe un sistema de diseño común de Atlas ONE al que haya que alinearse, o este repositorio es la referencia?

## Riesgos

- Reorganizar la navegación desorienta a usuarios activos; hacerlo junto con el cambio de nombre concentra el costo en un solo momento.
- Mostrar módulos no construidos erosiona la confianza.
- Un preset que necesite código propio deja de ser preset; es señal de que falta una capacidad configurable.
