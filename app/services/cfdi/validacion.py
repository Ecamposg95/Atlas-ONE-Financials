"""Validación previa determinista de un CFDI 4.0 de ingreso, antes de sellar.

Devuelve una lista de problemas en español. Cada problema lleva el código de
la matriz de errores del SAT cuando la regla viene de ahí (``CFDI40xxx``), el
código de validación del proveedor cuando es de las que hace el PAC (``401``,
la ventana de 72 horas) o un código propio con prefijo ``ATLAS-`` cuando es
una regla de Atlas Financials (cuadre con la operación, cosas aún no
soportadas). Un problema bloquea el timbrado; una advertencia no.

Las claves se validan **con la fecha de emisión del comprobante**, no con la
de hoy. Lo que sólo puede revisar el SAT o el proveedor (padrón de RFC,
nombre y código postal del receptor contra la lista de contribuyentes) no se
revisa aquí.

Nada aquí toca la base de datos, pólizas ni saldos.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from app.services.cfdi import datos_fiscales as df
from app.services.cfdi import xml_sat
from app.services.cfdi.armado import CLAVE_PROD_SERV_DEFECTO, Operacion
from app.services.cfdi.catalogos import EstadoClave, catalogo, tasa_o_cuota_valida, uso_cfdi_permitido
from app.services.cfdi.comprobante import (
    Comprobante,
    decimales,
    limites_importe,
    limites_impuesto,
    redondear,
    resumir,
    xml_sin_sellar,
)

VENTANA_TIMBRADO = dt.timedelta(hours=72)
# Margen para relojes desfasados; el PAC rechaza fechas futuras.
TOLERANCIA_FUTURO = dt.timedelta(minutes=5)
NOMBRE_PUBLICO_GENERAL = "PUBLICO EN GENERAL"


@dataclass(frozen=True)
class Problema:
    codigo: str
    campo: str
    mensaje: str


@dataclass
class Validacion:
    problemas: list[Problema] = field(default_factory=list)
    advertencias: list[Problema] = field(default_factory=list)

    @property
    def listo(self) -> bool:
        return not self.problemas

    def como_dict(self) -> dict:
        return {
            "listo": self.listo,
            "problemas": [asdict(p) for p in self.problemas],
            "advertencias": [asdict(p) for p in self.advertencias],
        }


@dataclass(frozen=True)
class Contexto:
    ahora_utc: dt.datetime
    fecha_emision_utc: dt.datetime
    operacion: Operacion | None = None
    operacion_cancelada: bool = False
    # PUE/PPD contra cómo está la operación: True si ya se cobró completa.
    operacion_liquidada: bool | None = None
    tasa_operacion: Decimal | None = None


class _Revision:
    def __init__(self, comp: Comprobante, fecha: dt.date):
        self.comp = comp
        self.fecha = fecha
        self.resultado = Validacion()

    def problema(self, codigo: str, campo: str, mensaje: str) -> None:
        self.resultado.problemas.append(Problema(codigo, campo, mensaje))

    def advertencia(self, codigo: str, campo: str, mensaje: str) -> None:
        self.resultado.advertencias.append(Problema(codigo, campo, mensaje))

    def clave(self, nombre: str, clave: str | None, codigo: str, campo: str, que: str) -> bool:
        """Clave presente, existente y vigente en la fecha de emisión."""
        if not clave:
            self.problema(codigo, campo, f"Falta {que}.")
            return False
        estado = catalogo(nombre).estado(clave, self.fecha)
        if estado is EstadoClave.INEXISTENTE:
            self.problema(codigo, campo, f"{que.capitalize()} {clave} no existe en el catálogo {nombre} del SAT.")
            return False
        if estado is EstadoClave.NO_VIGENTE:
            self.problema(
                codigo,
                campo,
                f"{que.capitalize()} {clave} no está vigente el {self.fecha.isoformat()} en el catálogo {nombre}.",
            )
            return False
        return True


def _rfc(rev: _Revision, rfc: str | None, campo: str, quien: str) -> df.RevisionRfc | None:
    if not rfc:
        rev.problema("ATLAS-DATOS", campo, f"Falta el RFC del {quien}.")
        return None
    try:
        revision = df.revisar_rfc(rfc)
    except df.DatoFiscalInvalido as exc:
        rev.problema("ATLAS-DATOS", campo, f"RFC del {quien}: {exc}")
        return None
    if revision.advertencia:
        rev.advertencia("ATLAS-RFC", campo, revision.advertencia)
    return revision


def _regimen(rev: _Revision, regimen: str | None, persona_moral: bool | None, codigos: tuple[str, str], campo: str, quien: str):
    if not rev.clave("c_RegimenFiscal", regimen, codigos[0], campo, f"el régimen fiscal del {quien}"):
        return
    if persona_moral is None:
        return
    registro = catalogo("c_RegimenFiscal").obtener(regimen)
    columna = "persona_moral" if persona_moral else "persona_fisica"
    if not (registro[columna] or "").strip().lower().startswith("s"):
        tipo = "moral" if persona_moral else "física"
        rev.problema(
            codigos[1],
            campo,
            f"El régimen {regimen} ({(registro.descripcion or '').rstrip('.')}) del {quien} no aplica a una persona {tipo}.",
        )


def _emisor(rev: _Revision) -> None:
    emisor = rev.comp.emisor
    revision = _rfc(rev, emisor.rfc, "emisor.rfc", "emisor")
    if revision is not None and revision.generico:
        rev.problema("ATLAS-DATOS", "emisor.rfc", "Un RFC genérico no puede emitir facturas.")
    if not (emisor.nombre or "").strip():
        rev.problema("ATLAS-DATOS", "emisor.nombre", "Falta la razón social del emisor tal como aparece en su constancia.")
    _regimen(
        rev,
        emisor.regimen_fiscal,
        revision.persona_moral if revision and not revision.generico else None,
        ("CFDI40140", "CFDI40141"),
        "emisor.regimen_fiscal",
        "emisor",
    )
    rev.clave("c_CodigoPostal", rev.comp.lugar_expedicion, "CFDI40126", "lugar_expedicion", "el código postal del lugar de expedición")
    if df.tiene_regimen_capital(emisor.nombre):
        rev.advertencia(
            "ATLAS-NOMBRE",
            "emisor.nombre",
            "En CFDI 4.0 la razón social va sin el régimen de capital (S.A. de C.V., S. de R.L.…), tal como aparece en la constancia.",
        )


def _receptor(rev: _Revision) -> None:
    receptor, comp = rev.comp.receptor, rev.comp
    revision = _rfc(rev, receptor.rfc, "receptor.rfc", "cliente")
    generico = revision.generico if revision else None
    nombre = (receptor.nombre or "").strip()
    if not nombre:
        rev.problema("ATLAS-DATOS", "receptor.nombre", "Falta la razón social del cliente tal como aparece en su constancia.")
    elif generico is None and df.tiene_regimen_capital(nombre):
        rev.advertencia(
            "ATLAS-NOMBRE",
            "receptor.nombre",
            "En CFDI 4.0 la razón social va sin el régimen de capital (S.A. de C.V., S. de R.L.…), tal como aparece en la constancia.",
        )
    if generico == "extranjero":
        rev.problema(
            "ATLAS-NO-SOPORTADO",
            "receptor.rfc",
            "Facturar a un cliente extranjero (XEXX010101000) pide residencia fiscal y número de registro tributario; aún no está soportado.",
        )
    if generico == "nacional" and nombre.upper() == NOMBRE_PUBLICO_GENERAL:
        rev.problema(
            "CFDI40130",
            "receptor.nombre",
            "Con RFC XAXX010101000 y nombre PUBLICO EN GENERAL el SAT pide el nodo de factura global; "
            "para una factura individual usa el nombre del cliente.",
        )

    if generico:
        if receptor.regimen_fiscal != df.REGIMEN_SIN_OBLIGACIONES:
            rev.problema(
                "CFDI40159",
                "receptor.regimen_fiscal",
                f"Con RFC genérico el régimen fiscal del cliente debe ser 616 (Sin obligaciones fiscales), no {receptor.regimen_fiscal or 'vacío'}.",
            )
        if receptor.domicilio_fiscal != comp.lugar_expedicion:
            rev.problema(
                "CFDI40149",
                "receptor.domicilio_fiscal",
                "Con RFC genérico el código postal del cliente debe ser el del lugar de expedición "
                f"({comp.lugar_expedicion or 'sin capturar'}).",
            )
    else:
        _regimen(
            rev,
            receptor.regimen_fiscal,
            revision.persona_moral if revision else None,
            ("CFDI40157", "CFDI40158"),
            "receptor.regimen_fiscal",
            "cliente",
        )
        rev.clave("c_CodigoPostal", receptor.domicilio_fiscal, "ATLAS-DATOS", "receptor.domicilio_fiscal", "el código postal fiscal del cliente")

    if rev.clave("c_UsoCFDI", receptor.uso_cfdi, "CFDI40160", "receptor.uso_cfdi", "el uso de CFDI") and receptor.regimen_fiscal:
        personas = (revision.persona_moral,) if revision and not revision.generico else (False,)
        if not any(uso_cfdi_permitido(receptor.uso_cfdi, receptor.regimen_fiscal, persona_moral=p, fecha=rev.fecha) for p in personas):
            rev.problema(
                "CFDI40161",
                "receptor.uso_cfdi",
                f"El uso de CFDI {receptor.uso_cfdi} no corresponde al régimen {receptor.regimen_fiscal} ni al tipo de persona del cliente.",
            )


def _fecha(rev: _Revision, ctx: Contexto) -> None:
    edad = ctx.ahora_utc - ctx.fecha_emision_utc
    if edad > VENTANA_TIMBRADO:
        rev.problema(
            "401",
            "fecha",
            f"La factura está fechada hace más de 72 horas ({rev.comp.fecha:%d/%m/%Y %H:%M}); el proveedor la rechazaría. "
            "Vuelve a prepararla para fecharla hoy.",
        )
    elif edad < -TOLERANCIA_FUTURO:
        rev.problema("401", "fecha", "La fecha de la factura es posterior a la hora actual del lugar de expedición.")
    if rev.comp.fecha.year < 2022:
        rev.problema("CFDI40101", "fecha", "La fecha de la factura no puede ser anterior a 2022 en CFDI 4.0.")


def _moneda_y_pago(rev: _Revision, ctx: Contexto) -> None:
    comp = rev.comp
    if rev.clave("c_Moneda", comp.moneda, "CFDI40113", "moneda", "la moneda") and comp.moneda != "MXN":
        rev.problema("ATLAS-NO-SOPORTADO", "moneda", "Por ahora sólo se factura en pesos mexicanos (MXN).")
    if comp.tipo_cambio is not None and comp.moneda == "MXN" and comp.tipo_cambio != 1:
        rev.problema("CFDI40114", "tipo_cambio", "En pesos mexicanos el tipo de cambio se omite o vale 1.")
    rev.clave("c_Exportacion", comp.exportacion, "CFDI40123", "exportacion", "la clave de exportación")
    forma_ok = rev.clave("c_FormaPago", comp.forma_pago, "CFDI40104", "forma_pago", "la forma de pago")
    metodo_ok = rev.clave("c_MetodoPago", comp.metodo_pago, "CFDI40124", "metodo_pago", "el método de pago (PUE o PPD)")
    if forma_ok and metodo_ok:
        if comp.metodo_pago == df.METODO_PPD and comp.forma_pago != df.FORMA_POR_DEFINIR:
            rev.problema(
                "CFDI40105",
                "forma_pago",
                "Con pago en parcialidades o diferido (PPD) la forma de pago debe ser 99 (Por definir); la real va en el complemento de pago.",
            )
        if comp.metodo_pago == df.METODO_PUE and comp.forma_pago == df.FORMA_POR_DEFINIR:
            rev.problema(
                "ATLAS-PUE-99",
                "forma_pago",
                "Con pago en una sola exhibición (PUE) indica cómo te pagaron; 99 (Por definir) sólo va con PPD.",
            )
    if ctx.operacion_liquidada is False and comp.metodo_pago == df.METODO_PUE:
        rev.advertencia(
            "ATLAS-PUE-PENDIENTE",
            "metodo_pago",
            "La operación todavía no está cobrada completa y la factura dice PUE (pagada en una exhibición). "
            "Si se cobrará después, usa PPD con forma 99 y emite el complemento de pago al cobrar.",
        )
    if ctx.operacion_liquidada is True and comp.metodo_pago == df.METODO_PPD:
        rev.advertencia(
            "ATLAS-PPD-PAGADA",
            "metodo_pago",
            "La operación ya está cobrada y la factura dice PPD: necesitarás emitir el complemento de pago.",
        )


def _conceptos(rev: _Revision) -> None:
    comp = rev.comp
    if not comp.conceptos:
        rev.problema("ATLAS-DATOS", "conceptos", "La factura no tiene conceptos.")
        return
    for n, c in enumerate(comp.conceptos, start=1):
        campo = f"conceptos[{n}]"
        if rev.clave("c_ClaveProdServ", c.clave_prod_serv, "CFDI40162", f"{campo}.clave_prod_serv", f"la clave de producto o servicio del concepto {n}"):
            registro = catalogo("c_ClaveProdServ").obtener(c.clave_prod_serv)
            if registro["complemento_que_debe_incluir"]:
                rev.problema(
                    "CFDI40163",
                    f"{campo}.clave_prod_serv",
                    f"La clave {c.clave_prod_serv} exige el complemento '{registro['complemento_que_debe_incluir']}', que aún no está soportado.",
                )
            exige_iva = (registro["incluir_iva_trasladado"] or "").strip().lower().startswith("s")
            if exige_iva and not any(t.impuesto == "002" for t in c.traslados):
                rev.problema("CFDI40164", f"{campo}.impuestos", f"La clave {c.clave_prod_serv} exige IVA trasladado.")
            if c.clave_prod_serv == CLAVE_PROD_SERV_DEFECTO:
                rev.advertencia(
                    "ATLAS-CLAVE-GENERICA",
                    f"{campo}.clave_prod_serv",
                    "La clave 01010101 ('No existe en el catálogo') es genérica; confirma con tu contador la clave que corresponde.",
                )
        rev.clave("c_ClaveUnidad", c.clave_unidad, "CFDI40165", f"{campo}.clave_unidad", f"la clave de unidad del concepto {n}")
        if not (c.descripcion or "").strip():
            rev.problema("ATLAS-DATOS", f"{campo}.descripcion", f"El concepto {n} no tiene descripción.")
        if c.valor_unitario <= 0:
            rev.problema("CFDI40166", f"{campo}.valor_unitario", f"El valor unitario del concepto {n} debe ser mayor que cero.")
        if c.cantidad <= 0:
            rev.problema("ATLAS-DATOS", f"{campo}.cantidad", f"La cantidad del concepto {n} debe ser mayor que cero.")
        if decimales(c.cantidad) > 6 or decimales(c.valor_unitario) > 6:
            rev.problema("ATLAS-DATOS", campo, f"Cantidad y valor unitario del concepto {n} admiten hasta seis decimales.")
        inferior, superior = limites_importe(c.cantidad, c.valor_unitario)
        if not inferior <= c.importe <= superior:
            rev.problema(
                "CFDI40167",
                f"{campo}.importe",
                f"El importe del concepto {n} ({c.importe}) no corresponde a cantidad por valor unitario (entre {inferior} y {superior}).",
            )
        if c.descuento is not None:
            if decimales(c.descuento) > 2:
                rev.problema("CFDI40168", f"{campo}.descuento", f"El descuento del concepto {n} tiene más decimales que su importe.")
            if c.descuento > c.importe:
                rev.problema("CFDI40169", f"{campo}.descuento", f"El descuento del concepto {n} es mayor que su importe.")
        _impuestos_concepto(rev, c, n, campo)


def _impuestos_concepto(rev: _Revision, c, n: int, campo: str) -> None:
    if not rev.clave("c_ObjetoImp", c.objeto_imp, "CFDI40170", f"{campo}.objeto_imp", f"el objeto de impuesto del concepto {n}"):
        return
    if c.objeto_imp == "02" and not c.impuestos:
        rev.problema("CFDI40171", f"{campo}.impuestos", f"El concepto {n} es objeto de impuesto (02) y no trae impuestos.")
    if c.objeto_imp in ("01", "03", "04", "05") and c.impuestos:
        rev.problema("CFDI40172", f"{campo}.impuestos", f"El concepto {n} con objeto de impuesto {c.objeto_imp} no debe traer impuestos.")
    if c.objeto_imp not in ("01", "02"):
        rev.problema("ATLAS-NO-SOPORTADO", f"{campo}.objeto_imp", f"El objeto de impuesto {c.objeto_imp} aún no está soportado.")
    for imp in c.impuestos:
        traslado = imp.tipo == "TRASLADO"
        prefijo = f"{campo}.{'traslado' if traslado else 'retencion'}"
        if imp.base <= 0:
            rev.problema("CFDI40174" if traslado else "CFDI40181", f"{prefijo}.base", f"La base del impuesto del concepto {n} debe ser mayor que cero.")
        if imp.base != c.base:
            rev.problema(
                "ATLAS-BASE",
                f"{prefijo}.base",
                f"La base del impuesto del concepto {n} ({imp.base}) no es su importe menos descuento ({c.base}).",
            )
        rev.clave("c_Impuesto", imp.impuesto, "CFDI40175" if traslado else "CFDI40182", f"{prefijo}.impuesto", "el impuesto")
        rev.clave("c_TipoFactor", imp.tipo_factor, "CFDI40176" if traslado else "CFDI40183", f"{prefijo}.tipo_factor", "el tipo de factor")
        if imp.tipo_factor == "Exento":
            if not traslado:
                rev.problema("CFDI40184", f"{prefijo}.tipo_factor", "Una retención no puede ser exenta.")
            elif imp.tasa_o_cuota is not None or imp.importe is not None:
                rev.problema("CFDI40177", prefijo, f"El traslado exento del concepto {n} no lleva tasa ni importe.")
            continue
        if imp.tasa_o_cuota is None or imp.importe is None:
            rev.problema("CFDI40178", prefijo, f"El impuesto del concepto {n} debe llevar tasa e importe.")
            continue
        if not tasa_o_cuota_valida(imp.impuesto, imp.tipo_factor, imp.tasa_o_cuota, traslado=traslado, fecha=rev.fecha):
            rev.problema(
                "CFDI40179" if traslado else "CFDI40185",
                f"{prefijo}.tasa_o_cuota",
                f"La tasa {imp.tasa_o_cuota} no está en el catálogo c_TasaOCuota para ese impuesto y factor.",
            )
        inferior, superior = limites_impuesto(imp.base, imp.tasa_o_cuota)
        if not inferior <= imp.importe <= superior:
            rev.problema(
                "CFDI40180" if traslado else "CFDI40186",
                f"{prefijo}.importe",
                f"El impuesto del concepto {n} ({imp.importe}) no corresponde a base por tasa (entre {inferior} y {superior}).",
            )
        if traslado and imp.impuesto == "002" and imp.tasa_o_cuota == Decimal("0.08"):
            registro = catalogo("c_CodigoPostal").obtener(rev.comp.lugar_expedicion or "")
            if registro is None or registro["estimulo_franja_fronteriza"] != "1":
                rev.advertencia(
                    "ATLAS-IVA-8",
                    f"{prefijo}.tasa_o_cuota",
                    "El IVA al 8 % es el estímulo de la región fronteriza norte y el código postal del lugar de "
                    "expedición no está marcado así en c_CodigoPostal; confírmalo con tu contador.",
                )


def _totales(rev: _Revision, ctx: Contexto) -> None:
    comp = rev.comp
    if not comp.conceptos:
        return
    resumen = resumir(comp.conceptos)
    if decimales(comp.subtotal) > 2:
        rev.problema("CFDI40107", "subtotal", "El subtotal tiene más decimales de los que admite la moneda.")
    if comp.subtotal != resumen.subtotal:
        rev.problema("CFDI40108", "subtotal", f"El subtotal ({comp.subtotal}) no es la suma de los conceptos ({resumen.subtotal}).")
    if comp.descuento != resumen.descuento:
        rev.problema("CFDI40111", "descuento", f"El descuento ({comp.descuento}) no es la suma de los descuentos de los conceptos ({resumen.descuento}).")
    if comp.descuento is not None and comp.descuento > comp.subtotal:
        rev.problema("CFDI40110", "descuento", "El descuento no puede ser mayor que el subtotal.")
    if comp.total_impuestos_trasladados != resumen.total_trasladados:
        rev.problema(
            "CFDI40205",
            "total_impuestos_trasladados",
            f"El total de impuestos trasladados ({comp.total_impuestos_trasladados}) no es la suma de los traslados ({resumen.total_trasladados}).",
        )
    if comp.total_impuestos_retenidos != resumen.total_retenidos:
        rev.problema(
            "CFDI40203",
            "total_impuestos_retenidos",
            f"El total de impuestos retenidos ({comp.total_impuestos_retenidos}) no es la suma de las retenciones ({resumen.total_retenidos}).",
        )
    esperado = redondear(
        comp.subtotal - (comp.descuento or 0) + (comp.total_impuestos_trasladados or 0) - (comp.total_impuestos_retenidos or 0)
    )
    if comp.total != esperado:
        rev.problema("CFDI40119", "total", f"El total ({comp.total}) no es subtotal − descuento + traslados − retenciones ({esperado}).")

    op = ctx.operacion
    if op is None:
        return
    base = comp.subtotal - (comp.descuento or 0)
    iva = sum((t.importe or Decimal("0") for t in resumen.traslados if t.impuesto == "002"), Decimal("0"))
    for etiqueta, factura, operacion in (
        ("el subtotal después de descuentos", base, op.subtotal),
        ("el IVA", iva, op.impuesto),
        ("el total", comp.total, op.total),
    ):
        if redondear(factura) != redondear(Decimal(operacion)):
            rev.problema(
                "ATLAS-CUADRE",
                "total",
                f"En la factura {etiqueta} es {redondear(factura)} y en la operación {redondear(Decimal(operacion))}. "
                "Vuelve a preparar la factura; los montos de la operación no se ajustan aquí.",
            )


def validar(comp: Comprobante, ctx: Contexto) -> Validacion:
    """Todas las reglas, en orden de lectura del comprobante. Determinista para el mismo ``ctx``."""
    rev = _Revision(comp, comp.fecha.date())
    if ctx.operacion_cancelada:
        rev.problema("ATLAS-ORIGEN", "origen", "La operación de origen está cancelada: no se puede facturar.")
    if comp.tipo_de_comprobante != "I":
        rev.problema("ATLAS-NO-SOPORTADO", "tipo_de_comprobante", "Por ahora sólo se preparan facturas de ingreso.")
    _fecha(rev, ctx)
    _emisor(rev)
    _receptor(rev)
    _moneda_y_pago(rev, ctx)
    _conceptos(rev)
    _totales(rev, ctx)
    # El esquema oficial al final: atrapa lo que se nos haya escapado (longitudes, patrones).
    for error in xml_sat.errores_xsd(xml_sin_sellar(comp)):
        rev.problema("ATLAS-XSD", "xml", f"El XML no pasa el esquema oficial del SAT: {error}")
    return rev.resultado
