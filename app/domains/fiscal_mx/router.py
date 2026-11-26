"""Localización MX: catálogos para captura y facturas (CFDI 4.0).

``/xml`` descarga un borrador sin sello y sin validez fiscal. Sellar, timbrar
y cancelar (al final del archivo) dependen del servicio de llaves (ADR-017) y
del proveedor (ADR-018), y responden 503 mientras ``CFDI_TIMBRADO_HABILITADO``
esté apagado.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.fiscal_mx import documentos as docs
from app.domains.fiscal_mx.schemas import ArmadoIn, DocumentoCreate, DocumentoRead, SatOption, ValidacionRead
from app.models.organization import WRITE_ROLES
from app.models.user import User
from app.security.deps import get_current_org_id, get_current_user, require_role
from app.services.cfdi import datos_fiscales as df
from app.services.cfdi.armado import Renglon

router = APIRouter(prefix="/fiscal-mx", tags=["fiscal-mx"])


@router.get("/catalogs/{nombre}")
def list_catalog(
    nombre: str,
    persona: Literal["fisica", "moral"] | None = Query(default=None),
    regimen: str | None = Query(default=None, max_length=3),
    rfc: str | None = Query(default=None, max_length=20),
    _org_id: str = Depends(get_current_org_id),
):
    """Claves vigentes hoy. ``rfc`` deduce el tipo de persona; ``regimen`` filtra los usos de CFDI."""
    if nombre not in df.CATALOGOS_PARA_CAPTURA:
        raise HTTPException(status_code=404, detail="Ese catálogo no está disponible para captura.")
    persona_moral = None if persona is None else persona == "moral"
    if persona_moral is None and rfc:
        persona_moral = df.persona_de_rfc(rfc)
    items = [SatOption(**fila) for fila in df.opciones(nombre, persona_moral=persona_moral, regimen=regimen)]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


# ---------------------------------------------------------------- documentos fiscales


def _opciones(payload: ArmadoIn, serie: str = docs.SERIE_DEFECTO) -> docs.OpcionesArmado:
    renglones = tuple(
        Renglon(
            descripcion=r.descripcion,
            cantidad=r.cantidad,
            valor_unitario=r.valor_unitario,
            descuento=r.descuento,
            clave_prod_serv=r.clave_prod_serv,
            clave_unidad=r.clave_unidad,
            unidad=r.unidad,
            no_identificacion=r.no_identificacion,
        )
        for r in payload.conceptos or ()
    )
    return docs.OpcionesArmado(
        serie=serie,
        tratamiento_iva=payload.tratamiento_iva,
        clave_prod_serv=payload.clave_prod_serv,
        clave_unidad=payload.clave_unidad,
        renglones=renglones,
    )


def _http(exc: docs.DocumentoError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/documents", response_model=DocumentoRead, status_code=201)
def create_document(
    payload: DocumentoCreate,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    """Prepara el borrador de factura de un ingreso o una cuenta por cobrar."""
    try:
        doc = docs.crear_borrador(
            db, org_id, payload.origen_tipo, payload.origen_id, _opciones(payload, payload.serie), user_id=user.id
        )
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    return DocumentoRead.model_validate(doc)


@router.get("/documents")
def list_documents(
    origen_tipo: Literal["income", "receivable"] | None = Query(default=None),
    origen_id: str | None = Query(default=None, max_length=36),
    estado: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    filas, total = docs.listar(
        db, org_id, origen_tipo=origen_tipo, origen_id=origen_id, estado=estado, limit=limit, offset=offset
    )
    return {"items": [DocumentoRead.model_validate(f) for f in filas], "total": total, "limit": limit, "offset": offset}


@router.get("/documents/{documento_id}", response_model=DocumentoRead)
def get_document(documento_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    try:
        return DocumentoRead.model_validate(docs.obtener(db, org_id, documento_id))
    except docs.DocumentoError as exc:
        raise _http(exc) from exc


@router.post("/documents/{documento_id}/rebuild", response_model=DocumentoRead)
def rebuild_document(
    documento_id: str,
    payload: ArmadoIn,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    """Vuelve a tomar los datos de la operación y del cliente, y fecha el borrador de nuevo."""
    try:
        return DocumentoRead.model_validate(docs.rearmar(db, org_id, documento_id, _opciones(payload)))
    except docs.DocumentoError as exc:
        raise _http(exc) from exc


@router.post("/documents/{documento_id}/validate", response_model=ValidacionRead)
def validate_document(
    documento_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    """Validación previa: problemas en español, con el código del SAT cuando aplica."""
    try:
        _doc, resultado = docs.validar(db, org_id, documento_id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    return ValidacionRead(**resultado.como_dict())


@router.get("/documents/{documento_id}/xml")
def download_draft_xml(documento_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    """XML sin sellar, sólo para revisión. NO tiene validez fiscal."""
    try:
        doc, xml = docs.xml_borrador(db, org_id, documento_id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    nombre = f"BORRADOR-SIN-VALIDEZ-FISCAL-{doc.serie}-{doc.folio}.xml"
    return Response(
        content=xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "X-Validez-Fiscal": "ninguna; borrador sin sello ni timbre",
        },
    )


# ---------------------------------------------------------------- sellado, timbrado y cancelación (ADR-017/018)

from app.config import get_settings  # noqa: E402
from app.domains.fiscal_mx import timbrado as timbrado_service  # noqa: E402
from app.domains.fiscal_mx.schemas import CancelacionIn, EstatusRead  # noqa: E402
from app.models.organization import ROLE_ADMIN, ROLE_OWNER  # noqa: E402
from app.services.cfdi import configuracion as cfdi_config  # noqa: E402

# Sellar usa el certificado de la empresa: sólo dueño o administrador.
ROLES_TIMBRADO = (ROLE_OWNER, ROLE_ADMIN)


def servicios_timbrado() -> cfdi_config.ServiciosTimbrado:
    """Firmante y proveedor configurados; 503 en español mientras el timbrado no esté disponible."""
    try:
        return cfdi_config.construir(get_settings())
    except cfdi_config.TimbradoNoDisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def servicios_timbrado_opcional() -> cfdi_config.ServiciosTimbrado | None:
    try:
        return cfdi_config.construir(get_settings())
    except cfdi_config.TimbradoNoDisponible:
        return None


@router.post("/documents/{documento_id}/stamp", response_model=DocumentoRead)
def stamp_document(
    documento_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(ROLES_TIMBRADO)),
    servicios: cfdi_config.ServiciosTimbrado = Depends(servicios_timbrado),
):
    """Sella con el certificado de la empresa y timbra con el proveedor. Idempotente."""
    try:
        doc = timbrado_service.timbrar(db, org_id, documento_id, servicios, user_id=user.id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    return DocumentoRead.model_validate(doc)


@router.post("/documents/{documento_id}/cancel", response_model=DocumentoRead)
def cancel_document(
    documento_id: str,
    payload: CancelacionIn,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(ROLES_TIMBRADO)),
    servicios: cfdi_config.ServiciosTimbrado = Depends(servicios_timbrado),
):
    """Solicita la cancelación ante el SAT (motivo 01 a 04). No cancela el ingreso ni toca el libro."""
    try:
        doc = timbrado_service.cancelar(
            db, org_id, documento_id, payload.motivo, payload.folio_sustitucion, servicios, user_id=user.id
        )
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    return DocumentoRead.model_validate(doc)


@router.get("/documents/{documento_id}/status", response_model=EstatusRead)
def document_status(
    documento_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    servicios: cfdi_config.ServiciosTimbrado | None = Depends(servicios_timbrado_opcional),
):
    """Estado del documento; si está timbrado y el timbrado está disponible, consulta al SAT por el proveedor."""
    try:
        doc = timbrado_service.consultar_estatus(db, org_id, documento_id, servicios, user_id=user.id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    leido = EstatusRead.model_validate(doc)
    leido.timbrado_disponible = servicios is not None
    return leido


@router.get("/documents/{documento_id}/stamped-xml")
def download_stamped_xml(documento_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    """XML timbrado tal como lo devolvió el proveedor (byte por byte)."""
    try:
        doc, xml = timbrado_service.xml_timbrado(db, org_id, documento_id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{doc.serie}-{doc.folio}-{doc.uuid_fiscal}.xml"'},
    )


@router.get("/documents/{documento_id}/pdf")
def download_pdf(documento_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    """Representación impresa, armada del XML. Sin timbre lleva la marca "Sin validez fiscal" y no trae QR."""
    from app.models.fiscal_document import FD_CANCELADO
    from app.services.cfdi import pdf as cfdi_pdf

    try:
        doc, xml = docs.xml_para_impresion(db, org_id, documento_id)
    except docs.DocumentoError as exc:
        raise _http(exc) from exc
    try:
        datos = cfdi_pdf.leer_cfdi(xml)
        contenido = cfdi_pdf.render_pdf(xml, cancelado=doc.estado == FD_CANCELADO)
    except cfdi_pdf.CfdiIlegible as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    nombre = re.sub(r"[^A-Za-z0-9_-]", "_", datos.serie_folio)
    headers = {"Content-Disposition": f'attachment; filename="{nombre}.pdf"'}
    if not datos.timbrado:
        headers["X-Validez-Fiscal"] = "ninguna; representacion sin timbre"  # encabezado HTTP: sólo ASCII
    return Response(content=contenido, media_type="application/pdf", headers=headers)
