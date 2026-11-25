# CFDI 4.0: documento fiscal, armado y validación previa

Capa de localización mexicana (ADR-013). Fase 2 del megaplan
(`docs/financials/09_MEGAPLAN_CFDI.md`): **armar y validar** el CFDI de
ingreso de un ingreso o una cuenta por cobrar. **No sella ni timbra**: eso
depende del servicio de llaves (ADR-017) y del proveedor (ADR-018) y llega en
el siguiente PR. Nada aquí crea pólizas, mueve dinero ni cambia la operación
(una prueba lo vigila: `test_el_modulo_fiscal_no_toca_el_libro`).

## Piezas

| Archivo | Qué hace |
|---|---|
| `catalogos/` | Catálogos y matriz de errores del SAT como datos versionados (fase 0) |
| `datos_fiscales.py` | Validadores de RFC, régimen, código postal, uso y pago; `fiscal_readiness` |
| `armado.py` | Conceptos e impuestos desde los importes de la operación. Nunca corrige montos: `ErrorArmado` en español |
| `comprobante.py` | El CFDI como datos puros, límites de tolerancia del Anexo 20, resumen de impuestos y XML sin sellar |
| `validacion.py` | Validación previa determinista: lista de problemas con código del SAT |
| `zona_horaria.py` | Hora local del lugar de expedición con las columnas de huso de `c_CodigoPostal` |
| `xml_sat.py` + `recursos_sat/` | Cadena original con la XSLT oficial y validación contra `cfdv40.xsd`, sin red |
| `app/domains/fiscal_mx/documentos.py` | Servicio: borrador desde la operación, rearmar, validar, XML |
| `app/models/fiscal_document.py` | Tablas `documentos_fiscales*` (migración `20261125_02`) |

## Modelo

- `documentos_fiscales`: tipo, estado, origen (`income_id` o `receivable_id`,
  exactamente uno, más `origen_tipo`/`origen_id`), fotografía del emisor
  (empresa o contribuyente) y del receptor, serie y folio por emisor
  (`documentos_fiscales_series`, bajo lock de fila; un borrador descartado deja
  hueco), fecha local + UTC + huso, lugar de expedición, moneda, forma y método
  de pago, totales, supuestos aplicados, última validación y, para el siguiente
  paso, UUID, proveedor y fechas de timbrado y cancelación.
- `documentos_fiscales_conceptos` y `documentos_fiscales_impuestos`: renglones
  con claves del SAT y sus traslados o retenciones. Cantidad y valor unitario
  `Numeric(20,6)`; importes `Numeric(14,2)`.
- `documentos_fiscales_xml`: **bytes inmutables** del XML sellado, timbrado y
  acuse de cancelación (uno por tipo). Viven en PostgreSQL como los adjuntos
  (`attachment_blobs`): el disco de Railway es efímero y aún no hay bucket;
  separados para que listar no cargue bytes. Un evento de SQLAlchemy y un
  disparador de PostgreSQL impiden actualizarlos o borrarlos: reconstruir un
  XML sellado desde la base invalida el sello (ADR-018, "guardar antes de
  enviar"). El XML **sin sellar no se guarda**: se regenera del documento.
- Estados: `BORRADOR` → `LISTO_PARA_TIMBRAR` (al validar sin problemas). Los
  demás (`SELLADO`, `TIMBRADO`, `CANCELACION_EN_PROCESO`, `CANCELADO`,
  `DESCARTADO`) quedan definidos para los siguientes pasos. Una operación sólo
  tiene una factura activa.

## API (`/api/fiscal-mx/documents`)

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/documents` | Prepara el borrador: `{origen_tipo, origen_id, serie?, tratamiento_iva?, clave_prod_serv?, clave_unidad?, conceptos?}` |
| GET | `/documents` | Lista paginada, filtros `origen_tipo`, `origen_id`, `estado` |
| GET | `/documents/{id}` | Documento con conceptos, supuestos y última validación |
| POST | `/documents/{id}/rebuild` | Vuelve a tomar datos de la operación y el cliente y refecha; conserva serie y folio |
| POST | `/documents/{id}/validate` | Validación previa; `{listo, problemas, advertencias}` |
| GET | `/documents/{id}/xml` | XML **sin sellar**, nombre `BORRADOR-SIN-VALIDEZ-FISCAL-…`, encabezado `X-Validez-Fiscal: ninguna` y comentario al inicio. `NoCertificado` en ceros, `Sello` y `Certificado` vacíos |

No hay endpoint de sellado ni de timbrado.

## Supuestos para el contador

También en `docs/financials/10_CUESTIONARIO_CONTADOR_CFDI.md`, sección I.

1. **Concepto único.** Las operaciones de hoy no tienen renglones: se factura
   un concepto con cantidad 1, valor unitario = subtotal, la descripción de la
   operación, clave `01010101` y unidad `E48` salvo que se indiquen otras. La
   validación advierte que `01010101` es genérica.
2. **Sin IVA no se adivina.** Con tasa 0 hay que decir si es tasa 0 %, exenta
   (`ObjetoImp 02`, traslado `Exento`) o no objeto (`ObjetoImp 01`).
3. **Descuentos.** El subtotal de la operación es la base después de
   descuentos; en el CFDI `SubTotal − Descuento` debe darlo.
4. **Montos intocables.** `subtotal + IVA = total` de la operación, base e IVA
   del CFDI iguales a los de la operación. El IVA del concepto debe caer en la
   tolerancia del Anexo 20 (`Base × Tasa`, con media unidad del último
   decimal de la base). Con varios renglones la diferencia de centavos se
   reparte dentro de esa tolerancia; si no cabe, error. Con `split_total`
   (IVA por diferencia) todo total de 0.01 a 1,000.00 al 16 % y al 8 % cabe.
5. **Fecha.** Hora local del código postal de expedición según `c_CodigoPostal`
   (huso, diferencia de invierno y verano y reglas de cambio), al preparar o
   rearmar. Sin código postal válido se usa UTC−6 y la validación lo marca.
   Ojo: el catálogo de noviembre de 2026 trae para Ciudad Juárez (`32000`)
   −6 en invierno y −7 en verano, al revés de lo esperable; se sigue el
   catálogo tal cual.
6. **Receptor genérico.** `XAXX010101000`: régimen 616, código postal = lugar
   de expedición, nombre distinto de "PUBLICO EN GENERAL" (eso es global).
   `XEXX010101000` aún no se soporta.
7. **Uso de CFDI.** El de la operación; si no trae, el del cliente por omisión
   (queda anotado en los supuestos del documento).
8. **PUE/PPD.** Se respeta lo capturado; sólo advierte si PUE con operación
   pendiente o PPD con operación cobrada.

## Validación previa

Códigos: los de la matriz de errores del SAT (`CFDI40xxx`) cuando la regla
sale de ahí; `401` para la ventana de 72 horas que revisa el proveedor;
`ATLAS-…` para reglas propias (`ATLAS-CUADRE` contra la operación,
`ATLAS-DATOS` datos faltantes, `ATLAS-XSD` esquema, `ATLAS-NO-SOPORTADO`).
Cubre: datos fiscales completos de emisor y receptor; claves vigentes **a la
fecha de emisión**; régimen por tipo de persona (CFDI40141/40158); uso contra
régimen (CFDI40161); RFC genérico (CFDI40130/40149/40159); 72 horas y fecha
futura; forma y método (CFDI40104/40105/40124); conceptos (CFDI40162–40180);
sumas y redondeos (CFDI40107–40119, 40203, 40205); cuadre con la operación; y
al final el XSD oficial. No revisa lo que sólo sabe el SAT (padrón de RFC,
nombre y código postal del receptor en la lista de contribuyentes).

## Cadena original y XSD

`recursos_sat/` trae `cfdv40.xsd`, sus importaciones y
`cadenaoriginal_4_0.xslt` con todas sus inclusiones, tal como los publica el
SAT (37 archivos, ~930 KB; `catCFDI.xsd` en gzip). `manifest.json` guarda URL,
sha256 y fecha; `xml_sat.py` revisa el sha256 al leer y resuelve las URL del
SAT sin red. `divisas.xslt` da 404 en el sitio del SAT y se sustituye por una
hoja vacía (sólo afecta ese complemento). Para actualizar:
`python3 -I scripts/sat_recursos/actualizar.py` y revisar el diff.

Por qué la XSLT oficial con lxml y no `satcfdi`: la cadena original es lo que
se firma; debe salir de la hoja del SAT, no de una copia de terceros, y así no
dependemos de internos de `satcfdi` sin documentar. El spike
(`spikes/cfdi_sellado/`) comprobó que lxml y `satcfdi` producen la misma
cadena y el mismo sello. `lxml==6.1.3` va fija en `requirements.txt`. El
hallazgo de C14N roto de lxml 6.1.3 / libxml2 2.14.6 no aplica aquí: el CFDI
no se canonicaliza (la cadena sale de la XSLT); sólo afecta la firma XML-DSig
de la cancelación, que llegará con su propia función `c14n` que canonicaliza
`SignedInfo` como documento aparte.

## Pendiente

- Sellado con el `Firmante` (ADR-017) y timbrado (ADR-018), guardando el XML
  sellado antes de enviarlo.
- Descartar un borrador; PDF; UI ("Preparar factura").
- Renglones en la operación (punto de venta, fase 3) en vez de concepto único.
