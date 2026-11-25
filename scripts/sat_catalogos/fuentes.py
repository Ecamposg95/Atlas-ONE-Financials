"""Fuentes oficiales de los catálogos del SAT que carga Atlas ONE Financials.

Es la única lista que hay que tocar cuando el SAT publica una versión nueva:
cambia el nombre del archivo (el SAT lo fecha, p. ej. ``catCFDI_V_4_20261120.xls``),
corre ``descargar.py`` y después ``convertir.py``. Ver el README del módulo
``app/services/cfdi/catalogos``.
"""

from __future__ import annotations

_DOCS = "http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos"
_XSD = "http://www.sat.gob.mx/sitio_internet/cfd/catalogos"

# Archivos originales. La clave es el nombre con que se guardan en disco.
ARCHIVOS: dict[str, dict[str, str]] = {
    # Página del Anexo 20: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm
    "catCFDI_V_4_20261120.xls": {
        "url": f"{_DOCS}/catCFDI_V_4_20261120.xls",
        "version_archivo": "2026-11-20",
    },
    "catCFDI.xsd": {"url": f"{_XSD}/catCFDI.xsd", "version_archivo": ""},
    "MatrizDeErrores_CFDI_v40_20260325.xls": {
        "url": f"{_DOCS}/MatrizDeErrores_CFDI_v40_20260325.xls",
        "version_archivo": "2026-03-25",
    },
    # Página del complemento de nómina: .../Paginas/complemento_nomina.htm
    "catNomina.xls": {"url": f"{_DOCS}/catNomina.xls", "version_archivo": ""},
    "catNomina.xsd": {"url": f"{_XSD}/Nomina/catNomina.xsd", "version_archivo": ""},
    "29122021_Matriz_ErroresNomina_v12_RevC.xls": {
        "url": f"{_DOCS}/29122021_Matriz_ErroresNomina_v12_RevC.xls",
        "version_archivo": "Revisión C (2021-12-29)",
    },
    # Página del complemento de pagos: .../Paginas/recepcion_de_pagos.htm
    "catPagos.xls": {"url": f"{_DOCS}/catPagos.xls", "version_archivo": ""},
    "catPagos.xsd": {"url": f"{_XSD}/Pagos/catPagos.xsd", "version_archivo": ""},
    "MatrizDeErrores_CRP_V20_RevB.xls": {
        "url": f"{_DOCS}/MatrizDeErrores_CRP_V20_RevB.xls",
        "version_archivo": "Revisión B",
    },
    # Motivos de cancelación (no hay hoja de cálculo; se transcriben y se cotejan contra el PDF).
    "Esquema_de_cancelacion_de_CFDI_2026.pdf": {
        "url": "https://www.sat.gob.mx/minisitio/Factura/documentos/Esquema_de_cancelacion_de_CFDI_2026.pdf",
        "version_archivo": "2026",
    },
}

# Catálogos a convertir: (grupo, catálogo, archivo, hojas, xsd que lo enumera o None).
# Varios catálogos vienen partidos en dos hojas por el límite de filas de Excel.
CATALOGOS: list[tuple[str, str, str, list[str], str | None]] = []

_CFDI = "catCFDI_V_4_20261120.xls"
for _nombre in [
    "c_FormaPago",
    "c_Moneda",
    "c_TipoDeComprobante",
    "c_Exportacion",
    "c_MetodoPago",
    "c_Periodicidad",
    "c_Meses",
    "c_TipoRelacion",
    "c_RegimenFiscal",
    "c_Pais",
    "c_UsoCFDI",
    "c_ClaveProdServ",
    "c_ClaveUnidad",
    "c_ObjetoImp",
    "c_Impuesto",
    "c_TipoFactor",
    "c_TasaOCuota",
    "c_Aduana",
]:
    CATALOGOS.append(("cfdi40", _nombre, _CFDI, [_nombre], "catCFDI.xsd"))
CATALOGOS.append(
    ("cfdi40", "c_CodigoPostal", _CFDI, ["c_CodigoPostal_Parte_1", "c_CodigoPostal_Parte_2"], "catCFDI.xsd")
)
CATALOGOS += [
    ("cfdi40", "c_Estado", _CFDI, ["c_Estado"], "catCFDI.xsd"),
    ("cfdi40", "c_Municipio", _CFDI, ["C_Municipio"], "catCFDI.xsd"),
    ("cfdi40", "c_Localidad", _CFDI, ["C_Localidad"], "catCFDI.xsd"),
]
for _nombre in [
    "c_Banco",
    "c_OrigenRecurso",
    "c_PeriodicidadPago",
    "c_TipoContrato",
    "c_TipoDeduccion",
    "c_TipoHoras",
    "c_TipoIncapacidad",
    "c_TipoJornada",
    "c_TipoNomina",
    "c_TipoOtroPago",
    "c_TipoPercepcion",
    "c_TipoRegimen",
    "c_RiesgoPuesto",
]:
    CATALOGOS.append(("nomina12", _nombre, "catNomina.xls", [_nombre], "catNomina.xsd"))
CATALOGOS.append(("pagos20", "c_TipoCadenaPago", "catPagos.xls", ["c_TIpoCadenaPago"], "catPagos.xsd"))

# Hojas de catCFDI que no se cargan a propósito (comercio exterior / domicilios):
# c_Colonia (~145 mil filas), c_NumPedimentoAduana y c_PatenteAduanal.
OMITIDOS = ["c_Colonia", "c_NumPedimentoAduana", "c_PatenteAduanal"]

# Catálogos grandes: se guardan comprimidos con gzip.
COMPRIMIDOS = {"c_ClaveProdServ", "c_CodigoPostal"}

# Matrices de errores: (nombre, archivo).
MATRICES: list[tuple[str, str]] = [
    ("cfdi40", "MatrizDeErrores_CFDI_v40_20260325.xls"),
    ("nomina12", "29122021_Matriz_ErroresNomina_v12_RevC.xls"),
    ("pagos20", "MatrizDeErrores_CRP_V20_RevB.xls"),
]

# Motivos de cancelación (art. 29-A CFF). Transcritos del PDF oficial; convertir.py
# verifica que cada descripción aparezca textualmente en él.
MOTIVOS_CANCELACION_ARCHIVO = "Esquema_de_cancelacion_de_CFDI_2026.pdf"
MOTIVOS_CANCELACION = [
    ("01", "Comprobante emitido con errores con relación", "2022-01-01"),
    ("02", "Comprobante emitido con errores sin relación", "2022-01-01"),
    ("03", "No se llevó a cabo la operación", "2022-01-01"),
    ("04", "Operación nominativa relacionada en una factura global", "2022-01-01"),
]
