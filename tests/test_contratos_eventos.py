"""Contrato de eventos v1 entre Atlas ONE, RRHH y Financials (docs/contracts/eventos).

Dos capas, igual que hará el receptor:
1. Forma: cada ejemplo valida contra su JSON Schema (draft 2020-12).
2. Cuadre: reglas aritméticas que un JSON Schema no puede expresar. Las
   funciones `cuadre_*` de este módulo son la implementación de referencia de
   la sección "Reglas de cuadre" del README; el endpoint receptor (no
   construido) debe dar los mismos resultados.

Los casos inválidos se arman mutando los ejemplos válidos, para que cada uno
pruebe exactamente una regla.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

RAIZ = Path(__file__).resolve().parent.parent / "docs" / "contracts" / "eventos" / "v1"
EJEMPLOS = RAIZ / "ejemplos"
CENTAVO = Decimal("0.01")
VENTANA_SEGUNDOS = 300

EVENTOS = [
    "pos.venta.registrada",
    "pos.venta.cancelada",
    "pos.devolucion.aprobada",
    "pos.abono.registrado",
    "pos.caja.cerrada",
    "pos.factura.solicitada",
    "rrhh.nomina.autorizada",
    "financials.cfdi.actualizado",
    "financials.nomina.timbrada",
]
OTROS_EJEMPLOS = {
    "acuse.aceptado.json": "acuse",
    "acuse.rechazado.json": "acuse",
    "cabeceras.json": "cabeceras",
}


# --------------------------------------------------------------------------- esquemas


def _cargar(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


def _esquemas() -> dict[str, dict]:
    return {p.name.removesuffix(".schema.json"): _cargar(p) for p in sorted(RAIZ.glob("*.schema.json"))}


ESQUEMAS = _esquemas()
REGISTRO = Registry().with_resources(
    (esquema["$id"], Resource.from_contents(esquema)) for esquema in ESQUEMAS.values()
)


def validador(nombre: str) -> Draft202012Validator:
    return Draft202012Validator(ESQUEMAS[nombre], registry=REGISTRO)


def errores_de_esquema(nombre: str, documento) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validador(nombre).iter_errors(documento)]


def ejemplo(nombre: str):
    return _cargar(EJEMPLOS / f"{nombre}.json")


# --------------------------------------------------------------------------- cuadre


def D(valor: str) -> Decimal:
    if not isinstance(valor, str):
        raise TypeError(f"Se esperaba cadena decimal, llegó {type(valor).__name__}")
    return Decimal(valor)


def r2(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def limites_impuesto(base: Decimal, tasa: Decimal) -> tuple[Decimal, Decimal]:
    """Límites del Anexo 20 para el importe de un traslado con dos decimales."""
    inferior = ((base - Decimal("0.005")) * tasa).quantize(CENTAVO, rounding=ROUND_DOWN)
    superior = ((base + Decimal("0.005") - Decimal("1e-12")) * tasa).quantize(CENTAVO, rounding=ROUND_UP)
    return inferior, superior


def _clave_impuesto(t: dict) -> tuple:
    return (t["impuesto"], t["tipo_factor"], t.get("tasa"))


def cuadre_documento(renglones: list[dict], totales: dict) -> list[str]:
    errores: list[str] = []
    numeros = [r["numero"] for r in renglones]
    if len(numeros) != len(set(numeros)):
        errores.append("renglones: número de renglón repetido")
    resumen: dict[tuple, list[Decimal]] = {}
    for r in renglones:
        n = r["numero"]
        importe, descuento = D(r["importe"]), D(r["descuento"])
        if importe != r2(D(r["cantidad"]) * D(r["valor_unitario"])):
            errores.append(f"renglón {n}: importe distinto de cantidad × valor_unitario")
        if descuento > importe:
            errores.append(f"renglón {n}: el descuento excede al importe")
        base_esperada = importe - descuento
        suma_impuestos = Decimal("0")
        vistos = set()
        for t in r["impuestos"]:
            if _clave_impuesto(t) in vistos:
                errores.append(f"renglón {n}: impuesto repetido")
            vistos.add(_clave_impuesto(t))
            base = D(t["base"])
            if base != base_esperada:
                errores.append(f"renglón {n}: la base del impuesto no es importe − descuento")
            if t["tipo_factor"] == "Tasa":
                inferior, superior = limites_impuesto(base, D(t["tasa"]))
                monto = D(t["importe"])
                if not inferior <= monto <= superior:
                    errores.append(f"renglón {n}: impuesto {monto} fuera de [{inferior}, {superior}]")
                suma_impuestos += monto
            acumulado = resumen.setdefault(_clave_impuesto(t), [Decimal("0"), Decimal("0")])
            acumulado[0] += base
            acumulado[1] += D(t.get("importe", "0.00"))
        if D(r["total"]) != importe - descuento + suma_impuestos:
            errores.append(f"renglón {n}: total distinto de importe − descuento + impuestos")

    if D(totales["subtotal"]) != sum((D(r["importe"]) for r in renglones), Decimal("0")):
        errores.append("totales: subtotal distinto de la suma de importes")
    if D(totales["descuento"]) != sum((D(r["descuento"]) for r in renglones), Decimal("0")):
        errores.append("totales: descuento distinto de la suma de descuentos")
    declarado = {}
    for t in totales["impuestos"]:
        if _clave_impuesto(t) in declarado:
            errores.append("totales: impuesto repetido en el resumen")
        declarado[_clave_impuesto(t)] = [D(t["base"]), D(t.get("importe", "0.00"))]
    if declarado != resumen:
        errores.append("totales: el resumen de impuestos no es la suma de los renglones")
    impuestos = sum((v[1] for v in declarado.values()), Decimal("0"))
    total = D(totales["total"])
    if total != D(totales["subtotal"]) - D(totales["descuento"]) + impuestos:
        errores.append("totales: total distinto de subtotal − descuento + impuestos")
    if total != sum((D(r["total"]) for r in renglones), Decimal("0")):
        errores.append("totales: total distinto de la suma de totales de renglón")
    return errores


def cuadre_sobre(evento: dict) -> list[str]:
    errores = []
    prefijo = f"{evento['emisor']}:{evento['organizacion_origen']['id']}:"
    if not evento["clave_idempotencia"].startswith(prefijo):
        errores.append("clave_idempotencia: debe empezar con emisor y organización de origen")
    instante = datetime.fromisoformat(evento["ocurrido_en"])
    if instante.utcoffset() != instante.astimezone(ZoneInfo(evento["zona_horaria"])).utcoffset():
        errores.append("ocurrido_en: el desfase no corresponde a zona_horaria en ese instante")
    return errores


def cuadre_venta_registrada(datos: dict) -> list[str]:
    errores = cuadre_documento(datos["renglones"], datos["totales"])
    cobrable = D(datos["totales"]["total"]) + D(datos["propina"]) + D(datos["recargo_tarjeta"])
    pagado = sum((D(p["importe"]) for p in datos["pagos"]), Decimal("0"))
    if pagado != cobrable - D(datos["saldo_pendiente"]):
        errores.append("pagos: no suman total + propina + recargo − saldo_pendiente")
    return errores


def cuadre_devolucion(datos: dict) -> list[str]:
    errores = cuadre_documento(datos["renglones"], datos["totales"])
    if sum((D(p["importe"]) for p in datos["reembolsos"]), Decimal("0")) != D(datos["totales"]["total"]):
        errores.append("reembolsos: no suman el total devuelto")
    return errores


def cuadre_abono(datos: dict) -> list[str]:
    errores = []
    if sum((D(a["importe"]) for a in datos["aplicaciones"]), Decimal("0")) != D(datos["pago"]["importe"]):
        errores.append("aplicaciones: no suman el importe del pago")
    for i, a in enumerate(datos["aplicaciones"]):
        if D(a["importe"]) > D(a["saldo_anterior"]):
            errores.append(f"aplicaciones.{i}: abona más que el saldo")
        if D(a["saldo_insoluto"]) != D(a["saldo_anterior"]) - D(a["importe"]):
            errores.append(f"aplicaciones.{i}: saldo_insoluto distinto de saldo_anterior − importe")
    return errores


def cuadre_caja(datos: dict) -> list[str]:
    errores = []
    metodos = [c["metodo_origen"] for c in datos["cobros_por_metodo"]]
    if len(metodos) != len(set(metodos)):
        errores.append("cobros_por_metodo: método repetido")
    if sum((D(c["importe"]) for c in datos["cobros_por_metodo"]), Decimal("0")) != D(datos["total_cobrado"]):
        errores.append("cobros_por_metodo: no suman total_cobrado")
    e = datos["efectivo"]
    efectivo = next((D(c["importe"]) for c in datos["cobros_por_metodo"] if c["metodo_origen"] == "CASH"), Decimal("0"))
    if D(e["cobros"]) != efectivo:
        errores.append("efectivo.cobros: distinto del renglón CASH")
    esperado = D(e["fondo_inicial"]) + D(e["cobros"]) + D(e["entradas"]) - D(e["salidas"]) - D(e["reembolsos"])
    if D(e["esperado"]) != esperado:
        errores.append("efectivo.esperado: distinto de fondo + cobros + entradas − salidas − reembolsos")
    if D(e["diferencia"]) != D(e["contado"]) - D(e["esperado"]):
        errores.append("efectivo.diferencia: distinta de contado − esperado")
    if datos["cerrada_en"] < datos["abierta_en"]:
        errores.append("cerrada_en: anterior a abierta_en")
    return errores


def cuadre_recibo(r: dict, fecha_final: str) -> list[str]:
    n = r["id_recibo_origen"]
    t = r["totales"]
    suma = lambda xs: sum(xs, Decimal("0"))  # noqa: E731
    gravado = suma(D(p["importe_gravado"]) for p in r["percepciones"])
    exento = suma(D(p["importe_exento"]) for p in r["percepciones"])
    isr = suma(D(d["importe"]) for d in r["deducciones"] if d["tipo_deduccion"] == "002")
    otras = suma(D(d["importe"]) for d in r["deducciones"] if d["tipo_deduccion"] != "002")
    otros_pagos = suma(D(o["importe"]) for o in r["otros_pagos"])
    errores = []
    esperado = {
        "total_gravado": gravado,
        "total_exento": exento,
        "total_percepciones": gravado + exento,
        "total_impuestos_retenidos": isr,
        "total_otras_deducciones": otras,
        "total_deducciones": isr + otras,
        "total_otros_pagos": otros_pagos,
        "neto": gravado + exento + otros_pagos - isr - otras,
    }
    for campo, valor in esperado.items():
        if D(t[campo]) != valor:
            errores.append(f"recibo {n}: {campo} declarado {t[campo]}, la suma da {valor}")
    if esperado["neto"] < 0:
        errores.append(f"recibo {n}: las deducciones superan a percepciones más otros pagos")
    if gravado + exento + otros_pagos == 0:
        errores.append(f"recibo {n}: sin percepciones ni otros pagos")
    if isr > 0 and gravado == 0:
        errores.append(f"recibo {n}: retiene ISR sobre ingresos sólo exentos")
    for o in r["otros_pagos"]:
        if o["tipo_otro_pago"] == "002" and D(o["subsidio_causado"]) < D(o["importe"]):
            errores.append(f"recibo {n}: subsidio entregado mayor que el causado")
    inicio = r["laboral"].get("fecha_inicio_rel_laboral")
    if inicio and inicio > fecha_final:
        errores.append(f"recibo {n}: relación laboral inicia después del periodo")
    return errores


def cuadre_nomina(datos: dict) -> list[str]:
    errores = []
    if not datos["fecha_inicial_pago"] <= datos["fecha_final_pago"]:
        errores.append("periodo: fecha_inicial_pago posterior a fecha_final_pago")
    ids = [r["id_recibo_origen"] for r in datos["recibos"]]
    if len(ids) != len(set(ids)):
        errores.append("recibos: id_recibo_origen repetido")
    empleados = [r["empleado"]["id_origen"] for r in datos["recibos"]]
    if len(empleados) != len(set(empleados)):
        errores.append("recibos: un empleado con dos recibos en la misma versión")
    for r in datos["recibos"]:
        errores += cuadre_recibo(r, datos["fecha_final_pago"])
    t = datos["totales"]
    suma = lambda campo: sum((D(r["totales"][campo]) for r in datos["recibos"]), Decimal("0"))  # noqa: E731
    if t["numero_recibos"] != len(datos["recibos"]):
        errores.append("totales: numero_recibos distinto de los recibos enviados")
    for campo, del_recibo in [
        ("total_percepciones", "total_percepciones"),
        ("total_deducciones", "total_deducciones"),
        ("total_otros_pagos", "total_otros_pagos"),
        ("total_neto", "neto"),
    ]:
        if D(t[campo]) != suma(del_recibo):
            errores.append(f"totales: {campo} no es la suma de los recibos")
    return errores


def cuadre_nomina_timbrada(datos: dict) -> list[str]:
    errores = []
    conteo = {e: sum(1 for r in datos["recibos"] if r["estado"] == e) for e in ("timbrado", "rechazado", "pendiente")}
    resumen = datos["resumen"]
    if (resumen["timbrados"], resumen["rechazados"], resumen["pendientes"]) != (
        conteo["timbrado"], conteo["rechazado"], conteo["pendiente"]
    ):
        errores.append("resumen: los conteos no corresponden a los recibos")
    neto = sum((D(r["neto"]) for r in datos["recibos"] if r["estado"] == "timbrado"), Decimal("0"))
    if D(resumen["total_neto_timbrado"]) != neto:
        errores.append("resumen: total_neto_timbrado no es la suma de los recibos timbrados")
    if conteo["pendiente"]:
        estado = "en_proceso"
    elif not conteo["rechazado"]:
        estado = "completa"
    elif not conteo["timbrado"]:
        estado = "rechazada"
    else:
        estado = "parcial"
    if datos["estado_corrida"] != estado:
        errores.append(f"estado_corrida: debería ser {estado}")
    return errores


CUADRE = {
    "pos.venta.registrada": cuadre_venta_registrada,
    "pos.venta.cancelada": lambda d: [],
    "pos.devolucion.aprobada": cuadre_devolucion,
    "pos.abono.registrado": cuadre_abono,
    "pos.caja.cerrada": cuadre_caja,
    "pos.factura.solicitada": lambda d: [],
    "rrhh.nomina.autorizada": cuadre_nomina,
    "financials.cfdi.actualizado": lambda d: [],
    "financials.nomina.timbrada": cuadre_nomina_timbrada,
}


def errores_de_cuadre(evento: dict) -> list[str]:
    return cuadre_sobre(evento) + CUADRE[evento["tipo"]](evento["datos"])


# --------------------------------------------------------------------------- firma


def firmar(secreto: str, marca_tiempo: str, cuerpo: bytes) -> str:
    mensaje = marca_tiempo.encode("ascii") + b"." + cuerpo
    return "sha256=" + hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


def firma_valida(secreto: str, marca_tiempo: str, cuerpo: bytes, firma: str, ahora: int) -> bool:
    if not marca_tiempo.isdigit() or abs(ahora - int(marca_tiempo)) > VENTANA_SEGUNDOS:
        return False
    return hmac.compare_digest(firmar(secreto, marca_tiempo, cuerpo), firma)


# --------------------------------------------------------------------------- pruebas: forma


def test_todo_esquema_es_draft_2020_12_valido():
    for nombre, esquema in ESQUEMAS.items():
        assert esquema["$schema"] == "https://json-schema.org/draft/2020-12/schema", nombre
        Draft202012Validator.check_schema(esquema)


def test_cada_evento_tiene_esquema_y_ejemplo():
    for tipo in EVENTOS:
        assert tipo in ESQUEMAS, f"falta {tipo}.schema.json"
        assert (EJEMPLOS / f"{tipo}.json").exists(), f"falta ejemplos/{tipo}.json"
    eventos_en_disco = {n for n in ESQUEMAS if n.split(".")[0] in {"pos", "rrhh", "financials"}}
    assert eventos_en_disco == set(EVENTOS)


def test_ningun_ejemplo_queda_huerfano():
    esperados = {f"{t}.json" for t in EVENTOS} | set(OTROS_EJEMPLOS) | {"firma.vector.json"}
    assert {p.name for p in EJEMPLOS.glob("*.json")} == esperados


@pytest.mark.parametrize("tipo", EVENTOS)
def test_ejemplo_valido_contra_su_esquema(tipo):
    evento = ejemplo(tipo)
    assert evento["tipo"] == tipo
    assert errores_de_esquema(tipo, evento) == []


@pytest.mark.parametrize("tipo", EVENTOS)
def test_ejemplo_cuadra(tipo):
    assert errores_de_cuadre(ejemplo(tipo)) == []


@pytest.mark.parametrize("archivo,esquema", sorted(OTROS_EJEMPLOS.items()))
def test_acuses_y_cabeceras_validos(archivo, esquema):
    assert errores_de_esquema(esquema, _cargar(EJEMPLOS / archivo)) == []


def test_ningun_ejemplo_usa_numeros_json_para_dinero():
    """Los únicos números permitidos son contadores enteros (numero, version, dias, horas...)."""

    def recorrer(nodo, ruta):
        if isinstance(nodo, float):
            pytest.fail(f"{ruta}: número con decimales en JSON")
        if isinstance(nodo, dict):
            for k, v in nodo.items():
                recorrer(v, f"{ruta}.{k}")
        elif isinstance(nodo, list):
            for i, v in enumerate(nodo):
                recorrer(v, f"{ruta}.{i}")

    for p in EJEMPLOS.glob("*.json"):
        recorrer(_cargar(p), p.name)


# --------------------------------------------------------------------------- pruebas: inválidos


def _set(ruta: str, valor):
    def mutar(doc):
        *camino, ultimo = ruta.split(".")
        nodo = doc
        for paso in camino:
            nodo = nodo[int(paso)] if isinstance(nodo, list) else nodo[paso]
        if isinstance(nodo, list):
            nodo[int(ultimo)] = valor
        else:
            nodo[ultimo] = valor

    return mutar


def _del(ruta: str):
    def mutar(doc):
        *camino, ultimo = ruta.split(".")
        nodo = doc
        for paso in camino:
            nodo = nodo[int(paso)] if isinstance(nodo, list) else nodo[paso]
        del nodo[ultimo]

    return mutar


def _todos(*mutaciones):
    def mutar(doc):
        for m in mutaciones:
            m(doc)

    return mutar


V = "pos.venta.registrada"
N = "rrhh.nomina.autorizada"
LAB_A = "datos.recibos.0.laboral"
LAB_B = "datos.recibos.1.laboral"

# (descripción, evento, mutación) — el esquema debe rechazarlo.
FALLAN_ESQUEMA = [
    ("monto flotante", V, _set("datos.totales.total", 173.93)),
    ("monto con un decimal", V, _set("datos.totales.total", "173.9")),
    ("monto con tres decimales", V, _set("datos.renglones.0.importe", "46.500")),
    ("monto con separador de miles", V, _set("datos.propina", "1,020.00")),
    ("tasa en porcentaje", V, _set("datos.renglones.0.impuestos.0.tasa", "16.0000")),
    ("tasa como entero", V, _set("datos.renglones.0.impuestos.0.tasa", "16")),
    ("tasa con dos decimales", V, _set("datos.renglones.0.impuestos.0.tasa", "0.16")),
    ("tasa como número", V, _set("datos.renglones.0.impuestos.0.tasa", 0.16)),
    ("tasa de IVA no admitida", V, _set("datos.renglones.0.impuestos.0.tasa", "0.1500")),
    ("cantidad flotante", V, _set("datos.renglones.1.cantidad", 1.25)),
    ("cantidad cero", V, _set("datos.renglones.1.cantidad", "0.000")),
    ("exento con tasa", V, _set("datos.renglones.1.impuestos.0.tipo_factor", "Exento")),
    ("objeto 02 sin impuestos", V, _set("datos.renglones.0.impuestos", [])),
    ("clave SAT de producto corta", V, _set("datos.renglones.0.clave_prod_serv", "502023")),
    ("hora sin zona", V, _set("ocurrido_en", "2026-11-24T13:45:10")),
    ("hora en Z", V, _set("ocurrido_en", "2026-11-24T19:45:10Z")),
    ("campo desconocido", V, _set("datos.subtotl", "162.70")),
    ("contado con saldo", V, _set("datos.saldo_pendiente", "10.00")),
    ("crédito sin cliente", V, _set("datos.condicion", "credito")),
    ("organización de Atlas ONE no entera", V, _set("organizacion_origen.id", "org-42")),
    ("emisor equivocado", V, _set("emisor", "hrflow")),
    ("organizacion_destino en evento entrante", V, _set("organizacion_destino", {"id": "1"})),
    ("clave de idempotencia sin hecho", V, _set("clave_idempotencia", "atlas-one:42:venta")),
    ("cancelación sin motivo", "pos.venta.cancelada", _del("datos.motivo")),
    ("devolución sin reembolsos", "pos.devolucion.aprobada", _set("datos.reembolsos", [])),
    ("abono sin aplicaciones", "pos.abono.registrado", _set("datos.aplicaciones", [])),
    ("caja con diferencia flotante", "pos.caja.cerrada", _set("datos.efectivo.diferencia", -5.5)),
    ("RFC en minúsculas", "pos.factura.solicitada", _set("datos.receptor.rfc", "eku9003173c9")),
    ("PPD con forma de pago distinta de 99", "pos.factura.solicitada",
     _todos(_set("datos.metodo_pago", "PPD"), _set("datos.forma_pago_sat", "01"))),
    ("nómina con monto flotante", N, _set("datos.recibos.0.percepciones.0.importe_gravado", 6000.0)),
    ("nómina sin slug de HRFlow", N, _del("organizacion_origen.slug")),
    ("registro patronal sin NSS", N, _del(f"{LAB_A}.num_seguridad_social")),
    ("asimilado con NSS", N, _set(f"{LAB_B}.num_seguridad_social", "12345678901")),
    ("contrato 01 sin registro patronal", N, _todos(
        _del(f"{LAB_A}.registro_patronal"), _del(f"{LAB_A}.num_seguridad_social"),
        _del(f"{LAB_A}.fecha_inicio_rel_laboral"), _del(f"{LAB_A}.antiguedad"),
        _del(f"{LAB_A}.riesgo_puesto"), _del(f"{LAB_A}.salario_diario_integrado"))),
    ("contrato 01 con régimen de asimilados", N, _set(f"{LAB_A}.tipo_regimen", "09")),
    ("asimilado con régimen de sueldos", N, _set(f"{LAB_B}.tipo_regimen", "02")),
    ("horas extra sin detalle", N, _set("datos.recibos.0.percepciones.1.tipo_percepcion", "019")),
    ("subsidio sin subsidio causado", N, _set("datos.recibos.0.otros_pagos", [
        {"tipo_otro_pago": "002", "clave": "O002", "concepto": "Subsidio", "importe": "10.00"}])),
    ("CLABE con banco", N, _todos(
        _set(f"{LAB_A}.cuenta_bancaria", "002180700123456789"), _set(f"{LAB_A}.banco", "002"))),
    ("NumEmpleado con el cuid completo", N, _set("datos.recibos.0.empleado.num_empleado", "cm1a2b3c40001xy7z8w9v0u1t")),
    ("ordinaria con periodicidad 99", N, _set("datos.periodicidad_pago", "99")),
    ("corrección en versión 1", N, _set("datos.alcance", "correccion")),
    ("días pagados con cuatro decimales", N, _set("datos.recibos.0.num_dias_pagados", "15.0000")),
    ("recibo sin percepciones ni otros pagos", N, _set("datos.recibos.1.percepciones", [])),
    ("CFDI timbrado sin UUID", "financials.cfdi.actualizado", _del("datos.uuid")),
    ("CFDI timbrado sin enlaces", "financials.cfdi.actualizado", _del("datos.enlaces")),
    ("CFDI rechazado sin motivo", "financials.cfdi.actualizado", _todos(
        _set("datos.estado", "rechazado"), _del("datos.uuid"), _del("datos.enlaces"))),
    ("respuesta sin causado_por", "financials.cfdi.actualizado", _del("causado_por")),
    ("respuesta sin organizacion_destino", "financials.cfdi.actualizado", _del("organizacion_destino")),
    ("recibo rechazado con UUID", "financials.nomina.timbrada",
     _set("datos.recibos.1.uuid", "4e6a8c0b-2d4f-4a1c-9b3e-5f7a9c1d3e81")),
    ("recibo timbrado sin enlaces", "financials.nomina.timbrada", _del("datos.recibos.0.enlaces")),
]

# (descripción, evento, mutación) — la forma es válida, pero no cuadra.
FALLAN_CUADRE = [
    ("total del documento un centavo arriba", V, _set("datos.totales.total", "173.94")),
    ("total de renglón redondeado", V, _set("datos.renglones.2.total", "90.00")),
    ("IVA de renglón fuera de tolerancia", V, _todos(
        _set("datos.renglones.0.impuestos.0.importe", "7.47"), _set("datos.renglones.0.total", "53.97"))),
    ("importe distinto de cantidad por precio", V, _set("datos.renglones.0.importe", "46.51")),
    ("resumen de impuestos que no suma", V, _set("datos.totales.impuestos.0.importe", "19.86")),
    ("pagos que no cubren total y propina", V, _set("datos.pagos.1.importe", "73.93")),
    ("clave de idempotencia de otra organización", V, _set(
        "clave_idempotencia", "atlas-one:43:venta:3f0c6a52-8d1e-4f7b-9a43-2b6c1e0d5a91:registrada")),
    ("desfase que no corresponde a la zona", V, _set("ocurrido_en", "2026-11-24T13:45:10-05:00")),
    ("reembolso distinto del total devuelto", "pos.devolucion.aprobada", _set("datos.reembolsos.0.importe", "45.01")),
    ("aplicaciones que no suman el abono", "pos.abono.registrado", _set("datos.aplicaciones.1.importe", "150.00")),
    ("saldo insoluto mal restado", "pos.abono.registrado", _set("datos.aplicaciones.1.saldo_insoluto", "1000.00")),
    ("diferencia de caja mal calculada", "pos.caja.cerrada", _set("datos.efectivo.diferencia", "5.50")),
    ("cobros de caja que no suman", "pos.caja.cerrada", _set("datos.total_cobrado", "9200.00")),
    ("neto del recibo descuadrado", N, _set("datos.recibos.0.totales.neto", "5684.26")),
    ("ISR fuera de total_impuestos_retenidos", N, _set("datos.recibos.0.totales.total_impuestos_retenidos", "0.00")),
    ("total de la corrida descuadrado", N, _set("datos.totales.total_neto", "12637.66")),
    ("número de recibos equivocado", N, _set("datos.totales.numero_recibos", 3)),
    ("resumen de timbrado que no cuenta bien", "financials.nomina.timbrada", _set("datos.resumen.rechazados", 0)),
    ("estado de corrida inconsistente", "financials.nomina.timbrada", _set("datos.estado_corrida", "completa")),
]


@pytest.mark.parametrize("descripcion,tipo,mutar", FALLAN_ESQUEMA, ids=[c[0] for c in FALLAN_ESQUEMA])
def test_esquema_rechaza(descripcion, tipo, mutar):
    evento = copy.deepcopy(ejemplo(tipo))
    mutar(evento)
    assert errores_de_esquema(tipo, evento), f"el esquema aceptó: {descripcion}"


@pytest.mark.parametrize("descripcion,tipo,mutar", FALLAN_CUADRE, ids=[c[0] for c in FALLAN_CUADRE])
def test_cuadre_rechaza(descripcion, tipo, mutar):
    evento = copy.deepcopy(ejemplo(tipo))
    mutar(evento)
    # La forma sigue siendo válida: este error sólo lo detecta la regla de cuadre.
    assert errores_de_esquema(tipo, evento) == []
    assert errores_de_cuadre(evento), f"el cuadre aceptó: {descripcion}"


def test_acuse_rechazado_exige_errores_y_detalle():
    acuse = _cargar(EJEMPLOS / "acuse.rechazado.json")
    del acuse["errores"]
    assert errores_de_esquema("acuse", acuse)


def test_tolerancia_de_impuesto_del_anexo_20():
    # 124.08 × 0.16 = 19.8528: sólo 19.85 cabe con dos decimales.
    assert limites_impuesto(Decimal("124.08"), Decimal("0.1600")) == (Decimal("19.85"), Decimal("19.86"))
    inferior, superior = limites_impuesto(Decimal("77.58"), Decimal("0.1600"))
    assert inferior <= Decimal("12.41") <= superior
    assert not inferior <= Decimal("12.43") <= superior
    # 46.50 × 0.16 = 7.44; el Anexo 20 admite 7.43 a 7.45, no 7.47.
    evento = copy.deepcopy(ejemplo(V))
    _todos(_set("datos.renglones.0.impuestos.0.importe", "7.47"), _set("datos.renglones.0.total", "53.97"))(evento)
    assert any("fuera de [7.43, 7.45]" in e for e in errores_de_cuadre(evento))


# --------------------------------------------------------------------------- pruebas: firma


def test_vector_de_firma():
    vector = _cargar(EJEMPLOS / "firma.vector.json")
    cuerpo = vector["cuerpo"].encode("utf-8")
    assert vector["cadena_firmada"] == f"{vector['marca_tiempo']}.{vector['cuerpo']}"
    assert firmar(vector["secreto"], vector["marca_tiempo"], cuerpo) == vector["firma"]
    ahora = int(vector["marca_tiempo"])
    assert firma_valida(vector["secreto"], vector["marca_tiempo"], cuerpo, vector["firma"], ahora)


def test_firma_rechaza_cuerpo_alterado_secreto_ajeno_y_marca_cambiada():
    vector = _cargar(EJEMPLOS / "firma.vector.json")
    ts, firma = vector["marca_tiempo"], vector["firma"]
    cuerpo = vector["cuerpo"].encode("utf-8")
    ahora = int(ts)
    assert not firma_valida(vector["secreto"], ts, cuerpo.replace(b"cancelada", b"registrada"), firma, ahora)
    assert not firma_valida("otro-secreto", ts, cuerpo, firma, ahora)
    # Mover la marca de tiempo invalida la firma: por eso se firma junto con el cuerpo.
    assert not firma_valida(vector["secreto"], str(ahora + 60), cuerpo, firma, ahora + 60)


def test_ventana_de_tiempo():
    vector = _cargar(EJEMPLOS / "firma.vector.json")
    ts, firma = vector["marca_tiempo"], vector["firma"]
    cuerpo = vector["cuerpo"].encode("utf-8")
    assert firma_valida(vector["secreto"], ts, cuerpo, firma, int(ts) + VENTANA_SEGUNDOS)
    assert firma_valida(vector["secreto"], ts, cuerpo, firma, int(ts) - VENTANA_SEGUNDOS)
    assert not firma_valida(vector["secreto"], ts, cuerpo, firma, int(ts) + VENTANA_SEGUNDOS + 1)


def test_cabeceras_de_ejemplo_corresponden_al_vector():
    cabeceras = _cargar(EJEMPLOS / "cabeceras.json")
    vector = _cargar(EJEMPLOS / "firma.vector.json")
    assert cabeceras["X-Atlas-Timestamp"] == vector["marca_tiempo"]
    assert cabeceras["X-Atlas-Signature"] == vector["firma"]
    assert cabeceras["X-Atlas-Event-Id"] == json.loads(vector["cuerpo"])["id_evento"]
