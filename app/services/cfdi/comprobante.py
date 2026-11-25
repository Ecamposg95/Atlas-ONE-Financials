"""CFDI 4.0 de ingreso como datos puros: importes con las reglas del Anexo 20 y XML sin sellar.

Nada aquí lee la base de datos ni conoce la operación de origen: recibe un
``Comprobante`` ya armado y produce números, resúmenes y bytes. Así lo mismo
sirve para el borrador que para el sellado del siguiente paso.

Redondeos y tolerancias (guía de llenado del Anexo 20, matriz de errores
CFDI40167 y CFDI40180):

- Importe del concepto: ``Cantidad × ValorUnitario``, aceptado entre
  ``(Cantidad − 10^−n/2)(ValorUnitario − 10^−m/2)`` truncado y
  ``(Cantidad + 10^−n/2 − 10^−12)(ValorUnitario + 10^−m/2 − 10^−12)``
  redondeado hacia arriba, con ``n`` y ``m`` los decimales escritos.
- Importe de un traslado o retención: ``Base × TasaOCuota``, entre
  ``(Base − 10^−d/2) × Tasa`` truncado y ``(Base + 10^−d/2 − 10^−12) × Tasa``
  redondeado hacia arriba, con ``d`` los decimales de la base.
- Los nodos del comprobante son la suma redondeada de los conceptos.
"""

from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from lxml import etree

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
ESQUEMA = "http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
# El XSD exige NoCertificado de 20 dígitos y Sello/Certificado presentes. En el
# borrador van vacíos: el XML no tiene validez fiscal hasta sellarlo.
NO_CERTIFICADO_BORRADOR = "0" * 20

TRASLADO = "TRASLADO"
RETENCION = "RETENCION"
IVA = "002"
CENTAVO = Decimal("0.01")
_EPSILON = Decimal("1e-12")


# ---------------------------------------------------------------- números


def decimales(valor: Decimal) -> int:
    exponente = Decimal(valor).normalize().as_tuple().exponent
    return max(0, -exponente) if isinstance(exponente, int) else 0


def redondear(valor: Decimal, lugares: int = 2) -> Decimal:
    return Decimal(valor).quantize(Decimal(1).scaleb(-lugares), rounding=ROUND_HALF_UP)


def _truncar(valor: Decimal, lugares: int) -> Decimal:
    return Decimal(valor).quantize(Decimal(1).scaleb(-lugares), rounding=ROUND_FLOOR)


def _hacia_arriba(valor: Decimal, lugares: int) -> Decimal:
    return Decimal(valor).quantize(Decimal(1).scaleb(-lugares), rounding=ROUND_CEILING)


def _media_unidad(lugares: int) -> Decimal:
    return Decimal(1).scaleb(-lugares) / 2


def limites_importe(cantidad: Decimal, valor_unitario: Decimal, lugares: int = 2) -> tuple[Decimal, Decimal]:
    """Límites del Importe de un concepto (CFDI40167), con los decimales tal como se escriben en el XML."""
    mc, mv = _media_unidad(decimales(cantidad)), _media_unidad(max(decimales(valor_unitario), 2))
    inferior = (cantidad - mc) * (valor_unitario - mv)
    superior = (cantidad + mc - _EPSILON) * (valor_unitario + mv - _EPSILON)
    return _truncar(inferior, lugares), _hacia_arriba(superior, lugares)


def limites_impuesto(base: Decimal, tasa: Decimal, lugares: int = 2) -> tuple[Decimal, Decimal]:
    """Límites del Importe de un traslado o retención (CFDI40180, CFDI40186); la base se escribe con 2 o más decimales."""
    media = _media_unidad(max(decimales(base), 2))
    return _truncar((base - media) * tasa, lugares), _hacia_arriba((base + media - _EPSILON) * tasa, lugares)


def formato(valor: Decimal, lugares: int) -> str:
    return f"{redondear(valor, lugares):f}"


def formato_libre(valor: Decimal, minimo: int = 0, maximo: int = 6) -> str:
    """Sin ceros de más a la derecha, pero con al menos ``minimo`` decimales."""
    lugares = min(max(decimales(valor), minimo), maximo)
    return formato(valor, lugares)


# ---------------------------------------------------------------- datos


@dataclass
class Impuesto:
    tipo: str  # TRASLADO | RETENCION
    impuesto: str  # c_Impuesto
    tipo_factor: str  # Tasa | Cuota | Exento
    tasa_o_cuota: Decimal | None
    base: Decimal
    importe: Decimal | None


@dataclass
class Concepto:
    clave_prod_serv: str
    cantidad: Decimal
    clave_unidad: str
    descripcion: str
    valor_unitario: Decimal
    importe: Decimal
    objeto_imp: str
    descuento: Decimal | None = None
    unidad: str | None = None
    no_identificacion: str | None = None
    impuestos: list[Impuesto] = field(default_factory=list)

    @property
    def base(self) -> Decimal:
        return self.importe - (self.descuento or Decimal("0"))

    @property
    def traslados(self) -> list[Impuesto]:
        return [i for i in self.impuestos if i.tipo == TRASLADO]

    @property
    def retenciones(self) -> list[Impuesto]:
        return [i for i in self.impuestos if i.tipo == RETENCION]


@dataclass
class Emisor:
    rfc: str | None
    nombre: str | None
    regimen_fiscal: str | None


@dataclass
class Receptor:
    rfc: str | None
    nombre: str | None
    domicilio_fiscal: str | None
    regimen_fiscal: str | None
    uso_cfdi: str | None


@dataclass
class Comprobante:
    serie: str | None
    folio: str | None
    fecha: dt.datetime  # hora local del lugar de expedición, sin zona
    lugar_expedicion: str | None
    emisor: Emisor
    receptor: Receptor
    conceptos: list[Concepto]
    subtotal: Decimal
    total: Decimal
    descuento: Decimal | None = None
    total_impuestos_trasladados: Decimal | None = None
    total_impuestos_retenidos: Decimal | None = None
    moneda: str = "MXN"
    tipo_cambio: Decimal | None = None
    forma_pago: str | None = None
    metodo_pago: str | None = None
    tipo_de_comprobante: str = "I"
    exportacion: str = "01"


@dataclass(frozen=True)
class TrasladoResumen:
    impuesto: str
    tipo_factor: str
    tasa_o_cuota: Decimal | None
    base: Decimal
    importe: Decimal | None


@dataclass(frozen=True)
class Resumen:
    """Lo que el comprobante debe decir según sus conceptos."""

    subtotal: Decimal
    descuento: Decimal | None
    traslados: tuple[TrasladoResumen, ...]
    retenciones: tuple[tuple[str, Decimal], ...]  # (impuesto, importe)
    total_trasladados: Decimal | None
    total_retenidos: Decimal | None
    total: Decimal


def resumir(conceptos: list[Concepto], lugares: int = 2) -> Resumen:
    subtotal = redondear(sum((c.importe for c in conceptos), Decimal("0")), lugares)
    con_descuento = [c.descuento for c in conceptos if c.descuento is not None]
    descuento = redondear(sum(con_descuento, Decimal("0")), lugares) if con_descuento else None

    grupos: OrderedDict[tuple, list[Impuesto]] = OrderedDict()
    retenidos: OrderedDict[str, Decimal] = OrderedDict()
    for concepto in conceptos:
        for imp in concepto.traslados:
            tasa = None if imp.tasa_o_cuota is None else Decimal(imp.tasa_o_cuota).quantize(Decimal("0.000001"))
            grupos.setdefault((imp.impuesto, imp.tipo_factor, tasa), []).append(imp)
        for imp in concepto.retenciones:
            retenidos[imp.impuesto] = retenidos.get(imp.impuesto, Decimal("0")) + (imp.importe or Decimal("0"))

    traslados = []
    for (impuesto, factor, tasa), lista in grupos.items():
        base = redondear(sum((i.base for i in lista), Decimal("0")), lugares)
        importe = None if factor == "Exento" else redondear(sum((i.importe or Decimal("0") for i in lista), Decimal("0")), lugares)
        traslados.append(TrasladoResumen(impuesto, factor, tasa, base, importe))
    no_exentos = [t for t in traslados if t.tipo_factor != "Exento"]
    total_trasladados = redondear(sum((t.importe for t in no_exentos), Decimal("0")), lugares) if no_exentos else None
    retenciones = tuple((imp, redondear(v, lugares)) for imp, v in retenidos.items())
    total_retenidos = redondear(sum((v for _, v in retenciones), Decimal("0")), lugares) if retenciones else None
    total = subtotal - (descuento or 0) + (total_trasladados or 0) - (total_retenidos or 0)
    return Resumen(
        subtotal=subtotal,
        descuento=descuento,
        traslados=tuple(traslados),
        retenciones=retenciones,
        total_trasladados=total_trasladados,
        total_retenidos=total_retenidos,
        total=redondear(total, lugares),
    )


# ---------------------------------------------------------------- XML


def _q(nombre: str) -> str:
    return f"{{{NS_CFDI}}}{nombre}"


def _atributos(nodo: etree._Element, pares: list[tuple[str, str | None]]) -> None:
    for nombre, valor in pares:
        if valor is not None and valor != "":
            nodo.set(nombre, valor)


def xml_sin_sellar(comp: Comprobante, *, leyenda: str | None = None) -> bytes:
    """XML del CFDI 4.0 con ``NoCertificado`` de ceros y ``Sello``/``Certificado`` vacíos.

    Los importes del comprobante salen de los datos guardados (no se
    recalculan): si no cuadran con los conceptos, la validación previa lo dice.
    ``leyenda`` se agrega como comentario antes del nodo raíz; no forma parte
    de la cadena original.
    """
    resumen = resumir(comp.conceptos)
    raiz = etree.Element(_q("Comprobante"), nsmap={"cfdi": NS_CFDI, "xsi": NS_XSI})
    raiz.set(f"{{{NS_XSI}}}schemaLocation", ESQUEMA)
    _atributos(
        raiz,
        [
            ("Version", "4.0"),
            ("Serie", comp.serie),
            ("Folio", comp.folio),
            ("Fecha", comp.fecha.replace(microsecond=0).isoformat(timespec="seconds")),
        ],
    )
    raiz.set("Sello", "")
    _atributos(raiz, [("FormaPago", comp.forma_pago)])
    raiz.set("NoCertificado", NO_CERTIFICADO_BORRADOR)
    raiz.set("Certificado", "")
    _atributos(
        raiz,
        [
            ("SubTotal", formato(comp.subtotal, 2)),
            ("Descuento", None if comp.descuento is None else formato(comp.descuento, 2)),
            ("Moneda", comp.moneda),
            ("TipoCambio", None if comp.tipo_cambio is None else formato_libre(comp.tipo_cambio)),
            ("Total", formato(comp.total, 2)),
            ("TipoDeComprobante", comp.tipo_de_comprobante),
            ("Exportacion", comp.exportacion),
            ("MetodoPago", comp.metodo_pago),
            ("LugarExpedicion", comp.lugar_expedicion),
        ],
    )

    emisor = etree.SubElement(raiz, _q("Emisor"))
    _atributos(
        emisor,
        [("Rfc", comp.emisor.rfc), ("Nombre", comp.emisor.nombre), ("RegimenFiscal", comp.emisor.regimen_fiscal)],
    )
    receptor = etree.SubElement(raiz, _q("Receptor"))
    _atributos(
        receptor,
        [
            ("Rfc", comp.receptor.rfc),
            ("Nombre", comp.receptor.nombre),
            ("DomicilioFiscalReceptor", comp.receptor.domicilio_fiscal),
            ("RegimenFiscalReceptor", comp.receptor.regimen_fiscal),
            ("UsoCFDI", comp.receptor.uso_cfdi),
        ],
    )

    conceptos = etree.SubElement(raiz, _q("Conceptos"))
    for c in comp.conceptos:
        nodo = etree.SubElement(conceptos, _q("Concepto"))
        _atributos(
            nodo,
            [
                ("ClaveProdServ", c.clave_prod_serv),
                ("NoIdentificacion", c.no_identificacion),
                ("Cantidad", formato_libre(c.cantidad)),
                ("ClaveUnidad", c.clave_unidad),
                ("Unidad", c.unidad),
                ("Descripcion", c.descripcion),
                ("ValorUnitario", formato_libre(c.valor_unitario, minimo=2)),
                ("Importe", formato(c.importe, 2)),
                ("Descuento", None if c.descuento is None else formato(c.descuento, 2)),
                ("ObjetoImp", c.objeto_imp),
            ],
        )
        if c.impuestos:
            impuestos = etree.SubElement(nodo, _q("Impuestos"))
            if c.traslados:
                traslados = etree.SubElement(impuestos, _q("Traslados"))
                for t in c.traslados:
                    _atributos(etree.SubElement(traslados, _q("Traslado")), _impuesto_concepto(t))
            if c.retenciones:
                retenciones = etree.SubElement(impuestos, _q("Retenciones"))
                for r in c.retenciones:
                    _atributos(etree.SubElement(retenciones, _q("Retencion")), _impuesto_concepto(r))

    if resumen.traslados or resumen.retenciones:
        impuestos = etree.SubElement(raiz, _q("Impuestos"))
        _atributos(
            impuestos,
            [
                (
                    "TotalImpuestosRetenidos",
                    None if comp.total_impuestos_retenidos is None else formato(comp.total_impuestos_retenidos, 2),
                ),
                (
                    "TotalImpuestosTrasladados",
                    None if comp.total_impuestos_trasladados is None else formato(comp.total_impuestos_trasladados, 2),
                ),
            ],
        )
        if resumen.retenciones:
            retenciones = etree.SubElement(impuestos, _q("Retenciones"))
            for impuesto, importe in resumen.retenciones:
                _atributos(
                    etree.SubElement(retenciones, _q("Retencion")),
                    [("Impuesto", impuesto), ("Importe", formato(importe, 2))],
                )
        if resumen.traslados:
            traslados = etree.SubElement(impuestos, _q("Traslados"))
            for t in resumen.traslados:
                _atributos(
                    etree.SubElement(traslados, _q("Traslado")),
                    [
                        ("Base", formato(t.base, 2)),
                        ("Impuesto", t.impuesto),
                        ("TipoFactor", t.tipo_factor),
                        ("TasaOCuota", None if t.tasa_o_cuota is None else formato(t.tasa_o_cuota, 6)),
                        ("Importe", None if t.importe is None else formato(t.importe, 2)),
                    ],
                )

    documento = etree.ElementTree(raiz)
    if leyenda:
        raiz.addprevious(etree.Comment(f" {leyenda} "))
    return etree.tostring(documento, xml_declaration=True, encoding="UTF-8")


def _impuesto_concepto(imp: Impuesto) -> list[tuple[str, str | None]]:
    exento = imp.tipo_factor == "Exento"
    return [
        ("Base", formato_libre(imp.base, minimo=2)),
        ("Impuesto", imp.impuesto),
        ("TipoFactor", imp.tipo_factor),
        ("TasaOCuota", None if exento or imp.tasa_o_cuota is None else formato(imp.tasa_o_cuota, 6)),
        ("Importe", None if exento or imp.importe is None else formato(imp.importe, 2)),
    ]
