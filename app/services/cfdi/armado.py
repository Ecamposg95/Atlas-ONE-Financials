"""Conceptos e impuestos del CFDI a partir de los importes de una operación.

Regla de oro: **nunca se corrigen los montos de la operación**. La operación
(ingreso o cuenta por cobrar) ya está en el libro con su subtotal, su IVA y su
total; el CFDI tiene que decir exactamente eso. Si con las reglas de redondeo
y tolerancia del Anexo 20 no se puede, se lanza ``ErrorArmado`` con el motivo
en español y la operación se corrige en su módulo (no aquí).

Supuestos (documentados para el contador en ``app/services/cfdi/README.md``):

- Sin renglones en la operación se arma **un solo concepto**: cantidad 1,
  valor unitario = subtotal de la operación, descripción de la operación y la
  clave de producto/servicio y unidad que se indiquen (por omisión
  ``01010101`` "No existe en el catálogo" y ``E48`` "Unidad de servicio").
- El subtotal de la operación es la base después de descuentos (lo que se
  grava). En el CFDI, ``SubTotal`` es antes de descuentos, así que se compara
  ``SubTotal − Descuento`` con el subtotal de la operación.
- Tasa 0 en la operación no dice si es tasa 0 %, exenta o no objeto: hay que
  decirlo explícitamente; no se adivina.
- Con varios renglones, el IVA de cada uno se redondea a centavos y la
  diferencia contra el IVA de la operación se reparte de a un centavo, en
  orden, sólo donde la tolerancia del SAT lo permite.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.cfdi.comprobante import (
    CENTAVO,
    IVA,
    TRASLADO,
    Concepto,
    Impuesto,
    limites_importe,
    limites_impuesto,
    redondear,
)

CLAVE_PROD_SERV_DEFECTO = "01010101"
CLAVE_UNIDAD_DEFECTO = "E48"

# Tratamiento de IVA de la operación.
GRAVADO = "gravado"  # tasa 16 % u 8 % (la de la operación)
TASA_CERO = "tasa_0"
EXENTO = "exento"
NO_OBJETO = "no_objeto"
TRATAMIENTOS = (GRAVADO, TASA_CERO, EXENTO, NO_OBJETO)
TASAS_GRAVADAS = (Decimal("0.16"), Decimal("0.08"))


class ErrorArmado(ValueError):
    """La operación no se puede expresar como CFDI sin tocar sus montos. Mensaje en español."""


@dataclass(frozen=True)
class Operacion:
    descripcion: str
    subtotal: Decimal  # base gravable (después de descuentos)
    impuesto: Decimal  # IVA
    total: Decimal
    tasa: Decimal  # 0.16, 0.08, 0


@dataclass(frozen=True)
class Renglon:
    descripcion: str
    cantidad: Decimal
    valor_unitario: Decimal
    descuento: Decimal | None = None
    clave_prod_serv: str | None = None
    clave_unidad: str | None = None
    unidad: str | None = None
    no_identificacion: str | None = None


@dataclass(frozen=True)
class Armado:
    conceptos: list[Concepto]
    supuestos: list[str]


def _dinero(valor: Decimal) -> str:
    return f"${redondear(valor):,.2f}"


def resolver_tratamiento(tasa: Decimal, tratamiento: str | None) -> str:
    tasa = Decimal(tasa)
    if tratamiento is not None and tratamiento not in TRATAMIENTOS:
        raise ErrorArmado("El tratamiento de IVA debe ser gravado, tasa_0, exento o no_objeto.")
    if tasa in TASAS_GRAVADAS:
        if tratamiento not in (None, GRAVADO):
            raise ErrorArmado(
                f"La operación lleva IVA al {tasa * 100:.0f} %; no puede facturarse como {tratamiento.replace('_', ' ')}."
            )
        return GRAVADO
    if tasa != 0:
        raise ErrorArmado(f"La tasa de IVA {tasa} de la operación no es una tasa que se pueda facturar (16 %, 8 % o 0).")
    if tratamiento in (None, GRAVADO):
        raise ErrorArmado(
            "La operación no lleva IVA. Indica si es tasa 0 %, exenta o no objeto de impuesto: "
            "cada una se factura distinto y no se adivina."
        )
    return tratamiento


def _impuestos(base: Decimal, tratamiento: str, tasa: Decimal) -> tuple[str, list[Impuesto]]:
    """ObjetoImp y traslados de un concepto, con el importe aún sin ajustar."""
    if tratamiento == NO_OBJETO:
        return "01", []
    if tratamiento == EXENTO:
        return "02", [Impuesto(TRASLADO, IVA, "Exento", None, base, None)]
    tasa6 = Decimal(tasa).quantize(Decimal("0.000001"))
    return "02", [Impuesto(TRASLADO, IVA, "Tasa", tasa6, base, redondear(base * tasa6))]


def armar(
    operacion: Operacion,
    *,
    tratamiento: str | None = None,
    renglones: list[Renglon] | None = None,
    clave_prod_serv: str | None = None,
    clave_unidad: str | None = None,
) -> Armado:
    tratamiento = resolver_tratamiento(operacion.tasa, tratamiento)
    subtotal, impuesto, total = (redondear(Decimal(v)) for v in (operacion.subtotal, operacion.impuesto, operacion.total))
    clave_ps = clave_prod_serv or CLAVE_PROD_SERV_DEFECTO
    clave_u = clave_unidad or CLAVE_UNIDAD_DEFECTO
    supuestos: list[str] = []

    if subtotal + impuesto != total:
        raise ErrorArmado(
            f"La operación no cuadra: subtotal {_dinero(subtotal)} más IVA {_dinero(impuesto)} "
            f"no da el total {_dinero(total)}."
        )
    if tratamiento in (EXENTO, NO_OBJETO, TASA_CERO) and impuesto != 0:
        raise ErrorArmado(f"La operación trae IVA de {_dinero(impuesto)} pero se marcó sin IVA cobrado.")

    if not renglones:
        renglones = [Renglon(descripcion=operacion.descripcion, cantidad=Decimal("1"), valor_unitario=subtotal)]
        supuestos.append(
            f"La operación no tiene renglones: se factura como un solo concepto con clave {clave_ps} "
            f"y unidad {clave_u}, por {_dinero(subtotal)} antes de impuestos."
        )
        if clave_ps == CLAVE_PROD_SERV_DEFECTO:
            supuestos.append(
                "La clave 01010101 significa 'No existe en el catálogo'; confirma con tu contador la clave "
                "de producto o servicio que corresponde."
            )
    if tratamiento == TASA_CERO:
        supuestos.append("La operación sin IVA se factura a tasa 0 % (IVA trasladado en 0.00).")
    elif tratamiento == EXENTO:
        supuestos.append("La operación sin IVA se factura como exenta de IVA (TipoFactor Exento).")
    elif tratamiento == NO_OBJETO:
        supuestos.append("La operación sin IVA se factura como no objeto de impuesto (ObjetoImp 01).")

    conceptos: list[Concepto] = []
    for numero, r in enumerate(renglones, start=1):
        cantidad, valor_unitario = Decimal(r.cantidad), Decimal(r.valor_unitario)
        if cantidad <= 0 or valor_unitario <= 0:
            raise ErrorArmado(f"Renglón {numero}: cantidad y valor unitario deben ser mayores que cero.")
        importe = redondear(cantidad * valor_unitario)
        inferior, superior = limites_importe(cantidad, valor_unitario)
        if not inferior <= importe <= superior:  # sólo con más de 6 decimales; defensa
            raise ErrorArmado(f"Renglón {numero}: el importe no cabe en la tolerancia del SAT.")
        descuento = None if r.descuento in (None, 0, Decimal("0")) else redondear(Decimal(r.descuento))
        if descuento is not None and not Decimal("0") < descuento <= importe:
            raise ErrorArmado(f"Renglón {numero}: el descuento no puede ser negativo ni mayor que el importe.")
        base = importe - (descuento or Decimal("0"))
        if tratamiento != NO_OBJETO and base <= 0:
            raise ErrorArmado(f"Renglón {numero}: con el descuento la base del impuesto queda en cero.")
        objeto, impuestos = _impuestos(base, tratamiento, operacion.tasa)
        conceptos.append(
            Concepto(
                clave_prod_serv=r.clave_prod_serv or clave_ps,
                cantidad=cantidad,
                clave_unidad=r.clave_unidad or clave_u,
                unidad=r.unidad,
                no_identificacion=r.no_identificacion,
                descripcion=r.descripcion.strip()[:1000] or operacion.descripcion,
                valor_unitario=valor_unitario,
                importe=importe,
                descuento=descuento,
                objeto_imp=objeto,
                impuestos=impuestos,
            )
        )

    bases = sum((c.base for c in conceptos), Decimal("0"))
    if bases != subtotal:
        raise ErrorArmado(
            f"Los renglones suman {_dinero(bases)} después de descuentos y la operación tiene subtotal "
            f"{_dinero(subtotal)}. Corrige los renglones o la operación; aquí no se ajustan montos."
        )
    if tratamiento in (GRAVADO, TASA_CERO):
        _cuadrar_iva(conceptos, impuesto)
    return Armado(conceptos=conceptos, supuestos=supuestos)


def _cuadrar_iva(conceptos: list[Concepto], objetivo: Decimal) -> None:
    """Hace que la suma de los IVA por concepto sea el IVA de la operación, moviendo
    centavos sólo dentro de la tolerancia del SAT de cada concepto."""
    traslados = [c.traslados[0] for c in conceptos]
    limites = [limites_impuesto(t.base, t.tasa_o_cuota) for t in traslados]
    diferencia = objetivo - sum((t.importe for t in traslados), Decimal("0"))
    paso = CENTAVO if diferencia > 0 else -CENTAVO
    while diferencia != 0:
        movido = False
        for t, (inferior, superior) in zip(traslados, limites, strict=True):
            if inferior <= t.importe + paso <= superior:
                t.importe += paso
                diferencia -= paso
                movido = True
                if diferencia == 0:
                    break
        if not movido:
            if len(traslados) == 1:
                rango = f"entre {_dinero(limites[0][0])} y {_dinero(limites[0][1])}"
            else:
                rango = f"cerca de {_dinero(objetivo - diferencia)}"
            raise ErrorArmado(
                f"El IVA de la operación ({_dinero(objetivo)}) no corresponde a su base dentro de las "
                f"tolerancias del SAT: debería quedar {rango}. Corrige la operación; aquí no se ajustan montos."
            )
