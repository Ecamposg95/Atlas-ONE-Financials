# Guía de uso · Conciliación bancaria

_Atlas ONE Financials · Para administración y contabilidad · 2026-11-24_

La conciliación compara el estado de cuenta del banco con los movimientos que ya están registrados. Sirve para confirmar que el dinero que dicen los libros es el que hay en el banco. Conciliar **no mueve saldos ni crea pólizas**: sólo liga renglones del banco con movimientos.

Se concilian cuentas de banco y procesadores de pago. La caja de efectivo se revisa con el corte de caja.

## Antes de empezar

1. Descarga el estado de cuenta desde la banca en línea, en Excel (`.xlsx`) o CSV.
2. Ten a la mano el saldo final del periodo que marca el banco.

## Paso a paso

1. Entra a **Dinero → Conciliación** y elige **Subir estado de cuenta**.
2. Elige la cuenta y el archivo. Aparece una vista previa con los renglones como los leyó el sistema. Nada se guarda todavía.
3. Revisa las columnas. El sistema reconoce los encabezados más comunes (Fecha, Concepto, Referencia, Cargo, Abono, Importe). Si alguno quedó mal, cámbialo en los selectores.
4. Elige **Importar y conciliar**.
5. Elige **Conciliar lo seguro**. El sistema liga los renglones que sólo tienen un movimiento posible del mismo importe, con fecha a 7 días o menos. Lo dudoso se queda pendiente.
6. Resuelve cada renglón pendiente:
   - **Confirmar**: acepta la propuesta que muestra el sistema.
   - **Buscar**: elige a mano uno o varios movimientos. Un depósito puede liquidar varias ventas.
   - **No corresponde**: el renglón no debe estar en tus libros. Pide un motivo.
7. Captura el saldo final del estado de cuenta y elige **Cerrar conciliación**.

## Cómo leer la pantalla

| Cifra | Qué significa |
|---|---|
| Saldo en banco | El saldo final que capturaste del estado de cuenta |
| Saldo en libros | El saldo de la cuenta en el sistema al último día del periodo |
| En tránsito | Movimientos registrados en el periodo que el banco aún no refleja |
| Sin explicar | Lo que falta para que banco y libros cuadren. Debe quedar en cero |

## Alertas

| Alerta | Qué hacer |
|---|---|
| Renglones sin ligar ni explicar | Resolverlos; no se puede cerrar con pendientes |
| Renglones con diferencia | El importe del banco no coincide con lo ligado. Suele ser una comisión sin registrar: regístrala como gasto y lígala |
| Movimientos que no aparecen en el banco | Normal si son recientes (cheques, liquidaciones). Si son antiguos, revisar |
| Movimiento cancelado después de conciliar | Deshacer el renglón y volver a ligarlo |
| Saldos que no cuadran | Revisar periodos anteriores sin conciliar o movimientos faltantes |

## Si falta un movimiento

Cuando el banco trae algo que no está registrado (una comisión, un depósito), regístralo en su módulo de siempre (Gastos, Ingresos, Movimientos) y regresa a la conciliación: aparecerá como propuesta.

## Corregir

- **Deshacer** regresa un renglón a pendiente.
- **Descartar estado de cuenta** elimina la conciliación en proceso; los movimientos no cambian y el archivo se puede volver a subir.
- Una conciliación cerrada conserva sus cifras aunque después se registren movimientos. Sólo el dueño o un administrador pueden reabrirla.

## Límites actuales

- No lee PDF ni imágenes.
- No se conecta al banco: el archivo se sube a mano.
- No compara la comisión cobrada contra la pactada con el procesador; eso es una función futura.
- Un archivo admite hasta 5,000 renglones y 10 MB.
