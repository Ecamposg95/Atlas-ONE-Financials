"""Hora local del lugar de expedición según ``c_CodigoPostal`` (CFDI40101).

El atributo ``Fecha`` del CFDI es la hora local donde se expide, sin zona. El
catálogo del SAT trae por código postal el huso, la diferencia con UTC en
invierno y en verano y, si aplica, cuándo cambia (p. ej. "Marzo / Segundo
domingo / 02:00"). Se usa eso tal cual, sin base de zonas IANA: si el SAT
cambia una regla, cambia el catálogo y no el código.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.services.cfdi.catalogos import catalogo

_MESES = {
    m: i
    for i, m in enumerate(
        (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        start=1,
    )
}
_ORDINALES = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "último": -1, "ultimo": -1}


class CodigoPostalSinHuso(ValueError):
    pass


@dataclass(frozen=True)
class HoraLocal:
    local: dt.datetime  # sin zona, como va en el atributo Fecha
    utc: dt.datetime  # con zona UTC
    huso: str  # "Tiempo del Centro", ...
    diferencia_horas: int  # -6, -5, ...


def _domingo(anio: int, mes: int, ordinal: int) -> dt.date:
    if ordinal > 0:
        dia = dt.date(anio, mes, 1)
        dia += dt.timedelta(days=(6 - dia.weekday()) % 7)
        return dia + dt.timedelta(weeks=ordinal - 1)
    siguiente = dt.date(anio + (mes == 12), mes % 12 + 1, 1)
    dia = siguiente - dt.timedelta(days=1)
    return dia - dt.timedelta(days=(dia.weekday() - 6) % 7)


def _cambio(anio: int, mes: str | None, dia: str | None, hora: str | None) -> dt.datetime | None:
    if not (mes and dia and hora):
        return None
    numero_mes = _MESES.get(mes.strip().lower())
    ordinal = _ORDINALES.get(dia.strip().split()[0].lower())
    if numero_mes is None or ordinal is None:
        raise CodigoPostalSinHuso(f"Regla de horario de verano no reconocida: {mes} / {dia}")
    hh, mm = (int(p) for p in hora.strip().split(":")[:2])
    return dt.datetime.combine(_domingo(anio, numero_mes, ordinal), dt.time(hh, mm))


def hora_local(codigo_postal: str, instante_utc: dt.datetime) -> HoraLocal:
    """Hora local en ``codigo_postal`` para un instante UTC (con o sin tzinfo UTC)."""
    registro = catalogo("c_CodigoPostal").obtener(codigo_postal)
    if registro is None:
        raise CodigoPostalSinHuso(f"El código postal {codigo_postal} no existe en el catálogo del SAT.")
    if instante_utc.tzinfo is not None:
        instante_utc = instante_utc.astimezone(dt.timezone.utc).replace(tzinfo=None)
    invierno = int(registro["diferencia_horaria_invierno"] or "-6")
    verano = int(registro["diferencia_horaria_verano"] or invierno)
    diferencia = invierno
    if verano != invierno:
        # Las horas de cambio son de reloj local: el inicio, en horario de
        # invierno; el fin, en horario de verano.
        anio = (instante_utc + dt.timedelta(hours=invierno)).year
        inicio = _cambio(
            anio,
            registro["mes_inicio_horario_verano"],
            registro["dia_inicio_horario_verano"],
            registro["dia_inicio_horario_verano_2"],
        )
        fin = _cambio(
            anio,
            registro["mes_inicio_horario_invierno"],
            registro["dia_inicio_horario_invierno"],
            registro["dia_inicio_horario_invierno_2"],
        )
        if inicio and fin:
            inicio_utc = inicio - dt.timedelta(hours=invierno)
            fin_utc = fin - dt.timedelta(hours=verano)
            if inicio_utc <= instante_utc < fin_utc:
                diferencia = verano
    local = (instante_utc + dt.timedelta(hours=diferencia)).replace(microsecond=0)
    return HoraLocal(
        local=local,
        utc=instante_utc.replace(microsecond=0, tzinfo=dt.timezone.utc),
        huso=registro["descripcion_del_huso_horario"] or "",
        diferencia_horas=diferencia,
    )
