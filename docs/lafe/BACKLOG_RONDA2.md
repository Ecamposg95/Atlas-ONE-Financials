# LaFe — Ronda 2: backlog a partir del feedback de Liza y Abraham

_Fuente: backlog de feedback de Liza y Abraham (con validación fiscal de Jessica) y comentarios con capturas de pantalla, entregados por Emmanuel el 2026-11-27. Cotejado ese día contra el código (`main` en `87a5fac`) y contra los datos de La Fe en producción (solo lectura). Continúa [`BACKLOG.md`](BACKLOG.md) (ronda 1) y su matriz [`HAB-01_matriz.md`](HAB-01_matriz.md)._

Los identificadores de esta ronda llevan el prefijo **R2** (R2·HU-01…) para no chocar con los de la ronda 1.

**Objetivo:** que La Fe registre su operación financiera de forma ágil, corrija errores con control y consulte información confiable por sucursal.

**Prioridades:** P0 bloquea la operación o compromete la confiabilidad; P1 mejora importante; P2 evolución sujeta a definición o viabilidad. "Por validar" no entra a desarrollo sin resolver sus preguntas. Los roles son funcionales y se mapean a los de Atlas (Dueño, Administrador, Contador, Captura, Consulta).

---

## 1. Lo que dicen los datos de La Fe (27-nov-2026)

| Hallazgo | Dato | Historias |
|---|---|---|
| Ninguna cuenta por pagar se ha liquidado | 37 abiertas por $359,788; ninguna pagada ni parcial; 4 vencidas (la más vieja, SEILAB 1876, del 10-oct) | R2·HU-01 |
| La columna de acciones de "Por pagar" queda cortada | En la captura de "Vencidas" el botón **Registrar pago** aparece como "Re" al borde derecho | R2·HU-01, TEC-01 |
| Saldos negativos o inflados | Bancomer −$651k, Santander −$697k, Caja central −$934k; NetPay +$1.25 M sin ninguna liquidación registrada; 13 de 15 cuentas con apertura provisional en $0 | R2·HU-12, R2·HU-13, R2·REQ-01 |
| Las cajas de sucursal nunca se entregan | Un solo corte de caja (cancelado); cajas de sucursal acumulan entre $74k y $323k cada una | R2·HU-16 |
| IVA sin capturar | 313 de 356 gastos con tasa 0, retenciones en cero en todos; 49 mencionan IVA o retención en notas | R2·HU-05, R2·HU-15 |
| La nómina es el gasto principal | 178 gastos por $1.26 M (≈ 46 % del gasto), todos en la categoría "Nómina" | R2·HU-06, R2·HU-07 |
| Nunca se ha cerrado un periodo | 0 meses y 0 ejercicios cerrados | R2·HU-03 |
| El asistente de IA nunca estuvo activo | Ni Railway ni IONOS tuvieron `ANTHROPIC_API_KEY`; 0 conversaciones y 0 llaves de agente | TEC-06 |
| Operaciones con fecha futura | 2 ingresos ($9,000) y 2 gastos ($6,620) | R2·HU-13 |
| Patrimonio y préstamos sin uso | 0 activos fijos y 0 préstamos registrados | R2·HU-17 |

---

## 2. Historias del backlog y su estado en la plataforma

Leyenda: **Existe** · **Parcial** · **Falta**.

### Épica 1 · Pagos y correcciones con trazabilidad

**R2·HU-01 · Registrar y visualizar el pago de una cuenta** — P0 · Liza · **Existe, con errores y problema de visibilidad.**

Como responsable de cuentas por pagar, quiero registrar claramente que una obligación ya fue pagada, para distinguir lo pendiente de lo liquidado sin duplicar registros.

- Criterios: acción visible para pagar; fecha, importe y cuenta de origen; estado y saldo actualizados en detalle y listados; pago vinculado a la obligación; sin pagos duplicados.
- Existe: "Registrar pago" en la fila y en el detalle (`DebtsPage.tsx`, `DebtDetailPanel.tsx`), pagos parciales, estados PARCIAL/PAGADA, saldo calculado, historial de pagos, pago por lote. Backend `POST /payables/{id}/pay` rechaza pagos mayores al saldo.
- Errores corregidos (R2·REQ-02):
  - La columna de acciones queda fija a la derecha; el concepto largo se corta a dos líneas.
  - El detalle se vuelve a pedir tras un pago y el formulario propone el saldo al día.
  - El pago bloquea la fila de la cuenta (también el cobro en Por cobrar).
  - Lo que espera autorización aparta saldo: una propuesta que no cabe se rechaza antes de llegar a la bandeja, y quien autoriza tampoco paga encima de lo apartado.
  - El botón del pago por lote se desactiva mientras corre.
- Riesgo de duplicado: si los pagos se capturan como gastos sueltos, el gasto cuenta dos veces y la cuenta sigue abierta. Ya hay aviso en el formulario de gasto cuando proveedor y monto coinciden con una cuenta por pagar abierta, con liga a la cuenta.
- Por validar: pagos parciales y el caso concreto (TEC-01: revisar SEILAB 1876 con Liza).

**R2·HU-02 · Corregir o revertir un gasto pagado con autorización** — P0 · Abraham y Liza · **Parcial.** Depende de R2·HU-03.

Como responsable administrativo, quiero solicitar la corrección o reversa de un gasto pagado, para atender errores o sustituciones de factura sin perder el historial.

- Criterios: distinguir corregir datos, sustituir comprobante y revertir pago; motivo obligatorio y relación con el original; autorización del rol definido; bitácora de quién solicitó, autorizó y qué cambió; saldos y reportes sin duplicar efectos.
- Existe: cancelar un pagado genera la reversa con fecha de hoy y conserva el historial (`reversals.py`); bitácora `change_log`.
- Hecho (27-nov, con la propuesta de la decisión 1; se ajusta si el refinamiento decide otra cosa):
  - Un gasto pagado corrige categoría, proveedor, referencia y notas con motivo obligatorio, mientras el mes esté abierto. La categoría genera una póliza de reclasificación en la fecha del gasto, ligada a él: si después se cancela, su reverso también se deshace. Monto, fecha, concepto y cuenta siguen exigiendo reversa.
  - Motivo obligatorio al cancelar gastos, ingresos, cuentas por pagar y por cobrar.
  - Sustituir comprobante: el anterior queda dado de baja, el cambio y su motivo en el historial; bloqueado en mes cerrado.
- Falta:
  - Corregir la sucursal de un pagado: la póliza lleva una sola unidad y moverla exige una reclasificación entre unidades. Validar con Jessica.
  - Autorización para cancelar (decisión 2): las autorizaciones solo cubren crear o pagar gastos, pagar cuentas por pagar y traspasos.
  - Revertir un solo pago de una cuenta por pagar: los pagos comparten origen con la cuenta y hoy el reverso es de todo.
- Propuesta para la decisión 1: categoría, sucursal, notas y referencia se corrigen directo con bitácora mientras el periodo esté abierto; monto, fecha y cuenta solo con reversa.

**R2·HU-03 · Cerrar periodos y controlar correcciones posteriores** — P0 · Abraham, Liza y Jessica · **Existe, con huecos; sin uso.**

Como responsable contable, quiero cerrar periodos y controlar sus modificaciones, para evitar cambios no autorizados sobre información ya cerrada.

- Criterios: cierre por usuario autorizado; sin edición ordinaria en periodo cerrado; correcciones por mecanismo compensatorio aprobado por contabilidad; reapertura con permisos y trazabilidad; el sistema explica el bloqueo.
- Existe: cierre y reapertura de meses y ejercicios (roles contables), reapertura con motivo, bloqueo central en el motor contable con mensaje claro.
- Huecos:
  - ~~Los gastos pendientes se crean y editan en un mes cerrado, porque no generan póliza.~~ Resuelto: gastos e ingresos pendientes respetan el mes y el ejercicio cerrados al crearse, editarse o cambiar de fecha.
  - Cancelar algo de un mes cerrado registra la reversa con fecha de hoy. Puede ser justo el mecanismo compensatorio; confirmarlo con Jessica.
  - ~~Cierre y reapertura no quedan en la bitácora.~~ Resuelto en R2·REQ-03.
  - ~~El bloqueo de comprobantes solo revisa el ejercicio, no el mes.~~ Quitar y sustituir revisan mes y ejercicio. Subir uno nuevo a un mes cerrado sigue permitido (completar evidencia faltante); confirmar con Jessica.
- Por validar con Jessica: reglas del periodo abierto, fechas de aplicación y pólizas inversas. Cambiar de mes no equivale a cerrar.

**R2·HU-04 · Corregir gastos de forma masiva** — P1 · Liza · **Falta.** Depende de R2·HU-02 y R2·HU-03.

- Criterios: filtrar y seleccionar; solo campos autorizados; vista previa; respetar permisos, estados y cierres; resultado con actualizados, rechazados y motivos.
- **Hecho (27-nov):** en Gastos, "Corregir en lote" cambia categoría, tratamiento de IVA, proveedor y proyecto de los gastos seleccionados, con motivo obligatorio. Se puede seleccionar más allá de la página: todos los que coinciden con el filtro, hasta 500. Primero hay una vista previa que no cambia nada; al aplicar, cada gasto pasa por las reglas de la corrección individual (estado, mes cerrado, IVA coherente, reclasificación). El resultado dice cuántos se corrigieron, cuántos ya tenían esos datos y cuáles no se pudieron corregir y por qué (`POST /expenses/bulk-update`).
- Falta: lo mismo para ingresos; los datos que mueven dinero (monto, fecha, cuenta) siguen sin corregirse en lote, por diseño.

### Épica 2 · Información fiscal estructurada

**R2·HU-05 · Capturar IVA y retenciones de manera explícita** — P0 · Abraham, Liza y Jessica · **Parcial.**

- Criterios: subtotal, trasladados, retenciones y total; retenciones con tipo, tasa o importe; tratamientos exento y no objeto; "sin clasificar" como pendiente de revisión; desglose en detalle y salidas contables; casos aprobados por contabilidad.
- Existe: en gastos, tasa 16/8/0 % y retenciones ISR e IVA como importes; las pólizas las registran bien (`rules.py`).
- Hecho (27-nov):
  - Tratamiento de IVA en gastos, ingresos y cuentas por pagar y por cobrar: gravado, tasa 0, exento, no objeto o sin clasificar. Lo que estaba en 0 % quedó **sin clasificar** (la migración no decide que algo es exento).
  - Lo pagado se clasifica desde el detalle sin cancelarlo, porque no cambia el IVA; un gasto pide motivo y el mes debe estar abierto.
  - Retenciones de gasto por tasa sobre la base (ISR 10 % y 1.25 %; IVA 2/3, 4 % y 6 %) o por importe; si vienen ambos y no coinciden, se rechaza.
  - Desglose en el detalle (base, IVA, tratamiento y retenciones) y en el historial.
  - Reporte de IVA: retenciones del periodo, base por tratamiento y aviso con liga a lo sin clasificar; filtro "IVA" en Gastos e Ingresos.
- Falta:
  - Retenciones en ingresos (lo que el cliente nos retiene) y en cuentas por pagar: requieren cuentas y pólizas que valida Jessica.
  - Retenciones y tratamiento en la exportación a Excel.
  - Que Jessica clasifique los gastos e ingresos sin clasificar.
- Importaciones de Toronja: fijan IVA 0. Muchos servicios médicos podrían ser exentos; lo confirma Jessica, no el sistema.
- Decisión: la historia pide capturar el subtotal; el sistema pide el total y calcula el desglose.
- Por validar: no deducibles y efectivo. No inferir impuestos por el medio de pago (hoy no se infiere).

### Épica 3 · Captura eficiente y organización de gastos

**R2·HU-06 · Cargar comprobantes de nómina por lote** — P1 · Abraham · **Falta.**

- Criterios: lote en el formato acordado; revisión previa; duplicados e inválidos detectados; asociación a empleado y periodo; reintento solo de los errores.
- No hay empleados, recibos ni lectura de XML de nómina. Si el formato es el CFDI de nómina timbrado, se lee directo y el duplicado se detecta por UUID.

**R2·HU-07 · Administrar nómina desde una sección propia** — P1 · Abraham · **Falta.**

- Criterios: acceso propio; consulta por empleado y periodo; se conserva la clasificación como gasto; migración sin recaptura; totales iguales antes y después.
- Hoy la nómina es solo una categoría de gasto. El agente de Tesorería la busca por el texto literal "Nómina": renombrarla lo rompe.
- Antes de crear empleados en Financials, acordar que HRFlow sea la fuente de empleados y periodos (eventos `rrhh.nomina.*` del megaplan CFDI, aún sin receptor).
- Límite: no calcula ni timbra nómina.

**R2·HU-08 · Administrar gastos de laboratorios de referencia** — P1 · Abraham · **Parcial, chica.**

- Criterios: vista propia; filtros por laboratorio, periodo y sucursal; relación con comprobantes y pagos; importes consolidados una sola vez.
- Los proveedores (SEILAB, Diagnóstica, Duolab) ya existen; sus gastos caen en "Inventario". Falta un grupo o etiqueta de proveedores y filtrar varios a la vez (hoy, uno). Basta una vista; no justifica módulo.

### Épica 4 · Vencimientos y seguimiento

**R2·HU-09 · Recibir recordatorios de pagos próximos a vencer** — P1 · Abraham · **Parcial.**

- Criterios: vencimiento o plazo; anticipación configurable; próximos y vencidos; lo liquidado deja de avisar; destinatario y canal.
- Existe: fecha de vencimiento obligatoria en cuentas por pagar y por cobrar, cálculo de vencidos, panel de la semana.
- Falta: cualquier proceso programado y cualquier canal de aviso. Recurrentes sin fecha de vencimiento.
- Corregir: "vencido" usa la fecha del servidor y el panel de Inicio la de la empresa.
- Diseño: reglas de fecha, sin depender de IA.

### Épica 5 · Visibilidad financiera por sucursal

**R2·HU-10 · Dashboard intuitivo por sucursal** — P1 · Abraham y Liza · **Parcial.**

- Criterios: selector de sucursal y periodo; ingresos, gastos y categorías; ticket promedio si hay datos; del resumen al detalle; totales iguales a la fuente.
- Existe: panel de sucursales (ventas del mes, comparativo, tendencia, estado de cortes), filtro por sucursal en resumen y reportes, liga a ingresos por sucursal.
- Falta: selector de periodo (el resumen está fijo en el mes actual).
- Inconsistencia: el desglose por categoría suma con IVA y el estado de resultados sin IVA.
- Ticket promedio imposible hoy: Toronja se importa como un ingreso por sucursal, día y forma de pago y descarta el número de atenciones. Habría que conservarlo.

**R2·HU-11 · Visualizar la cobertura de gastos operativos** — P1 · Liza y Abraham · **Falta; requiere definición.**

- Criterios: gastos incluidos por sucursal y periodo; base usada; avance, diferencia y estado; fecha en que se alcanza; advertencia por falta de datos; sin recuperación de inversión.
- No hay presupuestos por sucursal. Casi todos los gastos tienen sucursal (355 de 356), pero nómina y renta probablemente deban repartirse; definir la regla.
- Si se compara ventas contra gastos fijos, llamarlo "cobertura operativa", no "punto de equilibrio".

**R2·HU-12 · Gestionar saldos y fechas de apertura por cuenta** — P0 investigación · Liza · **Por validar.**

- Hoy hay una sola fecha de corte por empresa; no existe fecha de apertura por cuenta.
- Error encontrado: dar de alta una cuenta con saldo inicial registra la póliza con fecha de hoy, no en la fecha de corte, y sin movimiento de dinero. Puede ser lo que observó Liza.
- Los saldos negativos vienen de aperturas pendientes y de que nunca se registró cuándo NetPay deposita al banco (ver R2·REQ-01).
- Antes de desarrollar: caso concreto con Liza (TEC-04).

**R2·HU-13 · Distinguir históricos completos e incompletos** — P1 · Liza · **Falta.**

- Criterios: fecha confiable documentada (Liza propuso agosto); periodos incompletos marcados; lo importado no queda conciliado; procedencia conservada; advertencia en indicadores.
- Los gastos de La Fe empiezan el 1-ago-2026, lo que respalda agosto. Lo importado no queda conciliado por omisión y la procedencia vive en las filas de importación, no en la operación. No existe concepto de cobertura. Revisar las 4 operaciones con fecha futura.

### Épica 6 · Integraciones controladas

**R2·HU-14 · Conciliar movimientos bancarios con obligaciones** — P2 · Abraham · **Existe casi entera.**

- Existe: importar estados de cuenta CSV/XLSX, sugerencias de coincidencia con justificación, revisión humana, registro de quién confirmó; no inicia transferencias.
- Falta: conexión directa con el banco. Primer paso: usar la conciliación actual con un estado de cuenta real. La conexión sigue condicionada a viabilidad y seguridad.

---

## 3. Comentarios adicionales del equipo (27-nov, con capturas)

**R2·HU-15 · Desglosar cada factura de gasto en conceptos** — P1 · origen: comentario sobre "Factura SEILAB RM355".

Como responsable administrativo, quiero desglosar una factura en sus conceptos (pieza o unidad, cantidad, precio unitario e importe), para saber qué se compra y a qué precio sin depender de las notas, que no se ven.

- Hoy un gasto o cuenta por pagar es un solo monto con una categoría; no hay renglones. Las notas no aparecen en el detalle.
- Pidieron además una subcategoría "Gastos operativos". Las categorías son planas, sin subcategorías ni alta desde la interfaz. En la captura, "Inventario" ya se registra en la cuenta 5100 Gastos Operativos.
- Propuesta: categorías con subcategorías administrables, y renglones por factura. La vía más barata es **leer el XML de la factura recibida**, que trae conceptos, cantidades, precios, IVA y retenciones. Eso resuelve a la vez esta historia y buena parte de R2·HU-05. En la ronda 1 la lectura de XML quedó fuera del MVP; el plan maestro la tiene como módulo E. Se propone adelantarla.
- Por validar: si cada renglón lleva su propia categoría o la factura completa una sola.

**R2·HU-16 · Concentrar el efectivo de sucursales en caja central** — P1 · origen: comentario sobre "Nuevo gasto".

Como dirección, quiero que el efectivo de cada sucursal se entregue a caja central y de ahí se distribuyan los pagos, para saber cuánto efectivo hay realmente y desde dónde se paga.

- Existe: corte de caja por sucursal con entrega como traspaso caja → caja central o banco (`cash_cuts`), y pagar desde cualquier cuenta.
- Uso: La Fe tiene un solo corte, cancelado. Por eso las cajas de sucursal acumulan entre $74k y $323k y Caja central está en −$934k.
- Falta: hacer el flujo obvio (corte diario → entrega a caja central) y, en "Nuevo gasto", proponer Caja central cuando se paga en efectivo.
- Por validar: si las sucursales pagan gastos menores con su propia caja.

**R2·HU-17 · Vincular patrimonio con su financiamiento y su depreciación** — P1 · origen: comentario sobre patrimonio.

Como responsable administrativo, quiero que un activo comprado a crédito (por ejemplo, un vehículo) quede ligado a sus pagos futuros, para controlar lo que falta pagar, el IVA, los intereses y la depreciación desde un solo lugar.

- Existe: activos fijos con vida útil en meses, valor de rescate, depreciación en línea recta y baja; préstamos con tabla de amortización y pagos. Ninguno se usa en La Fe.
- Falta:
  - Ligar el activo al préstamo o a la cuenta por pagar que lo financia.
  - Anticipos aplicados a esa deuda.
  - IVA de la compra y separación de intereses en cada pago.
  - Elegir el método o plazo de depreciación.
  - Editar activos y préstamos (hoy solo crear, depreciar, dar de baja y pagar).
- Por validar con Jessica: tratamiento del IVA de compras a crédito, intereses y métodos de depreciación aceptados.

**R2·HU-18 · Clasificar clientes como Particular o Empresa** — P1 · origen: comentario sobre "Nuevo cliente".

- Criterio: el tipo se elige antes del nombre y cambia qué datos fiscales se piden.
- Hoy el cliente no tiene tipo. Puede deducirse del RFC (13 caracteres persona física, 12 moral), pero se pidió explícito.
- Encaja con los datos fiscales del CFDI (régimen, uso de CFDI).

**R2·HU-19 · Editar y eliminar proyectos** — P1 · origen: comentario sobre "Proyectos".

- Criterio: modificar nombre, cliente, monto acordado y costos del proyecto, o eliminarlo.
- Hoy solo se puede crear y cerrar un proyecto; no hay edición ni eliminación. Los costos salen de los gastos asignados.
- Eliminar un proyecto con operaciones debe desasignarlas, no borrarlas.

**R2·HU-20 · Totales de lo filtrado y de lo seleccionado** — P1 · origen: comentario sobre "Por pagar".

- Criterio: al filtrar y al seleccionar filas, ver la suma de lo visible y de lo seleccionado, en Por pagar y en las demás listas de operaciones.
- **Hecho (27-nov):**
  - Por pagar y Por cobrar: las tarjetas de saldo y vencido suman todo lo filtrado (antes, sólo la página visible).
  - Gastos e Ingresos: el pie de la tabla suma todo lo filtrado sin contar cancelados.
  - La barra de selección muestra la suma de lo seleccionado, aunque esté en varias páginas.

**R2·HU-21 · Buscar en ingresos y en general** — P1 · origen: comentario sobre "Por pagar".

- Criterio: buscar por concepto en Ingresos igual que en Gastos, y un buscador general que encuentre ingresos y gastos.
- **Hecho (27-nov):**
  - La búsqueda de Gastos e Ingresos estaba escondida dentro del panel "Filtros"; ahora está siempre a la vista.
  - El buscador general (Ctrl K) encuentra ingresos, gastos, cuentas por pagar y cobrar, clientes y proveedores, por concepto, referencia, notas, nombre, RFC o monto. Abre directo el detalle (`GET /search`).

---

## 4. Lo que el backlog no incluía y se agrega

| ID | Prioridad | Trabajo | Por qué |
|---|---|---|---|
| R2·REQ-01 | P0 | Saldos confiables: confirmar aperturas, registrar liquidaciones de NetPay al banco y conciliar bancos | Sin esto, ningún tablero ni indicador es confiable |
| R2·REQ-02 | P0 | Corregir los errores de cuentas por pagar listados en R2·HU-01 | **Hecho.** Falta validar con Liza (TEC-01) |
| R2·REQ-03 | P0 | Bitácora completa: cierres y reaperturas, cambios de autorizaciones, comprobantes, traspasos, categorías y contactos | **Hecho**, salvo categorías: hoy no se crean ni editan desde la app (llega con R2·HU-15). Faltan las cancelaciones con autorización (R2·HU-02) |
| R2·REQ-04 | P1 | Revisar las operaciones con fecha futura y validar fechas al capturar | Distorsionan saldos y reportes |
| R2·REQ-05 | P1 | IVA de lo importado desde Toronja según el tratamiento aprobado | Hoy entra siempre en 0 |

## 5. Trabajo técnico y de descubrimiento

| ID | Prioridad | Trabajo | Resultado esperado | Nota del cotejo |
|---|---|---|---|---|
| TEC-01 | P0 | Reproducir el problema de cuentas por pagar | Saber si es funcionalidad, visibilidad o estado | La columna de pago se corta y hay errores; revisar SEILAB 1876 |
| TEC-02 | P0 | Matriz de permisos y bitácora | Reglas para registrar, corregir, autorizar, cerrar y reabrir | Roles y autorizaciones existen; faltan cancelaciones y bitácora (REQ-03) |
| TEC-03 | P0 | Fórmulas fiscales con Jessica | Casos aprobados de IVA, retenciones y totales | Incluir tratamiento de Toronja |
| TEC-04 | P0 | Saldos de apertura con Liza | Ejemplo reproducible y alcance de R2·HU-12 | Revisar el error de fecha al dar de alta cuentas |
| TEC-05 | P1 | Migración de nómina y reclasificaciones | Respaldo, totales validados y reversión | Decidir antes la fuente de empleados (HRFlow) |
| TEC-06 | P1 | Acceso y límites de la conexión de IA | Diagnóstico y prueba del agente | Causa: nunca se configuró `ANTHROPIC_API_KEY`. Basta cargarla en `/srv/apps/financials/.env` y fijar el tope mensual |
| TEC-07 | P1 | Datos del indicador por sucursal | Fórmula, fuentes y ejemplo validado | Incluir regla de reparto de gastos comunes |
| TEC-08 | P2 | Conexión bancaria | Dictamen de viabilidad, seguridad, costo y alternativa | La alternativa por archivo ya existe |
| TEC-09 | Restricción | Pausar la integración con Toronja | Atlas opera de forma autónoma hasta definir proveedor | No detener la importación de archivos, que es como entran las ventas |
| TEC-10 | Separado | Evaluar propuesta del nuevo proveedor | Alcance, seguridad, propiedad, mantenimiento e integración | Consultoría; no aprueba un ERP nuevo |

## 6. Orden recomendado

| Etapa | Alcance | Condición de salida |
|---|---|---|
| 0. Ordenar los datos (sin desarrollo) | R2·REQ-01; revisar con Liza las 37 cuentas por pagar; cerrar agosto, septiembre y octubre; activar cortes de caja diarios | Saldos que cuadran con bancos y arqueos |
| 1. Recuperar confianza | R2·REQ-02, R2·REQ-03, R2·HU-01, R2·HU-02, R2·HU-03, R2·HU-05; investigación de R2·HU-12 | Pagos claros, correcciones auditables, reglas fiscales validadas |
| 2. Reducir trabajo manual | R2·HU-15 (lectura de XML), R2·HU-04, R2·HU-09, R2·HU-16, R2·HU-20, R2·HU-21, y R2·HU-06/07 una vez acordada la fuente de empleados | Menos recaptura y vencimientos visibles |
| 3. Dar visibilidad | R2·HU-08, R2·HU-10, R2·HU-11, R2·HU-13, R2·HU-17, R2·HU-18, R2·HU-19 | Reportes por sucursal consistentes y con límites explícitos |
| 4. Integraciones | R2·HU-14 con conexión bancaria y lo que dependa del proveedor elegido | Viabilidad y seguridad aprobadas |

No son fechas comprometidas. Se estima después de resolver las definiciones.

## 7. Criterio de terminado común

- Validación funcional con Liza o Abraham; fiscal y contable con Jessica.
- Permisos comprobados.
- Sin pérdida ni duplicación de información existente.
- Saldos y reportes consistentes.
- Bitácora en operaciones sensibles.
- Instrucciones de uso actualizadas.
- Evidencia de pruebas y aceptación del cambio.

## 8. Decisiones para el refinamiento

1. ¿Qué campos se corrigen directamente y cuáles requieren reversa? (propuesta en R2·HU-02)
2. ¿Quién autoriza cambios y quién cierra o reabre periodos?
3. ¿Qué formato se usará para la carga masiva de nómina, y HRFlow será la fuente de empleados?
4. ¿Qué significa exactamente "cubrir gastos" para Liza, y cómo se reparten los gastos comunes?
5. ¿Cuál es el caso concreto del problema de saldos de apertura?
6. ¿Qué fecha y cobertura de información se consideran confiables? (los datos respaldan el 1-ago-2026)
7. ¿Los renglones de una factura llevan categoría propia o una sola por factura? ¿Qué subcategorías se necesitan?
8. ¿Las sucursales pagan gastos menores con su propia caja o todo sale de caja central?
9. ¿Cómo se tratan el IVA, los intereses y la depreciación de activos comprados a crédito?

Recomendación: cerrar primero las reglas y fallas del núcleo financiero. Un dashboard más atractivo no resolverá saldos, impuestos o estados de pago ambiguos.
