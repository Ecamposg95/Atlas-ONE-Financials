# LaFe — Ronda 2: backlog de trabajo

_Fuente: feedback de Liza y Abraham (con validación fiscal de Jessica) y comentarios con capturas, entregados por Emmanuel el 2026-11-27. Reestructurado el mismo día, después de las entregas #37–#41, cotejando cada pendiente contra el código (`main` en `7dc77e1`) y contra los datos de La Fe en producción (solo lectura). Integra lo que sigue abierto de la ronda 1 ([`BACKLOG.md`](BACKLOG.md), matriz [`HAB-01_matriz.md`](HAB-01_matriz.md))._

**Objetivo:** que La Fe registre su operación financiera de forma ágil, corrija errores con control y consulte información confiable por sucursal.

**Cómo leer este documento.** El trabajo se organiza por lo que lo detiene, no por épica:

| Sección | Qué hay | Quién lo mueve |
|---|---|---|
| [1. Datos de La Fe](#1-lo-que-dicen-los-datos-de-la-fe-27-nov-2026) | El estado real de la operación | — |
| [2. Listo para desarrollar](#2-listo-para-desarrollar) | Tareas sin preguntas abiertas, agrupadas en lotes | Atlas |
| [3. Bloqueado](#3-bloqueado-por-una-persona-o-una-decisión) | Tareas que esperan una respuesta, agrupadas por persona | Jessica, Liza, dirección |
| [4. Operación sin desarrollo](#4-operación-sin-desarrollo-etapa-0) | Lo que La Fe tiene que capturar o revisar con lo que ya existe | La Fe con Atlas |
| [5. Investigación e integraciones](#5-investigación-e-integraciones) | Dictámenes y conexiones externas | Atlas |
| [6. Hecho](#6-hecho-en-la-ronda-2) | Lo entregado, con su PR | — |
| [7. Catálogo de historias](#7-catálogo-de-historias) | Cada historia con sus criterios y sus tareas | — |
| [8. Decisiones](#8-decisiones-abiertas-unificadas) | Las preguntas de ambas rondas, sin duplicados | Dirección y contabilidad |

**IDs.** Cada historia conserva su ID (R2·HU-05); cada tarea lleva una letra (HU-05.c). Lo que viene de la ronda 1 se marca **R1·**. Tamaño: **S** (horas a un día), **M** (unos días), **L** (una semana o más). Prioridad: **P0** bloquea la operación o la confiabilidad, **P1** mejora importante, **P2** sujeta a viabilidad.

---

## 1. Lo que dicen los datos de La Fe (27-nov-2026)

Consulta de solo lectura después de las entregas del día. Nada de esto cambia con desarrollo: cambia cuando La Fe usa lo que ya existe (sección 4).

| Hallazgo | Dato | Tareas |
|---|---|---|
| Ninguna cuenta por pagar se ha liquidado | 37 abiertas por $359,788; ninguna pagada ni parcial. 4 vencidas por $36,829; la más vieja, SEILAB 1876 ($741.66), del 10-oct | OP-02, HU-01.v |
| Saldos negativos o inflados | Bancomer −$651k, Santander −$697k, Caja central −$934k; NetPay +$1.25 M sin ninguna liquidación registrada | OP-01 |
| Aperturas provisionales | 13 de 15 cuentas en $0 provisional; solo Caja central confirmada ($27,407) | OP-01, HU-12.a |
| Las cajas de sucursal nunca se entregan | Un solo corte de caja (cancelado); cajas entre $74,711 (Haciendas) y $322,775 (Villas) | OP-04, HU-16.a, HU-16.b |
| IVA sin clasificar | Gastos: 313 sin clasificar y 43 gravados. Ingresos: 363 sin clasificar y 9 gravados. 0 retenciones capturadas | OP-05, HU-04.b, REQ-05 |
| La nómina es el gasto principal | 178 gastos por $1.26 M: 49 % del gasto | HU-06, HU-07 |
| Nunca se ha cerrado un periodo | 0 meses y 0 ejercicios cerrados | OP-03 |
| Operaciones con fecha futura | 2 ingresos ($9,000) y 2 gastos ($6,620) | REQ-04.a, REQ-04.b |
| El asistente de IA nunca estuvo activo | Sin `ANTHROPIC_API_KEY`; 0 conversaciones | TEC-06 |
| Patrimonio y préstamos sin uso | 0 activos fijos y 0 préstamos | HU-17 |
| La bitácora sí se usa | 829 registros desde el 3-nov (786 altas, 34 cambios, 7 cancelaciones) | — |

---

## 2. Listo para desarrollar

Sin preguntas abiertas. El orden de los lotes es la recomendación; dentro de un lote, las tareas son independientes.

### Lote A · Cifras confiables (todo S) — **Hecho (#43)**

Errores de cálculo que hacen que dos pantallas digan cosas distintas. Entregado el 27-nov: lo vencido usa la fecha de la empresa en todas partes; la póliza de saldo inicial va a la fecha de corte (si el mes de corte está cerrado, se rechaza); el desglose por categoría del resumen va sin IVA; lo pagado o cobrado, los traspasos, los pagos y los cobros no aceptan fecha futura (lo pendiente sí), las importaciones marcan esas filas como error, y Gastos e Ingresos avisan de lo pagado con fecha futura que ya existe.

| Tarea | Prior. | Qué | Dónde |
|---|---|---|---|
| HU-09.b | P0 | "Vencido" con la fecha de la empresa, no la del servidor. Hoy `date.today()` en 9 lugares; el panel de Inicio ya usa `local_today` | `payables/schemas.py:71`, `receivables/schemas.py:79`, `receivables/router.py:56,74`, `dashboard/service.py:52,109,214`, `portfolio/service.py:68`, `reports/router.py:16` |
| HU-12.a | P0 | Dar de alta una cuenta con saldo inicial registra la póliza hoy, no en la fecha de corte. Usar la fecha de corte, como ya hace el ajuste de apertura | `financial_accounts/service.py:58`, `opening/service.py` |
| HU-10.b | P1 | El desglose por categoría del resumen suma con IVA y el estado de resultados sin IVA. Sumar `subtotal` | `dashboard/service.py:168,282` |
| REQ-04.a | P1 | Validar fechas al capturar gastos, ingresos, traspasos, pagos y cobros. Propuesta: avisar y pedir confirmación si la fecha es futura (hoy solo las pólizas manuales la rechazan) | `{expenses,income,transactions,payables,receivables}/schemas.py` |
| REQ-04.b | P1 | Filtro o aviso "fecha futura" para revisar las 4 operaciones que ya existen | listados de operaciones |

### Lote B · Clasificar lo que ya está capturado

Hoy hay 676 operaciones sin clasificar. El lote de gastos ya existe; faltan ingresos, que son la mitad.

| Tarea | Prior. | Tam. | Qué | Dónde |
|---|---|---|---|---|
| HU-02.d | P0 | M | Corregir un ingreso cobrado con motivo (categoría, cliente, referencia, notas), igual que un gasto pagado. Hoy solo acepta proyecto y tratamiento, y el tratamiento no pide motivo | `income/service.py:307` |
| HU-04.b | P1 | M | Corrección en lote de ingresos (categoría, tratamiento de IVA, cliente, proyecto), con vista previa. Depende de HU-02.d | `expenses/service.py:362` como modelo, `BulkCorrectionModal.tsx` |
| HU-05.c | P1 | S | Tratamiento de IVA y retenciones en la exportación a Excel de gastos e ingresos | `services/listing.py:22`, `expenses/listing.py:75`, `income/listing.py` |
| HU-05.d | P1 | S | Exportar el reporte de IVA a Excel | `reports/router.py` |
| REQ-05.a | P1 | S | Ajuste en la configuración de Toronja para el tratamiento de IVA de lo importado (hoy fijo en tasa 0, sin clasificar). El valor lo decide Jessica (REQ-05.b) | `imports/service.py:593,617,888,909`, `ImportSettingsCard.tsx` |

### Lote C · Efectivo de sucursales

| Tarea | Prior. | Tam. | Qué | Dónde |
|---|---|---|---|---|
| HU-16.a | P1 | S | En "Nuevo gasto", proponer Caja central cuando se paga en efectivo | `OperationsPage.tsx:1263` |
| HU-16.b | P1 | M | Hacer obvio el corte diario → entrega a caja central: recordatorio de sucursales sin corte, entrega en un paso. El backend está completo | `cash_cuts/router.py`, `CashPage.tsx` |

### Lote D · Vencimientos

| Tarea | Prior. | Tam. | Qué |
|---|---|---|---|
| HU-09.c | P1 | S | Plazo de vencimiento en las reglas recurrentes, para que lo que generan aparezca en vencimientos |
| HU-09.d | P1 | S | Anticipación configurable para "por vencer" (hoy, la semana) |
| HU-02.a | P1 | M | Revertir un solo pago de una cuenta por pagar (y un cobro de una por cobrar). Hoy la cancelación revierte la cuenta completa (`payables/service.py:239`, `reversals.py`) |

### Lote E · Catálogos y edición

| Tarea | Prior. | Tam. | Qué |
|---|---|---|---|
| HU-15.a | P1 | M | Alta y edición de categorías desde la app, con bitácora (cierra REQ-03.b). Hoy solo `GET` |
| HU-18.a | P1 | S | Cliente Particular o Empresa, elegido antes del nombre, que cambia los datos fiscales que se piden |
| HU-19.a | P1 | M | Editar y eliminar proyectos; eliminar desasigna las operaciones, no las borra |
| HU-17.a | P1 | M | Editar activos fijos y préstamos (hoy solo crear, depreciar, dar de baja y pagar) |
| HU-08.a | P1 | S | Filtrar por varios proveedores a la vez (hoy, uno) |
| HU-08.b | P1 | M | Grupo de proveedores y vista "Laboratorios de referencia" |

### Lote F · Visibilidad

| Tarea | Prior. | Tam. | Qué |
|---|---|---|---|
| HU-10.a | P1 | M | Selector de periodo en el resumen (hoy fijo en el mes actual) |
| HU-13.b | P1 | S | Mostrar la procedencia (archivo y fila importada) en el detalle de la operación |
| R1·HU-22.a | P2 | S | Proyección de flujo: separar lo registrado de los supuestos |
| R1·HU-12.a | P2 | M | Detectar duplicados entre estados de cuenta que se traslapan |
| HU-14.a | P2 | S | Probar la conciliación bancaria actual con un estado de cuenta real (prueba, sin desarrollo; necesita el archivo) |

---

## 3. Bloqueado por una persona o una decisión

Agrupado por quién lo destraba, para llevarlo a una sola reunión con cada uno.

### Jessica (contabilidad y fiscal) — TEC-03

| Tarea | Prior. | Tam. | Qué se necesita de ella |
|---|---|---|---|
| HU-05.e | P0 | — | Clasificar los 313 gastos y 363 ingresos sin clasificar (con HU-04.b se hace en lote) |
| REQ-05.b | P1 | S | Qué tratamiento de IVA llevan las ventas de Toronja (¿servicios médicos exentos?) |
| HU-05.b | P1 | L | Cuentas y pólizas para retenciones en ingresos (lo que el cliente nos retiene) y en cuentas por pagar. En por pagar las columnas ya existen sin usarse |
| HU-02.c | P1 | M | Cómo reclasificar la sucursal de un gasto pagado (la póliza lleva una sola unidad) |
| HU-03.a | P1 | S | Si cancelar algo de un mes cerrado con reversa fechada hoy es el mecanismo compensatorio correcto, y si se permite subir un comprobante nuevo a un mes cerrado |
| HU-17.b, HU-17.c | P1 | M | Ligar activo con su financiamiento y anticipos; IVA de compras a crédito y de intereses; métodos de depreciación (decisión 4) |

### Liza

| Tarea | Prior. | Tam. | Qué se necesita de ella |
|---|---|---|---|
| HU-01.v (TEC-01) | P0 | S | Revisar las 37 cuentas por pagar, el caso SEILAB 1876 y validar los pagos parciales |
| HU-12.b (TEC-04) | P0 | M | Caso concreto del problema de saldos de apertura; decide si hace falta fecha de apertura por cuenta (decisión 6) |
| HU-13.a | P1 | M | Confirmar el 1-ago-2026 como fecha confiable para marcar periodos incompletos (decisión 6) |
| HU-11.a (TEC-07) | P1 | L | Qué significa "cubrir gastos" y cómo se reparten nómina y renta entre sucursales (decisión 10) |
| R1·HU-15 | P1 | M | Tasas pactadas con NetPay y Mercado Pago para validar comisiones (hoy `fee_rate` se guarda pero no se usa) |

### Dirección (Liza y Abraham)

| Tarea | Prior. | Tam. | Decisión |
|---|---|---|---|
| HU-02.b (TEC-02) | P0 | M | Quién autoriza cancelaciones y cambios, quién cierra y reabre (decisiones 1 y 2). Hoy cancelar solo pide rol de captura |
| HU-09.a | P1 | L | Canal, destinatarios y frecuencia de los recordatorios (decisión 8). No hay proceso programado ni canal |
| HU-16.c | P1 | S | Si las sucursales pagan gastos menores con su caja (decisión 12) |
| HU-15.b, HU-15.c | P1 | L | Subcategorías y si los renglones de una factura llevan categoría propia (decisión 11). Destraba la lectura del XML de facturas recibidas, que además completaría el IVA |
| HU-06.a, HU-07.a (TEC-05) | P1 | L | Formato de la carga de nómina y si HRFlow es la fuente de empleados (decisión 9) |

---

## 4. Operación sin desarrollo (etapa 0)

Con lo que ya existe en la plataforma. Es lo que más mueve las cifras de la sección 1.

| ID | Qué | Herramienta que ya existe | Con quién |
|---|---|---|---|
| OP-01 (REQ-01) | Confirmar aperturas de las 13 cuentas provisionales, registrar las liquidaciones de NetPay al banco y conciliar bancos | Aperturas, liquidaciones de procesador, conciliación bancaria | Liza |
| OP-02 | Revisar y pagar en la plataforma las 37 cuentas por pagar | Por pagar, pago por lote | Liza |
| OP-03 | Cerrar agosto, septiembre y octubre | Cierre de periodos | Jessica |
| OP-04 | Cortes de caja diarios con entrega a caja central | Cortes de caja | Sucursales |
| OP-05 | Clasificar el IVA pendiente | Filtro "IVA: sin clasificar" y corrección en lote | Jessica |
| TEC-06 | Activar el asistente: cargar `ANTHROPIC_API_KEY` en `/srv/apps/financials/.env` y fijar el tope mensual (ya existe en Configuración) | — | Emmanuel |

---

## 5. Investigación e integraciones

| ID | Prior. | Qué | Nota |
|---|---|---|---|
| HU-10.c | P1 | Conservar el número de atenciones de Toronja para tener ticket promedio | Hoy se importa un ingreso por sucursal, día y forma de pago |
| HU-14.b / TEC-08 | P2 | Conexión directa con el banco | La alternativa por archivo ya existe |
| R1·HU-21 | P2 | Conectores con NetPay y Mercado Pago | Sin dueño; TEC-09 solo pausa Toronja |
| R1·HU-12.b | P2 | Lectura de estados de cuenta en PDF | Requiere muestras reales |
| TEC-09 | Restricción | Pausar la integración con Toronja | No detener la importación de archivos |
| TEC-10 | Separado | Evaluar la propuesta del nuevo proveedor | Consultoría; no aprueba un ERP |
| R1·HAB-03 | P2 | Diccionario de movimientos, estados y reglas de saldo | Documento de Atlas |

---

## 6. Hecho en la ronda 2

Todo en producción el 27-nov-2026. Falta la validación funcional con La Fe (criterio de terminado).

| Entrega | PR | Qué quedó |
|---|---|---|
| REQ-02 · Por pagar | #37 | Columna de acciones fija; detalle y saldo al día tras pagar; pago con bloqueo de fila (también cobros); lo que espera autorización aparta saldo; pago por lote sin doble envío; aviso de posible duplicado al capturar un gasto |
| REQ-03 · Bitácora completa | #37 | Cierres y reaperturas, contactos, comprobantes, traspasos, permisos del equipo y reglas de autorización. Falta categorías (REQ-03.b, llega con HU-15.a) |
| HU-02 · Corregir lo pagado | #38 | Gasto pagado corrige categoría (con póliza de reclasificación), proveedor, referencia y notas con motivo; motivo obligatorio al cancelar; sustituir comprobante con traza |
| HU-03 · Mes cerrado | #38 | Gastos e ingresos pendientes respetan el mes y el ejercicio cerrados; quitar y sustituir comprobantes también |
| HU-05 · IVA explícito | #39 | Tratamiento (gravado, tasa 0, exento, no objeto, sin clasificar) en gastos, ingresos y cuentas; retenciones de gasto por tasa; desglose en detalle e historial; reporte de IVA por tratamiento con retenciones; filtro "IVA" |
| HU-04 · Corrección masiva | #40 | Gastos: categoría, IVA, proveedor y proyecto en lote, hasta 500, con vista previa y resultado por gasto |
| HU-20 · Totales | #41 | Por pagar y Por cobrar suman todo lo filtrado; Gastos e Ingresos suman sin cancelados; la selección suma entre páginas |
| Lote A · Cifras confiables (HU-09.b, HU-12.a, HU-10.b, REQ-04) | #43 | Vencido con la fecha de la empresa; apertura en la fecha de corte; categorías sin IVA; sin fechas futuras en lo pagado y aviso de las existentes |
| HU-21 · Búsqueda | #41 | Búsqueda siempre visible en Gastos e Ingresos; Ctrl K encuentra operaciones, cuentas y contactos por concepto, referencia, RFC o monto |

---

## 7. Catálogo de historias

Cada historia con su origen, criterios de aceptación y tareas. El estado vive en las secciones 2 a 6.

### Épica 1 · Pagos y correcciones con trazabilidad

**R2·HU-01 · Registrar y visualizar el pago de una cuenta** — P0 · Liza. Quiero registrar claramente que una obligación ya fue pagada, para distinguir lo pendiente de lo liquidado sin duplicar registros.
Criterios: acción visible para pagar; fecha, importe y cuenta de origen; estado y saldo actualizados; pago vinculado a la obligación; sin duplicados. → Hecho (REQ-02); pendiente HU-01.v.

**R2·HU-02 · Corregir o revertir un gasto pagado con autorización** — P0 · Abraham y Liza. Quiero solicitar la corrección o reversa de un gasto pagado, para atender errores o sustituciones de factura sin perder el historial.
Criterios: distinguir corregir datos, sustituir comprobante y revertir pago; motivo obligatorio; autorización del rol definido; bitácora de quién solicitó, autorizó y qué cambió; sin duplicar efectos. → Hecho en parte; pendientes HU-02.a, .b, .c, .d.

**R2·HU-03 · Cerrar periodos y controlar correcciones posteriores** — P0 · Abraham, Liza y Jessica. Quiero cerrar periodos y controlar sus modificaciones.
Criterios: cierre por usuario autorizado; sin edición ordinaria en periodo cerrado; correcciones por mecanismo compensatorio; reapertura con permisos y traza; el sistema explica el bloqueo. → Hecho; pendientes HU-03.a y OP-03.

**R2·HU-04 · Corregir gastos de forma masiva** — P1 · Liza.
Criterios: filtrar y seleccionar; solo campos autorizados; vista previa; respetar permisos, estados y cierres; resultado con actualizados, rechazados y motivos. → Hecho para gastos; pendiente HU-04.b (ingresos). Monto, fecha y cuenta no se corrigen en lote, por diseño.

### Épica 2 · Información fiscal estructurada

**R2·HU-05 · Capturar IVA y retenciones de manera explícita** — P0 · Abraham, Liza y Jessica.
Criterios: subtotal, trasladados, retenciones y total; retenciones con tipo, tasa o importe; exento y no objeto; "sin clasificar" como pendiente; desglose en detalle y salidas contables; casos aprobados por contabilidad. → Hecho en gastos; pendientes HU-05.b, .c, .d, .e. El sistema pide el total y calcula el desglose. No se infieren impuestos por el medio de pago.

### Épica 3 · Captura eficiente y organización de gastos

**R2·HU-06 · Cargar comprobantes de nómina por lote** — P1 · Abraham. Lote en el formato acordado, revisión previa, duplicados e inválidos detectados, asociación a empleado y periodo, reintento de errores. Si es CFDI de nómina, el duplicado se detecta por UUID. → HU-06.a.

**R2·HU-07 · Administrar nómina desde una sección propia** — P1 · Abraham. Consulta por empleado y periodo, sin perder la clasificación como gasto, migración sin recaptura y totales iguales. El agente de Tesorería busca la categoría por el texto "Nómina": renombrarla lo rompe. No calcula ni timbra nómina. → HU-07.a.

**R2·HU-08 · Administrar gastos de laboratorios de referencia** — P1 · Abraham. Vista propia filtrada por laboratorio, periodo y sucursal; importes consolidados una vez. Basta una vista, no un módulo. → HU-08.a, .b.

**R2·HU-15 · Desglosar cada factura de gasto en conceptos** — P1 · comentario sobre "Factura SEILAB RM355". Renglones con pieza, cantidad, precio unitario e importe; subcategorías administrables. La vía más barata es leer el XML de la factura recibida (trae conceptos, IVA y retenciones); el lector de CFDI actual sirve de base. → HU-15.a, .b, .c.

### Épica 4 · Vencimientos y seguimiento

**R2·HU-09 · Recibir recordatorios de pagos próximos a vencer** — P1 · Abraham. Anticipación configurable; próximos y vencidos; lo liquidado deja de avisar; destinatario y canal. Reglas de fecha, sin IA. Incluye el aviso del lunes de R1·HU-17. → HU-09.a, .b, .c, .d.

### Épica 5 · Visibilidad financiera por sucursal

**R2·HU-10 · Dashboard intuitivo por sucursal** — P1 · Abraham y Liza. Selector de sucursal y periodo; ingresos, gastos y categorías; ticket promedio si hay datos; del resumen al detalle; totales iguales a la fuente. → HU-10.a, .b, .c.

**R2·HU-11 · Visualizar la cobertura de gastos operativos** — P1 · Liza y Abraham. Llamarla "cobertura operativa", no "punto de equilibrio". → HU-11.a.

**R2·HU-12 · Gestionar saldos y fechas de apertura por cuenta** — P0 investigación · Liza. → HU-12.a, HU-12.b, OP-01.

**R2·HU-13 · Distinguir históricos completos e incompletos** — P1 · Liza. Fecha confiable documentada, periodos incompletos marcados, procedencia conservada, advertencia en indicadores. → HU-13.a, .b.

**R2·HU-16 · Concentrar el efectivo de sucursales en caja central** — P1 · comentario sobre "Nuevo gasto". → HU-16.a, .b, .c, OP-04.

**R2·HU-17 · Vincular patrimonio con su financiamiento y su depreciación** — P1 · comentario sobre patrimonio. Ya existen el IVA de la compra de contado y la separación de capital e intereses en cada pago. → HU-17.a, .b, .c.

**R2·HU-18 · Clasificar clientes como Particular o Empresa** — P1 · comentario sobre "Nuevo cliente". → HU-18.a.

**R2·HU-19 · Editar y eliminar proyectos** — P1 · comentario sobre "Proyectos". El monto acordado es el presupuesto del proyecto. → HU-19.a.

**R2·HU-20 · Totales de lo filtrado y lo seleccionado** y **R2·HU-21 · Buscar en ingresos y en general** — P1 · comentarios sobre "Por pagar". → Hechos (#41). Movimientos aún no tiene totales en el pie.

### Épica 6 · Integraciones controladas

**R2·HU-14 · Conciliar movimientos bancarios con obligaciones** — P2 · Abraham. Existe casi entera por archivo. → HU-14.a, HU-14.b.

### Requerimientos y trabajo técnico

| ID | Qué | Estado |
|---|---|---|
| REQ-01 | Saldos confiables | OP-01 (las herramientas existen) |
| REQ-02 | Errores de cuentas por pagar | Hecho (#37) |
| REQ-03 | Bitácora completa | Hecho (#37); REQ-03.b con HU-15.a |
| REQ-04 | Operaciones con fecha futura | REQ-04.a, .b |
| REQ-05 | IVA de lo importado de Toronja | REQ-05.a, .b |
| TEC-01 a TEC-10 | Descubrimiento y técnicos | Ver secciones 3 a 5 |

### De la ronda 1

Casi toda la ronda 1 está hecha o la reemplaza una historia de esta ronda. Lo que sigue abierto ya está arriba como **R1·**:

| R1 | Estado |
|---|---|
| HU-01, HU-02, HU-04, HU-05, HU-06, HU-08, HU-09, HU-10, HU-11, HU-13, HU-14, HU-16, HU-18, HU-19, HU-20 | Hechas; sus mejoras viven en R2 |
| HU-03, HU-21 (Toronja), HAB-04 a HAB-08 | Reemplazadas por R2·HU-12, REQ-01, TEC-02 a TEC-10 |
| HU-07 corte de caja | Construido sin uso → R2·HU-16 |
| HU-17 planeación semanal | Hecha; el aviso del lunes → R2·HU-09 |
| HU-12 carga bancaria | Hecha; quedan R1·HU-12.a y .b |
| HU-15 comisiones | Abierta → R1·HU-15 (bloqueada por Liza) |
| HU-21 NetPay y Mercado Pago | Abierta → R1·HU-21 |
| HU-22 proyección de flujo | Casi hecha; queda R1·HU-22.a |
| HAB-02 inventario de formatos | Parcial; falta nómina y bancos |
| HAB-03 diccionario de datos | Abierta → R1·HAB-03 |

---

## 8. Decisiones abiertas (unificadas)

Une las 7 de la ronda 1 y las 9 de la ronda 2. Ninguna está cerrada.

| # | Decisión | Quién | Destraba |
|---|---|---|---|
| 1 | Qué campos se corrigen directo y cuáles exigen reversa. Propuesta aplicada: categoría, proveedor, referencia y notas directo con motivo; monto, fecha y cuenta con reversa. Sucursal, pendiente de HU-02.c | Dirección y Jessica | Confirmar lo hecho |
| 2 | Quién autoriza cambios y cancelaciones, quién cierra y reabre periodos; umbral aprobado (¿$100,000?, ¿qué pasa con exactamente $100,000?) y restricciones del auxiliar | Dirección | HU-02.b, TEC-02 |
| 3 | Criterio contable: base de efectivo o devengo; tratamiento de préstamos e inversiones | Jessica | TEC-03 |
| 4 | IVA y retenciones: casos aprobados, ventas de Toronja, compras a crédito, intereses y depreciación | Jessica | HU-05.b, REQ-05.b, HU-17.b, HU-17.c |
| 5 | Conciliación: cuentas, referencias, depósitos agrupados y tiempos de liquidación de NetPay y Mercado Pago | Liza | OP-01, R1·HU-15 |
| 6 | Arranque: fecha confiable (los datos respaldan el 1-ago-2026), caso concreto de aperturas y quién valida saldos | Liza | HU-12.b, HU-13.a |
| 7 | Excepciones: devoluciones, contracargos y cancelaciones | Dirección y Jessica | HU-02.a (se puede construir antes) |
| 8 | Avisos: canal, destinatarios, frecuencia y anticipación | Dirección | HU-09.a |
| 9 | Nómina: formato de la carga y si HRFlow es la fuente de empleados | Abraham | HU-06.a, HU-07.a |
| 10 | Cobertura operativa: qué es "cubrir gastos" y cómo se reparten los gastos comunes | Liza y Abraham | HU-11.a |
| 11 | Factura: categoría por renglón o por factura; qué subcategorías | Dirección y Jessica | HU-15.b, HU-15.c |
| 12 | Caja de sucursal: ¿pagan gastos menores con su caja o todo sale de caja central? | Dirección | HU-16.c |

## 9. Criterio de terminado común

- Validación funcional con Liza o Abraham; fiscal y contable con Jessica.
- Permisos comprobados.
- Sin pérdida ni duplicación de información existente.
- Saldos y reportes consistentes.
- Bitácora en operaciones sensibles.
- Instrucciones de uso actualizadas.
- Evidencia de pruebas y aceptación del cambio.

Recomendación: los lotes A y B y la etapa 0 antes que cualquier tablero. Un dashboard más atractivo no resuelve saldos, impuestos o estados de pago ambiguos.
