"""documentos fiscales (CFDI 4.0): documento, conceptos, impuestos, XML y series

Revision ID: 20261125_02
Revises: 20261125_01
Create Date: 2026-11-25

Fase 2 del megaplan de CFDI. Cinco tablas nuevas de la capa de localización
(ADR-013). No tocan pólizas, movimientos ni saldos. En PostgreSQL, un
disparador impide actualizar o borrar los XML guardados (sellado, timbrado,
acuse): reconstruirlos invalida el sello.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261125_02"
down_revision = "20261125_01"
branch_labels = None
depends_on = None


def _id_y_org() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "documentos_fiscales",
        *_id_y_org(),
        sa.Column("tipo_comprobante", sa.String(1), nullable=False, server_default="I"),
        sa.Column("estado", sa.String(30), nullable=False, server_default="BORRADOR"),
        sa.Column("origen_tipo", sa.String(20), nullable=False),
        sa.Column("origen_id", sa.String(36), nullable=False),
        sa.Column("income_id", sa.String(36), sa.ForeignKey("incomes.id"), nullable=True),
        sa.Column("receivable_id", sa.String(36), sa.ForeignKey("receivables.id"), nullable=True),
        sa.Column("emisor_fiscal_entity_id", sa.String(36), sa.ForeignKey("fiscal_entities.id"), nullable=True),
        sa.Column("emisor_clave", sa.String(36), nullable=False),
        sa.Column("emisor_rfc", sa.String(13), nullable=True),
        sa.Column("emisor_nombre", sa.String(300), nullable=True),
        sa.Column("emisor_regimen", sa.String(3), nullable=True),
        sa.Column("receptor_customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("receptor_rfc", sa.String(13), nullable=True),
        sa.Column("receptor_nombre", sa.String(300), nullable=True),
        sa.Column("receptor_regimen", sa.String(3), nullable=True),
        sa.Column("receptor_domicilio_fiscal", sa.String(5), nullable=True),
        sa.Column("receptor_uso_cfdi", sa.String(4), nullable=True),
        sa.Column("serie", sa.String(25), nullable=False),
        sa.Column("folio", sa.String(40), nullable=False),
        sa.Column("fecha_emision", sa.DateTime(timezone=False), nullable=False),
        sa.Column("fecha_emision_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("huso_horario", sa.String(60), nullable=True),
        sa.Column("lugar_expedicion", sa.String(5), nullable=True),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="MXN"),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("exportacion", sa.String(2), nullable=False, server_default="01"),
        sa.Column("forma_pago", sa.String(2), nullable=True),
        sa.Column("metodo_pago", sa.String(3), nullable=True),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("descuento", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_impuestos_trasladados", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_impuestos_retenidos", sa.Numeric(14, 2), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("supuestos", sa.JSON(), nullable=False),
        sa.Column("validado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validacion", sa.JSON(), nullable=True),
        sa.Column("uuid_fiscal", sa.String(36), nullable=True, unique=True),
        sa.Column("proveedor_timbrado", sa.String(40), nullable=True),
        sa.Column("rfc_prov_certif", sa.String(13), nullable=True),
        sa.Column("fecha_timbrado", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(income_id IS NOT NULL AND receivable_id IS NULL) OR (income_id IS NULL AND receivable_id IS NOT NULL)",
            name="ck_documentos_fiscales_un_origen",
        ),
        sa.UniqueConstraint("organization_id", "emisor_clave", "serie", "folio", name="uq_documentos_fiscales_folio"),
    )
    op.create_index("ix_documentos_fiscales_organization_id", "documentos_fiscales", ["organization_id"])
    op.create_index(
        "ix_documentos_fiscales_origen", "documentos_fiscales", ["organization_id", "origen_tipo", "origen_id"]
    )

    op.create_table(
        "documentos_fiscales_conceptos",
        *_id_y_org(),
        sa.Column("documento_id", sa.String(36), sa.ForeignKey("documentos_fiscales.id"), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("clave_prod_serv", sa.String(8), nullable=False),
        sa.Column("no_identificacion", sa.String(100), nullable=True),
        sa.Column("cantidad", sa.Numeric(20, 6), nullable=False),
        sa.Column("clave_unidad", sa.String(3), nullable=False),
        sa.Column("unidad", sa.String(20), nullable=True),
        sa.Column("descripcion", sa.String(1000), nullable=False),
        sa.Column("valor_unitario", sa.Numeric(20, 6), nullable=False),
        sa.Column("importe", sa.Numeric(14, 2), nullable=False),
        sa.Column("descuento", sa.Numeric(14, 2), nullable=True),
        sa.Column("objeto_imp", sa.String(2), nullable=False),
        sa.UniqueConstraint("documento_id", "orden", name="uq_documentos_fiscales_conceptos_orden"),
    )
    op.create_index(
        "ix_documentos_fiscales_conceptos_organization_id", "documentos_fiscales_conceptos", ["organization_id"]
    )
    op.create_index("ix_documentos_fiscales_conceptos_documento_id", "documentos_fiscales_conceptos", ["documento_id"])

    op.create_table(
        "documentos_fiscales_impuestos",
        *_id_y_org(),
        sa.Column("concepto_id", sa.String(36), sa.ForeignKey("documentos_fiscales_conceptos.id"), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("impuesto", sa.String(3), nullable=False),
        sa.Column("tipo_factor", sa.String(6), nullable=False),
        sa.Column("tasa_o_cuota", sa.Numeric(8, 6), nullable=True),
        sa.Column("base", sa.Numeric(14, 2), nullable=False),
        sa.Column("importe", sa.Numeric(14, 2), nullable=True),
    )
    op.create_index(
        "ix_documentos_fiscales_impuestos_organization_id", "documentos_fiscales_impuestos", ["organization_id"]
    )
    op.create_index("ix_documentos_fiscales_impuestos_concepto_id", "documentos_fiscales_impuestos", ["concepto_id"])

    op.create_table(
        "documentos_fiscales_xml",
        *_id_y_org(),
        sa.Column("documento_id", sa.String(36), sa.ForeignKey("documentos_fiscales.id"), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("contenido", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("documento_id", "tipo", name="uq_documentos_fiscales_xml_tipo"),
    )
    op.create_index("ix_documentos_fiscales_xml_organization_id", "documentos_fiscales_xml", ["organization_id"])
    op.create_index("ix_documentos_fiscales_xml_documento_id", "documentos_fiscales_xml", ["documento_id"])

    op.create_table(
        "documentos_fiscales_series",
        *_id_y_org(),
        sa.Column("emisor_clave", sa.String(36), nullable=False),
        sa.Column("serie", sa.String(25), nullable=False),
        sa.Column("siguiente_folio", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("organization_id", "emisor_clave", "serie", name="uq_documentos_fiscales_series"),
    )
    op.create_index("ix_documentos_fiscales_series_organization_id", "documentos_fiscales_series", ["organization_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION documentos_fiscales_xml_inmutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Un XML fiscal guardado no se modifica ni se borra';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER documentos_fiscales_xml_inmutable
            BEFORE UPDATE OR DELETE ON documentos_fiscales_xml
            FOR EACH ROW EXECUTE FUNCTION documentos_fiscales_xml_inmutable();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS documentos_fiscales_xml_inmutable ON documentos_fiscales_xml")
        op.execute("DROP FUNCTION IF EXISTS documentos_fiscales_xml_inmutable()")
    op.drop_table("documentos_fiscales_series")
    op.drop_table("documentos_fiscales_xml")
    op.drop_table("documentos_fiscales_impuestos")
    op.drop_table("documentos_fiscales_conceptos")
    op.drop_table("documentos_fiscales")
