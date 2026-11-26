"""Representación impresa (PDF) de un CFDI 4.0, armada desde el XML.

El XML es la fuente de verdad: el PDF se lee de él y no de las filas de la
base, así que sirve igual para un borrador, un XML sellado o uno timbrado, y
lo impreso siempre coincide con lo que recibió el SAT.

- Timbrado (trae ``tfd:TimbreFiscalDigital``): UUID, fecha de timbrado,
  certificados, sellos, cadena original del complemento de certificación y el
  código QR de verificación del SAT.
- Sin timbre: marca grande "Sin validez fiscal" y sin QR.

Las descripciones salen de los catálogos del SAT (``catalogos/``), por ejemplo
"601 - General de Ley Personas Morales". Los montos se manejan con ``Decimal``
de punta a punta; nunca ``float``.

Fuente: Helvetica de las 14 estándar de PDF (no hay Inter vendorizada; agregar
un TTF aquí es el siguiente paso si se quiere la tipografía de marca). Sólo peso
regular: la jerarquía sale del tamaño y del color, no de negritas.
"""

from __future__ import annotations

import html
import io
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from lxml import etree
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.cfdi.catalogos import catalogo

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS = {"cfdi": NS_CFDI, "tfd": NS_TFD}

URL_VERIFICACION = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"

LEYENDA_BORRADOR = "Sin validez fiscal · borrador"
LEYENDA_SIN_TIMBRE = "Sin validez fiscal · sin timbrar"
LEYENDA_CANCELADO = "Cancelado"


class CfdiIlegible(ValueError):
    """El XML no es un CFDI 4.0 que se pueda imprimir."""


# ---------------------------------------------------------------- lectura del XML


@dataclass(frozen=True)
class ImpuestoImpreso:
    tipo: str  # "Traslado" o "Retención"
    impuesto: str
    tipo_factor: str | None
    tasa_o_cuota: str | None
    base: str | None
    importe: str | None


@dataclass(frozen=True)
class ConceptoImpreso:
    clave_prod_serv: str
    no_identificacion: str | None
    cantidad: str
    clave_unidad: str
    unidad: str | None
    descripcion: str
    valor_unitario: str
    importe: str
    descuento: str | None
    objeto_imp: str
    impuestos: tuple[ImpuestoImpreso, ...] = ()


@dataclass(frozen=True)
class Timbre:
    uuid: str
    fecha_timbrado: str
    rfc_prov_certif: str
    sello_cfd: str
    no_certificado_sat: str
    sello_sat: str
    version: str = "1.1"
    leyenda: str | None = None


@dataclass(frozen=True)
class DatosCfdi:
    version: str
    serie: str | None
    folio: str | None
    fecha: str
    lugar_expedicion: str
    tipo_de_comprobante: str
    exportacion: str
    moneda: str
    tipo_cambio: str | None
    subtotal: str
    descuento: str | None
    total: str
    forma_pago: str | None
    metodo_pago: str | None
    condiciones_de_pago: str | None
    sello: str
    no_certificado: str
    emisor_rfc: str
    emisor_nombre: str
    emisor_regimen: str
    receptor_rfc: str
    receptor_nombre: str
    receptor_cp: str
    receptor_regimen: str
    receptor_uso: str
    conceptos: tuple[ConceptoImpreso, ...]
    total_trasladados: str | None
    total_retenidos: str | None
    traslados: tuple[ImpuestoImpreso, ...] = ()
    retenciones: tuple[ImpuestoImpreso, ...] = ()
    relacionados: tuple[tuple[str, str], ...] = ()  # (tipo de relación, UUID)
    timbre: Timbre | None = None

    @property
    def timbrado(self) -> bool:
        return self.timbre is not None

    @property
    def sellado(self) -> bool:
        return bool(self.sello)

    @property
    def serie_folio(self) -> str:
        return "-".join(p for p in (self.serie, self.folio) if p) or "SIN-FOLIO"


def _parser() -> etree.XMLParser:
    # Sin entidades externas ni red: el XML puede venir de fuera (proveedor de timbrado).
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=False)


def _impuestos(nodo: etree._Element | None, *, resumen: bool) -> tuple[list[ImpuestoImpreso], list[ImpuestoImpreso]]:
    traslados: list[ImpuestoImpreso] = []
    retenciones: list[ImpuestoImpreso] = []
    if nodo is None:
        return traslados, retenciones
    for t in nodo.findall("cfdi:Traslados/cfdi:Traslado", NS):
        traslados.append(
            ImpuestoImpreso(
                "Traslado", t.get("Impuesto", ""), t.get("TipoFactor"), t.get("TasaOCuota"), t.get("Base"), t.get("Importe")
            )
        )
    for r in nodo.findall("cfdi:Retenciones/cfdi:Retencion", NS):
        retenciones.append(
            ImpuestoImpreso(
                "Retención",
                r.get("Impuesto", ""),
                None if resumen else r.get("TipoFactor"),
                None if resumen else r.get("TasaOCuota"),
                None if resumen else r.get("Base"),
                r.get("Importe"),
            )
        )
    return traslados, retenciones


def leer_cfdi(xml: bytes) -> DatosCfdi:
    """Lee del XML lo que necesita la representación impresa."""
    try:
        raiz = etree.fromstring(xml, _parser())
    except etree.XMLSyntaxError as exc:
        raise CfdiIlegible("El XML de la factura no se puede leer.") from exc
    if raiz.tag != f"{{{NS_CFDI}}}Comprobante" or raiz.get("Version") != "4.0":
        raise CfdiIlegible("El XML no es un CFDI 4.0.")
    emisor = raiz.find("cfdi:Emisor", NS)
    receptor = raiz.find("cfdi:Receptor", NS)
    if emisor is None or receptor is None:
        raise CfdiIlegible("Al XML le falta el emisor o el receptor.")

    conceptos = []
    for c in raiz.findall("cfdi:Conceptos/cfdi:Concepto", NS):
        tras, ret = _impuestos(c.find("cfdi:Impuestos", NS), resumen=False)
        conceptos.append(
            ConceptoImpreso(
                clave_prod_serv=c.get("ClaveProdServ", ""),
                no_identificacion=c.get("NoIdentificacion"),
                cantidad=c.get("Cantidad", ""),
                clave_unidad=c.get("ClaveUnidad", ""),
                unidad=c.get("Unidad"),
                descripcion=c.get("Descripcion", ""),
                valor_unitario=c.get("ValorUnitario", ""),
                importe=c.get("Importe", ""),
                descuento=c.get("Descuento"),
                objeto_imp=c.get("ObjetoImp", ""),
                impuestos=tuple(tras + ret),
            )
        )

    nodo_imp = raiz.find("cfdi:Impuestos", NS)
    traslados, retenciones = _impuestos(nodo_imp, resumen=True)

    relacionados = tuple(
        (grupo.get("TipoRelacion", ""), rel.get("UUID", ""))
        for grupo in raiz.findall("cfdi:CfdiRelacionados", NS)
        for rel in grupo.findall("cfdi:CfdiRelacionado", NS)
    )

    timbre = None
    tfd = raiz.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    if tfd is not None:
        timbre = Timbre(
            uuid=tfd.get("UUID", ""),
            fecha_timbrado=tfd.get("FechaTimbrado", ""),
            rfc_prov_certif=tfd.get("RfcProvCertif", ""),
            sello_cfd=tfd.get("SelloCFD", ""),
            no_certificado_sat=tfd.get("NoCertificadoSAT", ""),
            sello_sat=tfd.get("SelloSAT", ""),
            version=tfd.get("Version", "1.1"),
            leyenda=tfd.get("Leyenda"),
        )

    return DatosCfdi(
        version=raiz.get("Version", ""),
        serie=raiz.get("Serie"),
        folio=raiz.get("Folio"),
        fecha=raiz.get("Fecha", ""),
        lugar_expedicion=raiz.get("LugarExpedicion", ""),
        tipo_de_comprobante=raiz.get("TipoDeComprobante", ""),
        exportacion=raiz.get("Exportacion", ""),
        moneda=raiz.get("Moneda", ""),
        tipo_cambio=raiz.get("TipoCambio"),
        subtotal=raiz.get("SubTotal", "0"),
        descuento=raiz.get("Descuento"),
        total=raiz.get("Total", "0"),
        forma_pago=raiz.get("FormaPago"),
        metodo_pago=raiz.get("MetodoPago"),
        condiciones_de_pago=raiz.get("CondicionesDePago"),
        sello=raiz.get("Sello", ""),
        no_certificado=raiz.get("NoCertificado", ""),
        emisor_rfc=emisor.get("Rfc", ""),
        emisor_nombre=emisor.get("Nombre", ""),
        emisor_regimen=emisor.get("RegimenFiscal", ""),
        receptor_rfc=receptor.get("Rfc", ""),
        receptor_nombre=receptor.get("Nombre", ""),
        receptor_cp=receptor.get("DomicilioFiscalReceptor", ""),
        receptor_regimen=receptor.get("RegimenFiscalReceptor", ""),
        receptor_uso=receptor.get("UsoCFDI", ""),
        conceptos=tuple(conceptos),
        total_trasladados=None if nodo_imp is None else nodo_imp.get("TotalImpuestosTrasladados"),
        total_retenidos=None if nodo_imp is None else nodo_imp.get("TotalImpuestosRetenidos"),
        traslados=tuple(traslados),
        retenciones=tuple(retenciones),
        relacionados=relacionados,
        timbre=timbre,
    )


# ---------------------------------------------------------------- total con letra

_UNIDADES = (
    "", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
    "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE",
    "VEINTE", "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS",
    "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE",
)  # fmt: skip
_DECENAS = ("", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA")
_CENTENAS = (
    "", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
    "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS",
)  # fmt: skip
# (valor, singular, plural) de mayor a menor; "mil millones" sale solo de la recursión.
_ESCALAS = ((10**12, "UN BILLÓN", "BILLONES"), (10**6, "UN MILLÓN", "MILLONES"))


def _apocope(texto: str) -> str:
    """'UNO' → 'UN' y 'VEINTIUNO' → 'VEINTIÚN' delante de un sustantivo (mil, millones, pesos)."""
    if texto.endswith("VEINTIUNO"):
        return texto[: -len("VEINTIUNO")] + "VEINTIÚN"
    if texto.endswith("UNO"):
        return texto[:-1]
    return texto


def _menor_a_mil(n: int) -> str:
    if n == 100:
        return "CIEN"
    centenas, resto = divmod(n, 100)
    partes = [_CENTENAS[centenas]] if centenas else []
    if resto < 30:
        if resto:
            partes.append(_UNIDADES[resto])
    else:
        decenas, unidades = divmod(resto, 10)
        partes.append(_DECENAS[decenas] + (f" Y {_UNIDADES[unidades]}" if unidades else ""))
    return " ".join(partes)


def _menor_a_millon(n: int) -> str:
    miles, resto = divmod(n, 1000)
    partes = []
    if miles == 1:
        partes.append("MIL")
    elif miles:
        partes.append(f"{_apocope(_menor_a_mil(miles))} MIL")
    if resto:
        partes.append(_menor_a_mil(resto))
    return " ".join(partes)


def numero_a_letras(n: int) -> str:
    """Entero no negativo en palabras (mayúsculas, con acentos). Sin apócope final."""
    if n < 0:
        raise ValueError("Sólo cantidades no negativas.")
    if n == 0:
        return "CERO"
    for valor, singular, plural in _ESCALAS:
        if n >= valor:
            cuantos, resto = divmod(n, valor)
            cabeza = singular if cuantos == 1 else f"{_apocope(numero_a_letras(cuantos))} {plural}"
            return cabeza if not resto else f"{cabeza} {numero_a_letras(resto)}"
    return _menor_a_millon(n)


def total_con_letra(total: Decimal | str, moneda: str = "MXN") -> str:
    """'MIL CIENTO SESENTA PESOS 00/100 M.N.' — el importe del CFDI con letra.

    En pesos: singular con 1 ("UN PESO"), "DE PESOS" tras millones exactos y
    centavos como fracción "NN/100 M.N.". En otra moneda: nombre del catálogo
    c_Moneda y su código en lugar de "M.N.".
    """
    try:
        valor = Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Importe no válido: {total!r}") from exc
    if valor < 0:
        raise ValueError("El total no puede ser negativo.")
    enteros = int(valor)
    centavos = int((valor - enteros) * 100)
    palabras = _apocope(numero_a_letras(enteros))
    exacto_en_millones = enteros >= 10**6 and enteros % 10**6 == 0
    if moneda == "MXN":
        nombre = "PESO" if enteros == 1 else "PESOS"
        sufijo = "M.N."
    else:
        registro = catalogo("c_Moneda").obtener(moneda)
        nombre = (registro.descripcion if registro and registro.descripcion else moneda).upper()
        sufijo = moneda
    de = "DE " if exacto_en_millones else ""
    return f"{palabras} {de}{nombre} {centavos:02d}/100 {sufijo}"


# ---------------------------------------------------------------- QR de verificación


def formato_total_qr(total: Decimal | str) -> str:
    """``tt`` del QR (Anexo 20, CFDI 3.3 y 4.0): hasta 18 enteros y 6 decimales,
    sin ceros no significativos y con al menos un decimal: 1160 → '1160.0',
    1160.50 → '1160.5', 0.123456 → '0.123456'. Igual que ``phpcfdi/cfdi-expresiones``.
    """
    valor = Decimal(str(total)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    texto = f"{valor:f}".rstrip("0")
    if texto.endswith("."):
        texto += "0"
    enteros = texto.split(".")[0].lstrip("-")
    if len(enteros) > 18:
        raise ValueError("El total excede 18 enteros.")
    return texto


def url_verificacion(uuid: str, rfc_emisor: str, rfc_receptor: str, total: Decimal | str, sello: str) -> str:
    """URL del QR del SAT. Los RFC con '&' van como '&amp;' (entidad XML), como pide
    el Anexo 20; ``fe`` son los últimos 8 caracteres del sello del emisor, sin codificar."""
    return (
        f"{URL_VERIFICACION}?id={uuid}"
        f"&re={html.escape(rfc_emisor, quote=False)}"
        f"&rr={html.escape(rfc_receptor, quote=False)}"
        f"&tt={formato_total_qr(total)}"
        f"&fe={sello[-8:]}"
    )


def cadena_original_tfd(timbre: Timbre) -> str:
    """Cadena original del complemento de certificación digital del SAT (TFD 1.1):
    ``||Version|UUID|FechaTimbrado|RfcProvCertif|[Leyenda|]SelloCFD|NoCertificadoSAT||``,
    con los espacios normalizados como la XSLT ``cadenaoriginal_TFD_1_1``."""
    partes = [timbre.version, timbre.uuid, timbre.fecha_timbrado, timbre.rfc_prov_certif]
    if timbre.leyenda:
        partes.append(timbre.leyenda)
    partes += [timbre.sello_cfd, timbre.no_certificado_sat]
    return "||" + "|".join(" ".join(p.split()) for p in partes) + "||"


# ---------------------------------------------------------------- formato


def _clave(nombre_catalogo: str, clave: str | None) -> str:
    """'601 - General de Ley Personas Morales'; la clave sola si no está en el catálogo."""
    if not clave:
        return "—"
    registro = catalogo(nombre_catalogo).obtener(clave)
    descripcion = (registro.descripcion or "").rstrip(".") if registro else ""
    return f"{clave} - {descripcion}" if descripcion else clave


def _unidad(clave: str, unidad: str | None) -> str:
    registro = catalogo("c_ClaveUnidad").obtener(clave)
    nombre = unidad or (registro.get("nombre") if registro else None)
    return f"{clave} - {nombre}" if nombre else clave


def _dinero(valor: str | None) -> str:
    if valor is None or valor == "":
        return "—"
    try:
        d = Decimal(valor)
    except InvalidOperation:
        return valor
    lugares = max(2, -d.as_tuple().exponent) if isinstance(d.as_tuple().exponent, int) else 2
    return f"{d:,.{lugares}f}"


def _tasa(t: ImpuestoImpreso) -> str:
    if t.tipo_factor == "Exento":
        return "Exento"
    if t.tasa_o_cuota is None:
        return t.tipo_factor or ""
    if t.tipo_factor == "Tasa":
        porcentaje = (Decimal(t.tasa_o_cuota) * 100).normalize()
        return f"{porcentaje:f} %"
    return f"Cuota {t.tasa_o_cuota}"


def _nombre_impuesto(clave: str) -> str:
    registro = catalogo("c_Impuesto").obtener(clave)
    return registro.descripcion if registro and registro.descripcion else clave


# ---------------------------------------------------------------- render

TINTA = colors.HexColor("#1b1d2b")
TENUE = colors.HexColor("#5f6273")
LINEA = colors.HexColor("#d9dae2")
FONDO = colors.HexColor("#f4f4f7")
ACENTO = colors.HexColor("#b53a09")  # ember para texto (5:1 sobre claro)
MARCA = colors.Color(0.71, 0.23, 0.04, alpha=0.13)

FUENTE = "Helvetica"
MONO = "Courier"


def _estilos() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=FUENTE, fontSize=8, leading=10.5, textColor=TINTA)
    return {
        "base": base,
        "chico": ParagraphStyle("chico", parent=base, fontSize=7, leading=9),
        "etiqueta": ParagraphStyle("etiqueta", parent=base, fontSize=6.5, leading=8.5, textColor=TENUE),
        "etiqueta_der": ParagraphStyle(
            "etiqueta_der", parent=base, fontSize=6.5, leading=8.5, textColor=TENUE, alignment=TA_RIGHT
        ),
        "titulo": ParagraphStyle("titulo", parent=base, fontSize=14, leading=17),
        "seccion": ParagraphStyle("seccion", parent=base, fontSize=7, leading=9, textColor=ACENTO, spaceAfter=2),
        "derecha": ParagraphStyle("derecha", parent=base, alignment=TA_RIGHT),
        "total": ParagraphStyle("total", parent=base, fontSize=12, leading=15, alignment=TA_RIGHT),
        "mono": ParagraphStyle(
            "mono", parent=base, fontName=MONO, fontSize=5.6, leading=7, textColor=TINTA, wordWrap="CJK"
        ),
        "folio": ParagraphStyle("folio", parent=base, fontSize=12, leading=15, alignment=TA_RIGHT, textColor=ACENTO),
    }


def _p(texto: str | None, estilo: ParagraphStyle) -> Paragraph:
    return Paragraph(html.escape(texto or "—"), estilo)


def _campo(etiqueta: str, valor: str | None, e: dict) -> list:
    return [_p(etiqueta.upper(), e["etiqueta"]), _p(valor, e["base"])]


def _panel(filas: list, anchos: list[float], *, fondo: bool = False) -> Table:
    tabla = Table(filas, colWidths=anchos)
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
    ]
    if fondo:
        estilo.append(("BACKGROUND", (0, 0), (-1, -1), FONDO))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def _qr(url: str, lado: float) -> Drawing:
    widget = QrCodeWidget(url, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    ancho, alto = x1 - x0, y1 - y0
    dibujo = Drawing(lado, lado, transform=[lado / ancho, 0, 0, lado / alto, 0, 0])
    dibujo.add(widget)
    return dibujo


def _leyenda(datos: DatosCfdi, cancelado: bool) -> str | None:
    if cancelado:
        return LEYENDA_CANCELADO
    if datos.timbrado:
        return None
    return LEYENDA_SIN_TIMBRE if datos.sellado else LEYENDA_BORRADOR


def render_pdf(xml: bytes, *, cancelado: bool = False) -> bytes:
    """PDF de la representación impresa del CFDI contenido en ``xml``."""
    datos = leer_cfdi(xml)
    e = _estilos()
    buffer = io.BytesIO()
    margen = 14 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=margen,
        rightMargin=margen,
        topMargin=margen,
        bottomMargin=16 * mm,
        title=f"CFDI {datos.serie_folio}",
        author=datos.emisor_nombre,
        subject="Representación impresa de un CFDI 4.0",
        creator="Atlas ONE Financials",
    )
    ancho = doc.width
    leyenda = _leyenda(datos, cancelado)
    historia: list = []

    # Aviso arriba, además de la marca de agua: que no pase por factura válida.
    if leyenda:
        aviso = Table(
            [[_p(leyenda.upper() + ("" if cancelado else " · no es un comprobante fiscal"), e["base"])]],
            colWidths=[ancho],
        )
        aviso.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.8, ACENTO),
                    ("TEXTCOLOR", (0, 0), (-1, -1), ACENTO),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        historia += [aviso, Spacer(1, 4 * mm)]

    # Encabezado: emisor a la izquierda, comprobante a la derecha.
    izquierda = [
        _p(datos.emisor_nombre, e["titulo"]),
        Spacer(1, 1.5 * mm),
        _p(f"RFC {datos.emisor_rfc}", e["base"]),
        _p(f"Régimen fiscal: {_clave('c_RegimenFiscal', datos.emisor_regimen)}", e["base"]),
    ]
    tipo = _clave("c_TipoDeComprobante", datos.tipo_de_comprobante)
    derecha = Table(
        [
            [_p(f"Factura · CFDI {datos.version}", e["etiqueta_der"])],
            [_p(datos.serie_folio, e["folio"])],
            [_p(f"Tipo: {tipo}", e["derecha"])],
            [_p(f"Fecha de emisión: {datos.fecha}", e["derecha"])],
            [_p(f"Lugar de expedición: {datos.lugar_expedicion}", e["derecha"])],
            [_p(f"Exportación: {_clave('c_Exportacion', datos.exportacion)}", e["derecha"])],
        ],
        colWidths=[ancho * 0.42],
    )
    derecha.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 0.5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    cabeza = Table([[izquierda, derecha]], colWidths=[ancho * 0.58, ancho * 0.42])
    cabeza.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    historia += [cabeza, Spacer(1, 5 * mm)]

    # Receptor.
    mitad = ancho / 2
    receptor = _panel(
        [
            [_p("RECEPTOR", e["seccion"]), ""],
            [_campo("Nombre o razón social", datos.receptor_nombre, e), _campo("RFC", datos.receptor_rfc, e)],
            [
                _campo("Régimen fiscal", _clave("c_RegimenFiscal", datos.receptor_regimen), e),
                _campo("Código postal del domicilio fiscal", datos.receptor_cp, e),
            ],
            [_campo("Uso del CFDI", _clave("c_UsoCFDI", datos.receptor_uso), e), ""],
        ],
        [mitad, mitad],
    )
    historia += [receptor, Spacer(1, 4 * mm)]

    if datos.relacionados:
        filas = [[_p("CFDI RELACIONADOS", e["seccion"]), ""]] + [
            [_p(_clave("c_TipoRelacion", tipo_rel), e["base"]), _p(uuid, e["base"])]
            for tipo_rel, uuid in datos.relacionados
        ]
        historia += [_panel(filas, [mitad, mitad]), Spacer(1, 4 * mm)]

    # Conceptos.
    anchos = [ancho * f for f in (0.11, 0.08, 0.13, 0.35, 0.12, 0.12, 0.09)]
    encabezado = [
        _p(t, e["etiqueta_der" if t in ("Cantidad", "Valor unitario", "Importe") else "etiqueta"])
        for t in ("Clave prod./serv.", "Cantidad", "Clave unidad", "Descripción", "Valor unitario", "Importe", "Obj. imp.")
    ]
    filas = [encabezado]
    for c in datos.conceptos:
        descripcion = [_p(c.descripcion, e["base"])]
        if c.no_identificacion:
            descripcion.append(_p(f"No. identificación: {c.no_identificacion}", e["chico"]))
        if c.descuento:
            descripcion.append(_p(f"Descuento: {_dinero(c.descuento)}", e["chico"]))
        for imp in c.impuestos:
            texto = f"{imp.tipo} {_nombre_impuesto(imp.impuesto)} {_tasa(imp)} · Base {_dinero(imp.base)}"
            if imp.importe is not None:
                texto += f" · Importe {_dinero(imp.importe)}"
            descripcion.append(_p(texto, e["chico"]))
        filas.append(
            [
                _p(c.clave_prod_serv, e["base"]),
                _p(c.cantidad, e["derecha"]),
                _p(_unidad(c.clave_unidad, c.unidad), e["chico"]),
                descripcion,
                _p(_dinero(c.valor_unitario), e["derecha"]),
                _p(_dinero(c.importe), e["derecha"]),
                _p(c.objeto_imp, e["base"]),
            ]
        )
    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, TINTA),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    historia += [tabla, Spacer(1, 4 * mm)]

    # Totales a la derecha; pago y total con letra a la izquierda.
    renglones = [("Subtotal", _dinero(datos.subtotal))]
    if datos.descuento:
        renglones.append(("Descuento", _dinero(datos.descuento)))
    for t in datos.traslados:
        renglones.append((f"{_nombre_impuesto(t.impuesto)} trasladado {_tasa(t)}", _dinero(t.importe)))
    for r in datos.retenciones:
        renglones.append((f"{_nombre_impuesto(r.impuesto)} retenido", _dinero(r.importe)))
    totales = [[_p(k, e["base"]), _p(v, e["derecha"])] for k, v in renglones]
    totales.append([_p("Total", e["base"]), _p(f"{_dinero(datos.total)} {datos.moneda}", e["total"])])
    tabla_totales = Table(totales, colWidths=[ancho * 0.22, ancho * 0.18])
    tabla_totales.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, TINTA),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    moneda = _clave("c_Moneda", datos.moneda)
    if datos.tipo_cambio:
        moneda += f" · tipo de cambio {datos.tipo_cambio}"
    pago = [
        _p("IMPORTE CON LETRA", e["etiqueta"]),
        _p(total_con_letra(datos.total, datos.moneda), e["base"]),
        Spacer(1, 2 * mm),
        *_campo("Moneda", moneda, e),
        *_campo("Forma de pago", _clave("c_FormaPago", datos.forma_pago), e),
        *_campo("Método de pago", _clave("c_MetodoPago", datos.metodo_pago), e),
    ]
    if datos.condiciones_de_pago:
        pago += _campo("Condiciones de pago", datos.condiciones_de_pago, e)
    pie = Table([[pago, tabla_totales]], colWidths=[ancho * 0.6, ancho * 0.4])
    pie.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 0)]))
    historia += [KeepTogether(pie), Spacer(1, 5 * mm)]

    # Timbre fiscal digital.
    if datos.timbre:
        t = datos.timbre
        url = url_verificacion(t.uuid, datos.emisor_rfc, datos.receptor_rfc, datos.total, datos.sello)
        lado = 32 * mm  # el SAT pide al menos 2.75 cm por lado
        detalle = Table(
            [
                [_campo("Folio fiscal (UUID)", t.uuid, e), _campo("Fecha y hora de certificación", t.fecha_timbrado, e)],
                [
                    _campo("No. de certificado del SAT", t.no_certificado_sat, e),
                    _campo("No. de certificado del emisor", datos.no_certificado, e),
                ],
                [_campo("RFC del proveedor de certificación", t.rfc_prov_certif, e), ""],
            ],
            colWidths=[(ancho - lado - 4 * mm) / 2] * 2,
        )
        detalle.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        bloque = Table([[_qr(url, lado), detalle]], colWidths=[lado + 4 * mm, ancho - lado - 4 * mm])
        bloque.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        sellos = [
            _p("SELLO DIGITAL DEL CFDI", e["etiqueta"]),
            _p(datos.sello, e["mono"]),
            Spacer(1, 1.5 * mm),
            _p("SELLO DIGITAL DEL SAT", e["etiqueta"]),
            _p(t.sello_sat, e["mono"]),
            Spacer(1, 1.5 * mm),
            _p("CADENA ORIGINAL DEL COMPLEMENTO DE CERTIFICACIÓN DIGITAL DEL SAT", e["etiqueta"]),
            _p(cadena_original_tfd(t), e["mono"]),
        ]
        historia += [
            KeepTogether([_p("TIMBRE FISCAL DIGITAL", e["seccion"]), bloque]),
            Spacer(1, 3 * mm),
            *sellos,
        ]

    def _pagina(canvas, documento):
        canvas.saveState()
        if leyenda:
            canvas.setFillColor(MARCA)
            canvas.setFont(FUENTE, 58)
            canvas.translate(letter[0] / 2, letter[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 18, "SIN VALIDEZ FISCAL" if not cancelado else "CANCELADO")
            if not cancelado:
                canvas.setFont(FUENTE, 34)
                canvas.drawCentredString(0, -30, leyenda.split("·")[-1].strip().upper())
            canvas.restoreState()
            canvas.saveState()
        canvas.setFont(FUENTE, 6.5)
        canvas.setFillColor(TENUE)
        texto = (
            "Este documento es una representación impresa de un CFDI 4.0."
            if datos.timbrado
            else "Representación de un CFDI 4.0 sin timbre fiscal: no ampara operación alguna ante el SAT."
        )
        canvas.drawString(margen, 9 * mm, texto)
        canvas.drawRightString(letter[0] - margen, 9 * mm, f"{datos.serie_folio} · página {documento.page}")
        canvas.restoreState()

    doc.build(historia, onFirstPage=_pagina, onLaterPages=_pagina)
    return buffer.getvalue()

