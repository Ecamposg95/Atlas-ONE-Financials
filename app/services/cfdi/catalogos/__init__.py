"""Catálogos del SAT (CFDI 4.0, Nómina 1.2, Pagos 2.0, cancelación) como datos versionados.

Uso::

    from app.services.cfdi.catalogos import catalogo

    catalogo("c_FormaPago").validar("03", fecha_emision)   # Registro o ClaveNoValida
    catalogo("c_CodigoPostal").obtener("64000")["descripcion_del_huso_horario"]

Ver README.md en este directorio.
"""

from app.services.cfdi.catalogos.cargador import (
    Catalogo,
    CatalogoNoEncontrado,
    ClaveNoValida,
    ErrorSat,
    EstadoClave,
    Registro,
    catalogo,
    catalogos_disponibles,
    errores_sat,
    manifiesto,
    tasa_o_cuota_valida,
    uso_cfdi_permitido,
)

__all__ = [
    "Catalogo",
    "CatalogoNoEncontrado",
    "ClaveNoValida",
    "ErrorSat",
    "EstadoClave",
    "Registro",
    "catalogo",
    "catalogos_disponibles",
    "errores_sat",
    "manifiesto",
    "tasa_o_cuota_valida",
    "uso_cfdi_permitido",
]
