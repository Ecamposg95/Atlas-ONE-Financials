# 10 · Cuestionario para el contador: CFDI, punto de venta y nómina

_Atlas ONE Financials · 2026-11-25 · Fase 0 del megaplan de CFDI (`09_MEGAPLAN_CFDI.md`)_

## Para qué es este documento

Atlas ONE Financials va a emitir CFDI para sus clientes y a convertir cada venta, factura y nómina en pólizas. Antes de construir, necesitamos que un contador confirme o corrija las reglas que propone el plan. Nada de lo que sigue está validado; ninguna regla fiscal del sistema ha pasado por revisión de contador (`07_SECURITY_AND_COMPLIANCE.md`).

**Cómo contestar.** Cada pregunta trae el contexto mínimo, la opción que propone el plan y opciones cerradas. Marque una opción; si ninguna aplica, escriba la correcta en "Notas". Si la respuesta depende del régimen o del giro del cliente, dígalo: el sistema puede dejar la regla configurable por empresa.

**Datos útiles del sistema.**

- Catálogo de cuentas actual (por empresa): 1100 Caja y Bancos, 1110 Cobros en tránsito, 1200 Cuentas por Cobrar, 1190/1191 IVA acreditable pagado y pendiente de pago, 2100 Cuentas por Pagar, 2190/2191 IVA trasladado cobrado y pendiente de cobro, 2400 ISR Retenido por Enterar, 2410 IVA Retenido por Enterar, 4100 Ventas, 4200 Servicios, 5200 Nómina, y otras de gasto. Los códigos nuevos que se proponen abajo son tentativos.
- Hoy el IVA trasladado se registra en 2191 al facturar a crédito y pasa a 2190 al cobrar, en proporción al cobro.
- Atlas ONE (punto de venta) hoy sólo calcula IVA si la venta pide factura. Eso se va a corregir.
- HRFlow (RRHH) hoy no calcula ISR por tarifa, IMSS real ni subsidio. Ese motor se construirá antes de timbrar nómina (fase 6A).

**Datos del cliente piloto que necesitamos** (para La Fe y para cualquier otro piloto):

| Dato | Respuesta |
|---|---|
| Régimen fiscal del emisor (persona moral general, RESICO, actividad empresarial…) | |
| ¿Alguna sucursal en región fronteriza con IVA al 8%? | |
| ¿Vende productos con IEPS, tasa 0% o exentos? ¿Cuáles? | |
| ¿Recibe pagos de clientes con retención de ISR o IVA? | |
| Número de trabajadores y periodicidad de pago | |
| Estados donde paga impuesto sobre nóminas | |

---

## A. IVA y retenciones por tipo de venta

### A-01 · Tasa de IVA por renglón

**Contexto.** La factura global exige un concepto por ticket con su IVA desglosado por tasa. Un ticket puede mezclar productos al 16%, 0% y exentos.

**Propuesta del plan.** La tasa vive en el producto (y se fija la de la sucursal si está en región fronteriza). Cada renglón del ticket guarda su base, tasa e impuesto en el momento de la venta.

- ☐ Correcto.
- ☐ La tasa depende también del cliente o del tipo de operación (explique).
- Notas:

### A-02 · Precio al público con IVA incluido

**Contexto.** En mostrador el precio suele mostrarse con IVA incluido. El sistema debe derivar base e IVA por renglón y cuadrar al centavo con el total cobrado.

**Propuesta del plan.** Precio con IVA incluido; base = precio / (1 + tasa), redondeada por renglón a dos decimales; el IVA es la diferencia. Si la suma de renglones no cuadra con el total del ticket, el evento se rechaza.

- ☐ Correcto.
- ☐ Redondear sobre el total del ticket, no por renglón.
- ☐ Aceptar la diferencia de centavos y llevarla a una cuenta de redondeo.
- Notas:

### A-03 · Ventas con retención

**Contexto.** Si el cliente es una persona moral que retiene ISR o IVA (por ejemplo, a un emisor persona física o RESICO), la venta no puede ir en la factura global y requiere factura individual. Financials no tiene cuenta para impuestos que le retienen al emisor.

**Propuesta del plan.** Toda venta con retención se factura individual. Lo retenido se registra en una cuenta nueva de activo, "Impuestos retenidos por acreditar" (tentativa 1195), y se cobra el neto.

- ☐ Correcto.
- ☐ No aplica a los clientes piloto.
- ☐ Usar otro tratamiento (explique cuenta y momento).
- Notas:

### A-04 · IEPS

**Contexto.** El global separa IVA e IEPS por concepto. Hoy el sistema no maneja IEPS.

- ☐ Los clientes piloto no venden productos con IEPS: se deja fuera de esta fase.
- ☐ Sí venden con IEPS: indicar productos, si es tasa o cuota, y si se traslada en el precio.
- Notas:

### A-05 · Momento en que se causa el IVA en mostrador

**Contexto.** En mostrador casi todo es pago en una exhibición (PUE).

**Propuesta del plan.** Venta de mostrador cobrada: el IVA va directo a 2190 (cobrado). Venta a crédito a un cliente identificado: a 2191 hasta el cobro, como hoy.

- ☐ Correcto.
- ☐ Distinto (explique).
- Notas:

---

## B. Propina, recargo y comisión de tarjeta

> El megaplan anotó "propina y recargo: campos propios; no forman parte del ingreso gravado **[contador]**". La investigación no encontró fuente del SAT sobre propinas, y su lectura sobre el recargo es la contraria: sería parte del precio. Por eso estas preguntas son abiertas.

### B-01 · Propina cobrada con tarjeta

**Contexto.** El punto de venta guarda la propina en una columna aparte. El banco la deposita junto con la venta.

**Propuesta del plan.** La propina no es ingreso del negocio: se registra como pasivo "Propinas por entregar" (tentativa 2195), no entra al CFDI ni al global, y sale del pasivo al entregarla a los trabajadores.

- ☐ Correcto.
- ☐ Es ingreso del negocio y va en el comprobante.
- ☐ Otro tratamiento (explique).
- ¿Lo entregado a los trabajadores debe reflejarse en su recibo de nómina? ☐ Sí, como percepción (indique clave) ☐ No
- Notas:

### B-02 · Recargo por pagar con tarjeta

**Contexto.** Algunas tiendas cobran un porcentaje extra al pagar con tarjeta. El punto de venta lo guarda aparte.

**Opciones.**

- ☐ Es parte del precio: ingreso gravado con IVA, va en el ticket y en el CFDI (lectura de la investigación).
- ☐ No es ingreso gravado: se registra aparte y no va en el CFDI (texto actual del megaplan).
- ☐ No debe cobrarse; el sistema no lo soportará.
- Notas:

### B-03 · Comisión del banco por la terminal

**Contexto.** El banco deposita la venta neta de comisión y emite un CFDI por la comisión con IVA.

**Propuesta del plan.** El ingreso se registra por el total cobrado al cliente; la comisión es gasto con IVA acreditable, contra el CFDI del banco. Lo cobrado con tarjeta queda en 1110 (Cobros en tránsito) hasta el depósito.

- ☐ Correcto.
- ☐ Distinto (explique).
- Notas:

---

## C. Factura de un ticket que ya entró en una global (decisión D5)

### C-01 · Camino a seguir

**Contexto.** Las guías del SAT se contradicen. El manual de cancelación y las preguntas frecuentes de 2026 dicen: cancelar la global con motivo 04, volver a emitirla sin ese ticket y emitir la factura nominativa. La guía de llenado de la global (2023, aún publicada) admite además emitir un egreso con relación 01 contra la global y luego la nominativa, sin cancelar nada. Ninguna fuente declara inválido el segundo camino. Los dos chocan: un egreso vigente contra una global la vuelve no cancelable.

**Propuesta del plan.** Camino B (egreso contra la global y luego nominativa), configurable por empresa.

- ☐ Camino A: cancelar la global con motivo 04 y reexpedir.
- ☐ Camino B: egreso relacionado contra la global y luego nominativa.
- ☐ Cualquiera de los dos, a elección de cada empresa.
- Notas:

### C-02 · Efecto contable

**Propuesta del plan.** Ninguno de los dos caminos cambia el ingreso ni el IVA ya contabilizados en la venta: los documentos se ligan entre sí y a la venta original. Sólo hay póliza si la venta era a crédito (reclasificar la cuenta por cobrar al cliente identificado).

- ☐ Correcto.
- ☐ Debe registrarse el egreso como disminución de ingreso y la nominativa como ingreso nuevo (efecto neto cero).
- Notas:

### C-03 · Plazo para que el cliente pida su factura

**Contexto.** No se encontró plazo expreso. El límite práctico es el plazo para cancelar o relacionar la global.

- ☐ Mismo mes de la compra.
- ☐ Hasta el cierre del ejercicio.
- ☐ Otro: ______
- Notas:

---

## D. Pólizas de venta del punto de venta

### D-01 · Granularidad

**Propuesta del plan.** Una póliza por cierre de caja y sucursal, con detalle por forma de pago y tasa, ligada a los tickets que cubre. La factura individual de una venta no cambia esa póliza; sólo se liga.

- ☐ Correcto.
- ☐ Una póliza por venta.
- ☐ Una póliza diaria por sucursal, sin importar cierres de caja.
- Notas:

### D-02 · Cuentas

**Propuesta del plan.**

| Movimiento | Cargo | Abono |
|---|---|---|
| Venta en efectivo | 1100 Caja y Bancos | 4100 Ventas (base), 2190 IVA trasladado cobrado |
| Venta con tarjeta | 1110 Cobros en tránsito | 4100 Ventas (base), 2190 IVA trasladado cobrado |
| Depósito del banco | 1100 Caja y Bancos, gasto por comisión, 1190 IVA acreditable | 1110 Cobros en tránsito |

- ☐ Correcto.
- ☐ Correcciones (explique):

### D-03 · Costo de ventas

**Contexto.** El inventario lo lleva Atlas ONE, no Financials. El catálogo de Financials no tiene cuenta de costo de ventas.

- ☐ Fuera de alcance de esta fase.
- ☐ Se necesita póliza de costo de ventas desde el punto de venta (indicar método de costeo).
- Notas:

### D-04 · Devoluciones

**Propuesta del plan.** Una devolución es un evento propio. Genera su póliza con la fecha de la devolución (no la de la venta), revierte ingreso e IVA, y su CFDI de egreso relacionado. Si el ticket estaba en una global, el egreso va contra la global, con el folio del ticket.

- ☐ Correcto.
- ☐ Distinto si la devolución es de un mes ya cerrado (explique).
- Notas:

---

## E. Factura global

### E-01 · Periodicidad

**Propuesta del plan.** Diaria, una por sucursal, emitida dentro de las 24 horas siguientes al cierre del día.

- ☐ Diaria.
- ☐ Semanal.
- ☐ Mensual.
- ☐ Configurable por empresa.

### E-02 · Efecto contable

**Propuesta del plan.** La global no genera póliza: el ingreso y el IVA ya se registraron al cerrar caja. La global se liga a esas pólizas por su UUID.

- ☐ Correcto.
- ☐ Distinto (explique).

### E-03 · Ventas a crédito al público en general

**Contexto.** Las ventas a crédito sin cliente identificado no llevan complemento de pagos; se reflejan en globales.

- ☐ Los clientes piloto no tienen este caso.
- ☐ Sí existe: ¿se reporta en la global del día de la venta o del día de cada abono? ______

---

## F. Complemento de pagos

### F-01 · PUE o PPD

**Propuesta del plan.** PPD siempre que el cobro no esté confirmado al timbrar; PUE sólo si ya se cobró.

- ☐ Correcto.
- ☐ Distinto (explique).

### F-02 · Uno por pago o mensual

- ☐ Uno por cada pago (propuesta del plan: concilia uno a uno con el banco).
- ☐ Uno mensual por cliente.
- ☐ Configurable por empresa.

### F-03 · IVA de un cobro parcial

**Propuesta del plan.** Al cobrar, el IVA pasa de 2191 a 2190 en proporción al pago sobre el total de la factura, igual que hoy. El complemento no genera póliza propia: la póliza es la del cobro.

- ☐ Correcto.
- ☐ Distinto (explique).

---

## G. Notas de crédito (egresos)

### G-01 · Cuenta

**Propuesta del plan.** Devoluciones, descuentos y bonificaciones van a una cuenta nueva "Devoluciones, descuentos y rebajas sobre ventas" (tentativa 4900, que resta de ingresos), no directo a 4100.

- ☐ Correcto.
- ☐ Directo a 4100.
- ☐ Una cuenta por tipo (devolución, descuento, bonificación).

### G-02 · IVA del egreso

**Propuesta del plan.** Si la factura original ya estaba cobrada, el egreso disminuye 2190; si estaba pendiente, 2191.

- ☐ Correcto.
- ☐ Distinto (explique).

### G-03 · Anticipos

- ☐ Los clientes piloto no reciben anticipos: fuera de alcance.
- ☐ Sí reciben: describir el caso (apartado con precio pactado, monedero, tarjeta de regalo…).

---

## H. Nómina

> Contexto común. HRFlow paga hoy "días pagables × salario diario"; no calcula ISR por tarifa, IMSS por ramo ni subsidio. El motor fiscal se construirá en HRFlow (fase 6A) y Financials sólo timbra y contabiliza lo que llegue ya calculado y clasificado. Estas preguntas fijan qué debe calcular ese motor y cómo se contabiliza.

### H-01 · Momento de la provisión

**Propuesta del plan.** Póliza de provisión al autorizar la corrida en RRHH; el gasto se marca deducible cuando cada recibo tiene UUID.

- ☐ Correcto.
- ☐ Al timbrar.
- ☐ Al pagar.

### H-02 · Cuentas de nómina

**Propuesta del plan** (códigos tentativos):

| Cuenta | Uso |
|---|---|
| 5200 Nómina (subcuentas por concepto) | Percepciones devengadas |
| 5210 Cuotas patronales | IMSS, SAR, INFONAVIT a cargo del patrón |
| 5220 Impuesto sobre nóminas | Impuesto estatal |
| 2500 Sueldos por pagar | Neto a pagar |
| 2420 ISR retenido por salarios | Separado de 2400 (honorarios y arrendamiento) |
| 2430 Cuotas obreras IMSS retenidas | |
| 2440 Cuotas patronales por pagar | IMSS mensual, SAR e INFONAVIT bimestral |
| 2450 Impuesto sobre nóminas por pagar | |

- ☐ Correcto.
- ☐ Usar 2400 también para ISR por salarios.
- ☐ Correcciones (explique):

### H-03 · ISR

**Propuesta del plan.** Tarifa del art. 96 de la LISR según la periodicidad de pago, calculada por HRFlow.

- ☐ Tarifa del periodo (quincenal, semanal…).
- ☐ Mensualizar y volver a proporcionar.
- ☐ Ajuste mensual o anual adicional (explique cuándo).

### H-04 · Subsidio para el empleo 2026

**Contexto.** La investigación no pudo leer en fuente primaria la mecánica vigente: la revisión E del complemento sube el tope del subsidio causado de 475 a 628 pesos (fuente secundaria), y el decreto del 31-12-2025 habla de alrededor de 536 pesos mensuales. Es el mayor riesgo de implementación de nómina.

**Propuesta del plan.** El subsidio disminuye el ISR a retener y se reporta en el recibo como otro pago 002 con su subsidio causado; no genera cuenta por cobrar al fisco.

- ☐ Correcto. Cifras 2026 a usar: ______
- ☐ Distinto (explique mecánica y cifras).

### H-05 · Cuotas del IMSS

**Propuesta del plan.** Cuotas obreras retenidas en cada corrida; cuotas patronales provisionadas al mes (SAR e INFONAVIT al bimestre), contra 2440.

- ☐ Correcto.
- ☐ Patronales también por corrida.
- ☐ Distinto (explique).

### H-06 · Impuesto sobre nóminas

- ¿En qué estados? ______ ¿Tasa? ______
- ☐ Lo calcula RRHH y llega en el evento.
- ☐ Lo calcula Financials al mes sobre el total de percepciones.

### H-07 · Incentivo de puntualidad pagado fuera de nómina

**Contexto.** HRFlow calcula un incentivo de puntualidad y lo marca como pagado en una tabla aparte (`IncentivoPago`); no entra al bruto ni a ningún recibo. El catálogo del SAT tiene una percepción de premios por puntualidad.

**Propuesta del plan.** Si es un premio pagado por el patrón, va en el recibo de nómina como percepción con su clave del SAT, dentro de la corrida.

- (a) ¿Debe ir en el CFDI de nómina? ☐ Sí ☐ No (explique por qué)
- (b) ¿Integra salario base de cotización? ☐ Sí ☐ No ☐ Sólo el excedente del tope (indique tope) — la regla del 10% del art. 27 de la Ley del Seguro Social está **sin verificar** en esta investigación.
- (c) ¿Para ISR es gravado o tiene parte exenta? ______
- (d) Lo ya pagado fuera de nómina en 2026: ☐ Regularizar con recibos antes del 31-12-2026 ☐ Otro tratamiento: ______

### H-08 · Aguinaldo, prima vacacional y PTU

**Contexto.** HRFlow no los calcula.

- ☐ Fuera del piloto; se registran por fuera mientras tanto.
- ☐ Provisión mensual desde el inicio (indique método).

### H-09 · Granularidad y pago

**Propuesta del plan.** Una póliza de provisión por corrida con detalle por concepto, ligada a la lista de UUID; una póliza de pago por dispersión bancaria (un movimiento por dispersión, conciliable con el estado de cuenta); pólizas de entero por cada impuesto o cuota.

- ☐ Correcto.
- ☐ Póliza por empleado.
- ☐ Distinto (explique).

### H-10 · Fecha y plazo de timbrado

**Contexto.** La ley pide emitir el recibo en la fecha de pago. La regla 2.7.5.1 da un plazo posterior de 3 a 11 días hábiles según el número de trabajadores (fuente secundaria; la tabla no se leyó en el DOF).

- ¿Plazo aplicable al cliente piloto? ______ días hábiles.
- ☐ Timbrar siempre antes del pago.
- ☐ Timbrar dentro del plazo posterior.

---

## I. Armado de la factura individual (supuestos ya programados en el borrador)

El borrador de factura (`app/services/cfdi/armado.py`, detalle en `app/services/cfdi/README.md`) ya aplica estos supuestos. Ninguno corrige montos de la operación: si no cuadran, la factura no se prepara.

### I-01 · Concepto único cuando la operación no tiene renglones

**Supuesto programado.** Hoy ingresos y cuentas por cobrar no tienen renglones. Se factura un concepto: cantidad 1, valor unitario = subtotal de la operación, descripción de la operación, clave `01010101` ("No existe en el catálogo") y unidad `E48` ("Unidad de servicio"), salvo que el usuario indique otras. La validación lo marca como advertencia.

- ☐ Correcto.
- ☐ Usar otra clave por omisión por empresa: ______ / unidad ______.
- ☐ Exigir siempre la clave (no permitir 01010101).

### I-02 · Operación sin IVA

**Supuesto programado.** Tasa 0 en la operación no distingue tasa 0 %, exenta o no objeto; el usuario debe elegir y no se adivina. Exenta se emite con `ObjetoImp 02` y traslado `Exento`; no objeto, con `ObjetoImp 01` sin impuestos.

- ☐ Correcto.
- ☐ Distinto (explique).

### I-03 · Descuentos

**Supuesto programado.** El subtotal de la operación es la base después de descuentos; en el CFDI `SubTotal` va antes de descuentos y `Descuento` por renglón. Se exige que `SubTotal − Descuento` sea el subtotal de la operación.

- ☐ Correcto.
- ☐ Distinto (explique).

### I-04 · Centavos de IVA con varios renglones

**Supuesto programado.** El IVA de cada renglón se redondea a centavos; si la suma no da el IVA de la operación, la diferencia se reparte de a un centavo, en orden, sólo donde la tolerancia del Anexo 20 lo permite. Si no cabe, la factura no se prepara y se pide corregir la operación.

- ☐ Correcto.
- ☐ Distinto (explique).

### I-05 · PUE en una cuenta por cobrar pendiente

**Supuesto programado.** Se respeta el método capturado en la operación. Si dice PUE y la operación no está cobrada, sólo se advierte (no bloquea); si dice PPD y ya está cobrada, se advierte que hará falta el complemento de pago. Ver también F-01.

- ☐ Correcto.
- ☐ Bloquear PUE si la operación no está cobrada.

### I-06 · IVA 8 % fuera de la franja fronteriza

**Supuesto programado.** Si la tasa es 8 % y el código postal de expedición no está marcado como franja fronteriza norte en `c_CodigoPostal`, sólo se advierte.

- ☐ Correcto.
- ☐ Bloquear.

### I-07 · Cliente con RFC genérico

**Supuesto programado.** Con `XAXX010101000` el régimen debe ser 616, el código postal del cliente se toma del lugar de expedición y el nombre no puede ser "PUBLICO EN GENERAL" (eso es factura global, fase 4). `XEXX010101000` (extranjero) aún no se soporta.

- ☐ Correcto.
- ☐ Distinto (explique).

---

## Cierre

| | |
|---|---|
| Contador que responde | |
| Cédula o registro | |
| Fecha | |
| Alcance de la revisión (qué sí y qué no se revisó) | |

Las respuestas se incorporan al megaplan y a las reglas de `app/services/accounting/rules.py` con referencia a este cuestionario. Ninguna regla se marca como validada en el producto sin la respuesta correspondiente.
