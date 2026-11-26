"""Qué firmante y qué proveedor de timbrado usa la aplicación.

Todo apagado por omisión. Variables de entorno:

| Variable | Valores | Omisión |
|---|---|---|
| ``CFDI_TIMBRADO_HABILITADO`` | ``true`` / ``false`` | ``false``: sellar, timbrar y cancelar responden 503 |
| ``CFDI_FIRMANTE`` | ``kms`` · ``local_pruebas`` | ``kms`` (aún no conectado: 503) |
| ``CFDI_PROVEEDOR`` | ``prodigia`` · ``formas_digitales_pruebas`` · ``simulado`` | ``prodigia`` (sin adaptador: 503) |
| ``CFDI_CSD_PRUEBAS_CER`` / ``_KEY`` / ``_CONTRASENA`` | rutas y contraseña del CSD de prueba del SAT | — |
| ``FD_USUARIO`` / ``FD_CONTRASENA`` | credenciales públicas del ambiente de pruebas de Formas Digitales | — |

En producción sólo valen ``kms`` y un proveedor real: ``local_pruebas``,
``simulado`` y ``formas_digitales_pruebas`` se rechazan. El día que haya
cuenta del servicio de llaves y del proveedor, falta escribir
``FirmanteKms`` (y el alta de certificados) y el adaptador de Prodigia; nada
más cambia.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from app.config import Settings
from app.services.cfdi.firmante import Firmante, FirmanteKms, FirmanteLocalPruebas, FirmanteNoDisponible
from app.services.cfdi.proveedor_timbrado import ProveedorTimbrado

FIRMANTES = ("kms", "local_pruebas")
PROVEEDORES = ("prodigia", "formas_digitales_pruebas", "simulado")
_SOLO_PRUEBAS = {"local_pruebas", "formas_digitales_pruebas", "simulado"}

MENSAJE_NO_DISPONIBLE = "El timbrado aún no está disponible."
_SIMULADO = None


class TimbradoNoDisponible(Exception):
    """El timbrado está apagado o le falta configuración; mensaje en español."""


# (organization_id, rfc del emisor) -> Firmante del CSD de ese emisor.
FabricaFirmante = Callable[[str, str | None], Firmante]


@dataclass
class ServiciosTimbrado:
    proveedor: ProveedorTimbrado
    firmante_para: FabricaFirmante

    @property
    def nombre_proveedor(self) -> str:
        return self.proveedor.nombre


def _fabrica_local_pruebas(env: str) -> FabricaFirmante:
    cer, key = os.getenv("CFDI_CSD_PRUEBAS_CER"), os.getenv("CFDI_CSD_PRUEBAS_KEY")
    if not cer or not key:
        raise TimbradoNoDisponible(
            f"{MENSAJE_NO_DISPONIBLE} Falta CFDI_CSD_PRUEBAS_CER y CFDI_CSD_PRUEBAS_KEY (CSD de prueba del SAT)."
        )
    firmante = FirmanteLocalPruebas.desde_archivos(cer, key, os.getenv("CFDI_CSD_PRUEBAS_CONTRASENA"), entorno=env)
    # Un solo CSD de prueba: el sellado revisa que su RFC sea el del emisor.
    return lambda _org_id, _rfc: firmante


def _fabrica_kms(_env: str) -> FabricaFirmante:
    if not FirmanteKms.DISPONIBLE:
        raise FirmanteNoDisponible(FirmanteKms.MENSAJE)

    def fabrica(_org_id: str, _rfc: str | None) -> Firmante:
        return FirmanteKms()  # lanza FirmanteNoDisponible hasta que exista la cuenta y el alta de certificados

    return fabrica


def _proveedor(nombre: str, env: str) -> ProveedorTimbrado:
    if nombre == "simulado":
        from app.services.cfdi.pac_simulado import ProveedorSimulado  # noqa: PLC0415

        global _SIMULADO
        if _SIMULADO is None:  # uno por proceso, para que recuerde lo que timbró entre peticiones
            _SIMULADO = ProveedorSimulado()
        return _SIMULADO
    if nombre == "formas_digitales_pruebas":
        from app.services.cfdi.pac_formas_digitales import FormasDigitalesPruebas  # noqa: PLC0415

        try:
            return FormasDigitalesPruebas(os.getenv("FD_USUARIO", ""), os.getenv("FD_CONTRASENA", ""), entorno=env)
        except ValueError as exc:
            raise TimbradoNoDisponible(f"{MENSAJE_NO_DISPONIBLE} {exc}") from exc
    if nombre == "prodigia":
        # Hueco del primario (ADR-018): sin cuenta de pruebas ni documentación aún.
        raise TimbradoNoDisponible(f"{MENSAJE_NO_DISPONIBLE} El proveedor de timbrado todavía no está conectado.")
    raise TimbradoNoDisponible(f"{MENSAJE_NO_DISPONIBLE} Proveedor desconocido: {nombre}.")


def construir(settings: Settings) -> ServiciosTimbrado:
    """Arma los servicios según la configuración o lanza ``TimbradoNoDisponible``."""
    if not settings.cfdi_timbrado_habilitado:
        raise TimbradoNoDisponible(MENSAJE_NO_DISPONIBLE)
    firmante, proveedor = settings.cfdi_firmante, settings.cfdi_proveedor
    if firmante not in FIRMANTES:
        raise TimbradoNoDisponible(f"{MENSAJE_NO_DISPONIBLE} Firmante desconocido: {firmante}.")
    if settings.is_production and ({firmante, proveedor} & _SOLO_PRUEBAS):
        raise TimbradoNoDisponible(
            f"{MENSAJE_NO_DISPONIBLE} La configuración de pruebas no se usa en producción."
        )
    try:
        fabrica = _fabrica_local_pruebas(settings.env) if firmante == "local_pruebas" else _fabrica_kms(settings.env)
    except FirmanteNoDisponible as exc:
        raise TimbradoNoDisponible(f"{MENSAJE_NO_DISPONIBLE} {exc}") from exc
    return ServiciosTimbrado(proveedor=_proveedor(proveedor, settings.env), firmante_para=fabrica)
