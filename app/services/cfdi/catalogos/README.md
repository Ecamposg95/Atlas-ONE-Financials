# Catálogos del SAT

Catálogos oficiales del SAT para CFDI 4.0, Nómina 1.2, Pagos 2.0 y cancelación,
guardados como **datos versionados** (no como enumeraciones en código) y un
cargador de solo lectura para consultarlos. Es la fase 0 del megaplan de CFDI
(`docs/financials/09_MEGAPLAN_CFDI.md`). Aquí no hay sellado ni timbrado, ni
tablas en la base de datos.

## Qué hay

`data/` lo genera `scripts/sat_catalogos/convertir.py`; **no se edita a mano**
(el cargador verifica el sha256 de cada archivo contra `data/manifest.json`).

| Grupo | Archivo original del SAT | Catálogos |
|---|---|---|
| `cfdi40` | `catCFDI_V_4_20261120.xls` (versión 20-nov-2026) | c_FormaPago, c_MetodoPago, c_UsoCFDI, c_RegimenFiscal, c_ClaveProdServ, c_ClaveUnidad, c_ObjetoImp, c_Impuesto, c_TipoFactor, c_TasaOCuota, c_TipoDeComprobante, c_Exportacion, c_Periodicidad, c_Meses, c_TipoRelacion, c_Moneda, c_Pais, c_Aduana, c_CodigoPostal (con huso horario y horario de verano), c_Estado, c_Municipio, c_Localidad |
| `nomina12` | `catNomina.xls` | c_Banco, c_OrigenRecurso, c_PeriodicidadPago, c_TipoContrato, c_TipoDeduccion, c_TipoHoras, c_TipoIncapacidad, c_TipoJornada, c_TipoNomina, c_TipoOtroPago, c_TipoPercepcion, c_TipoRegimen, c_RiesgoPuesto |
| `pagos20` | `catPagos.xls` | c_TipoCadenaPago (el resto de Pagos 2.0 usa los de CFDI 4.0) |
| `cancelacion` | `Esquema_de_cancelacion_de_CFDI_2026.pdf` | c_MotivoCancelacion (01–04, transcritos y cotejados textualmente contra el PDF) |
| `matrices` | `MatrizDeErrores_CFDI_v40_20260325.xls`, `29122021_Matriz_ErroresNomina_v12_RevC.xls`, `MatrizDeErrores_CRP_V20_RevB.xls` | Códigos de error CFDI40xxx, NOMxx y CRP20xxx con su validación y descripción |

Cada archivo trae `sat` (versión, revisión, fecha de publicación y vigencia del
catálogo, tal como vienen en la hoja; `null` si la hoja no las trae) y `origen`
(archivo, URL, fecha de descarga y sha256 del original). El manifiesto reúne lo
mismo más el número de registros.

Formato: JSON con metadatos arriba, `columnas` y un registro por línea en
`registros` (los diffs de una actualización salen legibles). Todos los valores
son texto o `null`, nunca flotantes. Las claves conservan los ceros a la
izquierda tal como las enumera el XSD oficial (`"01"`, `"002"`, `"01010101"`).
Las fechas van en ISO; `vigencia_fin: null` significa sin fecha de fin.

`c_ClaveProdServ` (52 mil registros) y `c_CodigoPostal` (96 mil) van en
`.json.gz` (gzip determinista, mtime 0); para verlos: `zcat archivo.json.gz | less`.
Todo `data/` pesa ~1.8 MB.

## Uso

```python
from app.services.cfdi.catalogos import catalogo, errores_sat, tasa_o_cuota_valida, uso_cfdi_permitido

forma = catalogo("c_FormaPago").validar("03", fecha_emision)  # Registro, o ClaveNoValida (mensaje en español)
catalogo("c_ObjetoImp").estado("06", fecha_emision)            # EstadoClave.VIGENTE / NO_VIGENTE / INEXISTENTE
catalogo("c_CodigoPostal").obtener("64000")["descripcion_del_huso_horario"]
catalogo("c_Municipio").obtener(("AGU", "001"))                  # llave compuesta (c_estado, clave)
tasa_o_cuota_valida("002", "Tasa", "0.160000", traslado=True, fecha=fecha_emision)
uso_cfdi_permitido("G03", "626", persona_moral=False, fecha=fecha_emision)
errores_sat("CFDI40104")                                          # renglones de la matriz de errores
```

- La vigencia se valida por registro y **con la fecha de emisión**, que se pasa
  siempre explícita: `inicio <= fecha <= fin` (fin inclusivo).
- Cada catálogo se lee la primera vez que se pide y queda en memoria.
- Sin dependencias nuevas en tiempo de ejecución (sólo biblioteca estándar).

## Cómo actualizar

El SAT publica versiones nuevas varias veces al año (el nombre del archivo lleva
la fecha). Páginas: [Anexo 20](http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm),
[Nómina](http://omawww.sat.gob.mx/tramitesyservicios/Paginas/complemento_nomina.htm),
[Pagos](http://omawww.sat.gob.mx/tramitesyservicios/Paginas/recepcion_de_pagos.htm).

1. Actualiza nombres y URL en `scripts/sat_catalogos/fuentes.py`.
2. Descarga **fuera del repo** (los originales no se versionan; el de CFDI pesa ~49 MB):
   `python3 -I scripts/sat_catalogos/descargar.py /tmp/sat_catalogos`
3. Convierte (necesita `xlrd`, sólo para este paso):
   `pip install -r scripts/sat_catalogos/requirements.txt`
   `python3 -I scripts/sat_catalogos/convertir.py /tmp/sat_catalogos`
   Sale con error si una clave no está en el XSD oficial o si una llave se repite.
   Imprime `AVISO` para lo que no detiene (queda también en `manifest.json`, `avisos_conversion`).
4. Revisa `git diff app/services/cfdi/catalogos/data` (para los `.gz`, compara con `zcat`),
   corre `pytest tests/test_cfdi_catalogos.py` y haz commit.

Los originales son datos no confiables: el script sólo los lee (`python3 -I`),
nunca los ejecuta ni los importa. La conversión es determinista: los mismos
originales producen los mismos bytes.

## Qué no se cargó o quedó pendiente

- **Claves que el XSD acepta y la hoja de cálculo no trae.** El XSD oficial
  (`catCFDI.xsd`, `catNomina.xsd`) enumera claves que no vienen en el `.xls`,
  así que no tienen descripción ni vigencia y **no se cargaron**. El cargador
  las expone en `Catalogo.claves_solo_en_xsd`. Hay que decidir caso por caso
  con el contador:
  - Nómina: c_TipoPercepcion 054–057 y c_TipoDeduccion 108–115. `catNomina.xls`
    no se ha actualizado desde 2022 y el XSD sí; probablemente son claves nuevas
    reales (revisión E de la guía de nómina). **Pendiente antes de la fase de nómina.**
  - c_RegimenFiscal 609, 628, 629, 630; c_UsoCFDI P01; c_TipoRelacion 08, 09;
    c_Estado DIF; c_CodigoPostal 00000; 234 claves de c_ClaveProdServ. En su
    mayoría parecen claves históricas de CFDI 3.3 o dadas de baja que el XSD
    conserva; sin verificar.
- **Omitidos a propósito** de `catCFDI`: c_Colonia (~145 mil filas),
  c_NumPedimentoAduana y c_PatenteAduanal (comercio exterior). Se agregan en
  `fuentes.py` si hacen falta.
- **Matriz de errores de cancelación**: el SAT no la publica como hoja de
  cálculo; los códigos del servicio de cancelación (p. ej. 210, 211, 310) están
  sólo en el Anexo 29 de la RMF (PDF) y no se cargaron.
- **Catálogos de otros complementos** (Carta Porte, Comercio Exterior, etc.):
  fuera de alcance.
- `c_TasaOCuota` no tiene clave propia; se consulta con `tasa_o_cuota_valida()`.
- Varios catálogos de nómina no traen fecha de publicación ni vigencia del
  catálogo en la hoja; esos metadatos quedan en `null`.
