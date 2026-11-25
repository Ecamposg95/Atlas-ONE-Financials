"""Datos fiscales del emisor, del receptor y de la operación (fase 2 del megaplan de CFDI).

Capa de localización mexicana (ADR-013): sólo valida claves contra los catálogos
del SAT y dice qué falta para facturar. No arma pólizas, no toca saldos y no
sella ni timbra.

La vigencia de las claves se revisa con la fecha que se pase; al capturar datos
maestros es la de hoy. Al timbrar se volverá a validar con la fecha de emisión.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app.services.cfdi.catalogos import EstadoClave, catalogo, uso_cfdi_permitido

RFC_PUBLICO_GENERAL = "XAXX010101000"
RFC_EXTRANJERO = "XEXX010101000"
RFC_GENERICOS = (RFC_PUBLICO_GENERAL, RFC_EXTRANJERO)
# CFDI40159: con RFC genérico el régimen del receptor es 616.
REGIMEN_SIN_OBLIGACIONES = "616"
FORMA_POR_DEFINIR = "99"
METODO_PUE = "PUE"
METODO_PPD = "PPD"

# Patrón del atributo Rfc en el XSD de CFDI 4.0 (t_RFC), con fecha AAMMDD.
_RFC = re.compile(r"^[A-Z&Ñ]{3,4}[0-9]{2}(0[1-9]|1[012])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{2}[0-9A]$")
_CODIGO_POSTAL = re.compile(r"^[0-9]{5}$")
# Valores del dígito verificador (Anexo 1-A, regla de cálculo del RFC).
_VALORES_DIGITO = {c: i for i, c in enumerate("0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ")}
# CFDI 4.0 pide la razón social tal como está en la constancia, que no trae el
# régimen de capital. Es la causa más común de rechazo por nombre.
_REGIMEN_CAPITAL = re.compile(
    r"[\s,]+(S\.?\s?A\.?\s?P\.?\s?I\.?|S\.?\s?A\.?|S\.?\s?DE\s?R\.?\s?L\.?|S\.?\s?C\.?|A\.?\s?C\.?)"
    r"(\s+DE\s+C\.?\s?V\.?)?\.?\s*$",
    re.IGNORECASE,
)


class DatoFiscalInvalido(ValueError):
    """Un dato fiscal no pasa la validación. El mensaje va en español, listo para la UI."""


def _hoy() -> dt.date:
    return dt.date.today()


# ---------------------------------------------------------------- RFC


def normalizar_rfc(valor: str | None) -> str | None:
    limpio = "".join((valor or "").split()).upper()
    return limpio or None


def digito_verificador(rfc: str) -> str:
    """Dígito verificador calculado para las primeras 11 (física) o 12 (moral) posiciones.

    La persona moral se rellena con un espacio a la izquierda para que ambas
    sumen 12 posiciones con pesos de 13 a 2.
    """
    base = rfc[:-1].rjust(12)
    suma = sum(_VALORES_DIGITO.get(c, 0) * (13 - i) for i, c in enumerate(base))
    resto = 11 - suma % 11
    if resto == 11:
        return "0"
    if resto == 10:
        return "A"
    return str(resto)


@dataclass(frozen=True)
class RevisionRfc:
    rfc: str
    persona_moral: bool
    generico: str | None  # "nacional" | "extranjero" | None
    digito_correcto: bool

    @property
    def advertencia(self) -> str | None:
        if self.generico or self.digito_correcto:
            return None
        return (
            f"El dígito verificador del RFC {self.rfc} no cuadra. Revísalo contra la constancia: "
            "el SAT lo puede rechazar al timbrar."
        )


def revisar_rfc(valor: str | None) -> RevisionRfc:
    """Valida formato y fecha del RFC. El dígito verificador sólo advierte: hay RFC
    reales asignados por el SAT que no siguen el cálculo."""
    rfc = normalizar_rfc(valor)
    if rfc is None:
        raise DatoFiscalInvalido("Escribe el RFC.")
    if rfc in RFC_GENERICOS:
        return RevisionRfc(
            rfc=rfc,
            persona_moral=False,
            generico="nacional" if rfc == RFC_PUBLICO_GENERAL else "extranjero",
            digito_correcto=True,
        )
    if len(rfc) not in (12, 13) or not _RFC.match(rfc):
        raise DatoFiscalInvalido(
            f"El RFC {rfc} no tiene un formato válido: son 12 caracteres para persona moral "
            "o 13 para persona física (letras, fecha AAMMDD y homoclave)."
        )
    return RevisionRfc(
        rfc=rfc,
        persona_moral=len(rfc) == 12,
        generico=None,
        digito_correcto=digito_verificador(rfc) == rfc[-1],
    )


def es_generico(rfc: str | None) -> bool:
    return normalizar_rfc(rfc) in RFC_GENERICOS


def _persona_de(rfc: str | None) -> bool | None:
    """True moral, False física, None si no hay RFC o no es válido."""
    try:
        return revisar_rfc(rfc).persona_moral if rfc else None
    except DatoFiscalInvalido:
        return None


# ---------------------------------------------------------------- catálogos


def _clave(nombre: str, clave: str, fecha: dt.date, que: str) -> None:
    estado = catalogo(nombre).estado(clave, fecha)
    if estado is EstadoClave.INEXISTENTE:
        raise DatoFiscalInvalido(f"{que} {clave} no existe en el catálogo del SAT.")
    if estado is EstadoClave.NO_VIGENTE:
        raise DatoFiscalInvalido(f"{que} {clave} ya no está vigente en el catálogo del SAT.")


def validar_regimen(clave: str, *, persona_moral: bool | None, fecha: dt.date | None = None) -> None:
    """Clave vigente de c_RegimenFiscal que aplique al tipo de persona (CFDI40141)."""
    fecha = fecha or _hoy()
    _clave("c_RegimenFiscal", clave, fecha, "El régimen fiscal")
    if persona_moral is None:
        return
    registro = catalogo("c_RegimenFiscal").obtener(clave)
    columna = "persona_moral" if persona_moral else "persona_fisica"
    if not (registro[columna] or "").strip().lower().startswith("s"):
        tipo = "moral" if persona_moral else "física"
        raise DatoFiscalInvalido(
            f"El régimen {clave} ({registro.descripcion}) no aplica a una persona {tipo}; "
            "revisa el RFC o el régimen de la constancia."
        )


def validar_codigo_postal(clave: str, fecha: dt.date | None = None) -> None:
    if not _CODIGO_POSTAL.match(clave or ""):
        raise DatoFiscalInvalido("El código postal fiscal son cinco dígitos.")
    _clave("c_CodigoPostal", clave, fecha or _hoy(), "El código postal")


def validar_uso_cfdi(
    uso: str,
    *,
    regimen: str | None,
    persona_moral: bool | None,
    fecha: dt.date | None = None,
) -> None:
    """Clave vigente de c_UsoCFDI y, si se conoce el régimen, que le corresponda (CFDI40161)."""
    fecha = fecha or _hoy()
    _clave("c_UsoCFDI", uso, fecha, "El uso de CFDI")
    if not regimen:
        return
    personas = (persona_moral,) if persona_moral is not None else (False, True)
    if not any(uso_cfdi_permitido(uso, regimen, persona_moral=p, fecha=fecha) for p in personas):
        raise DatoFiscalInvalido(
            f"El uso de CFDI {uso} no corresponde al régimen {regimen} del cliente según el catálogo del SAT."
        )


def validar_pago(forma: str | None, metodo: str | None, fecha: dt.date | None = None) -> None:
    """Forma (c_FormaPago) y método (c_MetodoPago) válidos y coherentes entre sí.

    PPD exige forma 99 (CFDI40105). PUE con 99 se rechaza: si se pagó en una
    exhibición, la forma ya se conoce (guía de llenado del Anexo 20).
    """
    fecha = fecha or _hoy()
    if forma:
        _clave("c_FormaPago", forma, fecha, "La forma de pago")
    if metodo:
        _clave("c_MetodoPago", metodo, fecha, "El método de pago")
    if metodo == METODO_PPD and forma and forma != FORMA_POR_DEFINIR:
        raise DatoFiscalInvalido(
            "Con pago en parcialidades o diferido (PPD) la forma de pago debe ser 99 (Por definir); "
            "la forma real va en el complemento de pago."
        )
    if metodo == METODO_PUE and forma == FORMA_POR_DEFINIR:
        raise DatoFiscalInvalido(
            "Con pago en una sola exhibición (PUE) indica cómo te pagaron; 99 (Por definir) sólo va con PPD."
        )


# ---------------------------------------------------------------- conjuntos


def validar_receptor(
    *,
    rfc: str | None,
    regimen: str | None,
    codigo_postal: str | None,
    uso_cfdi: str | None,
    fecha: dt.date | None = None,
) -> None:
    """Coherencia de los datos del cliente que vienen presentes; los ausentes no se exigen."""
    fecha = fecha or _hoy()
    persona = _persona_de(rfc)
    if regimen:
        if es_generico(rfc) and regimen != REGIMEN_SIN_OBLIGACIONES:
            raise DatoFiscalInvalido("Con RFC genérico el régimen fiscal debe ser 616 (Sin obligaciones fiscales).")
        validar_regimen(regimen, persona_moral=persona, fecha=fecha)
    if codigo_postal:
        validar_codigo_postal(codigo_postal, fecha)
    if uso_cfdi:
        validar_uso_cfdi(uso_cfdi, regimen=regimen, persona_moral=persona, fecha=fecha)


def validar_emisor(
    *, rfc: str | None, regimen: str | None, codigo_postal: str | None, fecha: dt.date | None = None
) -> None:
    fecha = fecha or _hoy()
    if es_generico(rfc):
        raise DatoFiscalInvalido("Un RFC genérico no puede emitir facturas; escribe el RFC de la constancia.")
    if regimen:
        validar_regimen(regimen, persona_moral=_persona_de(rfc), fecha=fecha)
    if codigo_postal:
        validar_codigo_postal(codigo_postal, fecha)


# ---------------------------------------------------------------- listo para facturar


@dataclass
class Preparacion:
    """Qué falta para facturar. ``faltantes`` bloquea; ``advertencias`` no."""

    listo: bool = True
    faltantes: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    def falta(self, texto: str) -> None:
        self.listo = False
        self.faltantes.append(texto)

    def como_dict(self) -> dict:
        return {"listo": self.listo, "faltantes": list(self.faltantes), "advertencias": list(self.advertencias)}


def _revisa(prep: Preparacion, funcion, *args, **kwargs) -> bool:
    try:
        funcion(*args, **kwargs)
    except DatoFiscalInvalido as exc:
        prep.falta(str(exc))
        return False
    return True


def tiene_regimen_capital(razon_social: str | None) -> bool:
    """¿La razón social trae el régimen de capital (S.A. de C.V., S. de R.L.…)? CFDI 4.0 la pide sin él."""
    return bool(_REGIMEN_CAPITAL.search((razon_social or "").strip()))


def _razon_social(prep: Preparacion, razon_social: str | None, rfc: str | None) -> None:
    if not (razon_social or "").strip():
        prep.falta("Razón social tal como aparece en la constancia de situación fiscal.")
    elif not es_generico(rfc) and _REGIMEN_CAPITAL.search(razon_social.strip()):
        prep.advertencias.append(
            "En CFDI 4.0 la razón social va sin el régimen de capital (S.A. de C.V., S. de R.L.…), "
            "tal como aparece en la constancia."
        )


def _rfc(prep: Preparacion, rfc: str | None) -> RevisionRfc | None:
    if not rfc:
        prep.falta("RFC.")
        return None
    try:
        revision = revisar_rfc(rfc)
    except DatoFiscalInvalido as exc:
        prep.falta(str(exc))
        return None
    if revision.advertencia:
        prep.advertencias.append(revision.advertencia)
    return revision


def preparacion_emisor(
    *,
    rfc: str | None,
    razon_social: str | None,
    regimen: str | None,
    codigo_postal: str | None,
    fecha: dt.date | None = None,
) -> Preparacion:
    fecha = fecha or _hoy()
    prep = Preparacion()
    revision = _rfc(prep, rfc)
    if revision is not None and revision.generico:
        prep.falta("Un RFC genérico no puede emitir facturas.")
    _razon_social(prep, razon_social, rfc)
    if not regimen:
        prep.falta("Régimen fiscal.")
    else:
        _revisa(prep, validar_regimen, regimen, persona_moral=revision.persona_moral if revision else None, fecha=fecha)
    if not codigo_postal:
        prep.falta("Código postal fiscal (lugar de expedición).")
    else:
        _revisa(prep, validar_codigo_postal, codigo_postal, fecha)
    return prep


def preparacion_receptor(
    *,
    rfc: str | None,
    razon_social: str | None,
    regimen: str | None,
    codigo_postal: str | None,
    uso_cfdi: str | None,
    fecha: dt.date | None = None,
) -> Preparacion:
    fecha = fecha or _hoy()
    prep = Preparacion()
    revision = _rfc(prep, rfc)
    generico = revision is not None and revision.generico is not None
    _razon_social(prep, razon_social, rfc)
    persona = revision.persona_moral if revision else None
    regimen_ok = False
    if not regimen:
        prep.falta("Régimen fiscal.")
    elif generico and regimen != REGIMEN_SIN_OBLIGACIONES:
        prep.falta("Con RFC genérico el régimen fiscal debe ser 616 (Sin obligaciones fiscales).")
    else:
        regimen_ok = _revisa(prep, validar_regimen, regimen, persona_moral=persona, fecha=fecha)
    if generico:
        # CFDI40149: con RFC genérico el domicilio del receptor es el lugar de expedición.
        pass
    elif not codigo_postal:
        prep.falta("Código postal fiscal.")
    else:
        _revisa(prep, validar_codigo_postal, codigo_postal, fecha)
    if not uso_cfdi:
        prep.falta("Uso de CFDI por defecto.")
    else:
        _revisa(prep, validar_uso_cfdi, uso_cfdi, regimen=regimen if regimen_ok else None, persona_moral=persona, fecha=fecha)
    return prep


# ---------------------------------------------------------------- opciones para la UI

CATALOGOS_PARA_CAPTURA = ("c_RegimenFiscal", "c_UsoCFDI", "c_FormaPago", "c_MetodoPago")


def opciones(
    nombre: str,
    *,
    fecha: dt.date | None = None,
    persona_moral: bool | None = None,
    regimen: str | None = None,
) -> list[dict]:
    """Claves vigentes de un catálogo chico para los selectores. El filtro por tipo de
    persona y por régimen se hace aquí, no en el front (invariante 19)."""
    if nombre not in CATALOGOS_PARA_CAPTURA:
        raise DatoFiscalInvalido("Ese catálogo no está disponible para captura.")
    fecha = fecha or _hoy()
    filas = []
    for registro in catalogo(nombre).vigentes(fecha):
        if nombre == "c_RegimenFiscal" and persona_moral is not None:
            columna = "persona_moral" if persona_moral else "persona_fisica"
            if not (registro[columna] or "").strip().lower().startswith("s"):
                continue
        if nombre == "c_UsoCFDI" and regimen:
            personas = (persona_moral,) if persona_moral is not None else (False, True)
            if not any(uso_cfdi_permitido(registro.clave, regimen, persona_moral=p, fecha=fecha) for p in personas):
                continue
        filas.append({"clave": registro.clave, "descripcion": (registro.descripcion or "").rstrip(".")})
    return filas


def persona_de_rfc(rfc: str | None) -> bool | None:
    return _persona_de(rfc)
