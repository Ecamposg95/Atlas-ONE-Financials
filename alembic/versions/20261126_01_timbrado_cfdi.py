"""timbrado CFDI: estado del envío, cancelación, secuencia del XML y bitácora de firmas

Revision ID: 20261126_01
Revises: 20261125_02
Create Date: 2026-11-26

Sellado, timbrado y cancelación del documento fiscal (ADR-017 y ADR-018).

- ``documentos_fiscales``: número de certificado, identificador idempotente,
  intentos, momento de envío (se fija antes de llamar al proveedor), último
  error, datos de la solicitud de cancelación y del último estatus del SAT.
- ``documentos_fiscales_xml``: columna ``secuencia``. Un rechazo por datos
  obliga a sellar otra vez; el sellado anterior se conserva intacto. La
  restricción única pasa a ``(documento_id, tipo, secuencia)``. Agregar la
  columna con valor por omisión no dispara el disparador de inmutabilidad
  (no es un UPDATE de filas).
- ``documentos_fiscales_bitacora``: sólo agregar; en PostgreSQL un disparador
  impide actualizarla o borrarla.

No toca pólizas, movimientos ni saldos.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261126_01"
down_revision = "20261125_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documentos_fiscales") as batch:
        batch.add_column(sa.Column("no_certificado", sa.String(20), nullable=True))
        batch.add_column(sa.Column("id_idempotente", sa.String(80), nullable=True))
        batch.add_column(sa.Column("timbrado_intentos", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("timbrado_enviado_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("ultimo_error", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("cancelacion_motivo", sa.String(2), nullable=True))
        batch.add_column(sa.Column("cancelacion_folio_sustitucion", sa.String(36), nullable=True))
        batch.add_column(sa.Column("cancelacion_solicitada_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("estatus_sat", sa.String(40), nullable=True))
        batch.add_column(sa.Column("es_cancelable", sa.String(60), nullable=True))
        batch.add_column(sa.Column("estatus_cancelacion_sat", sa.String(60), nullable=True))
        batch.add_column(sa.Column("estatus_consultado_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("documentos_fiscales_xml") as batch:
        batch.add_column(sa.Column("secuencia", sa.Integer(), nullable=False, server_default="1"))
        batch.drop_constraint("uq_documentos_fiscales_xml_tipo", type_="unique")
        batch.create_unique_constraint(
            "uq_documentos_fiscales_xml_tipo_secuencia", ["documento_id", "tipo", "secuencia"]
        )

    op.create_table(
        "documentos_fiscales_bitacora",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("documento_id", sa.String(36), sa.ForeignKey("documentos_fiscales.id"), nullable=False),
        sa.Column("evento", sa.String(30), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("no_certificado", sa.String(20), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("firmante", sa.String(30), nullable=True),
        sa.Column("proveedor", sa.String(40), nullable=True),
        sa.Column("uuid_fiscal", sa.String(36), nullable=True),
        sa.Column("resultado", sa.String(30), nullable=True),
        sa.Column("codigo", sa.String(40), nullable=True),
        sa.Column("mensaje", sa.String(500), nullable=True),
        sa.Column("segundos", sa.Numeric(8, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_documentos_fiscales_bitacora_organization_id", "documentos_fiscales_bitacora", ["organization_id"]
    )
    op.create_index(
        "ix_documentos_fiscales_bitacora_doc",
        "documentos_fiscales_bitacora",
        ["organization_id", "documento_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION documentos_fiscales_bitacora_inmutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'La bitácora de firmas no se modifica ni se borra';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER documentos_fiscales_bitacora_inmutable
            BEFORE UPDATE OR DELETE ON documentos_fiscales_bitacora
            FOR EACH ROW EXECUTE FUNCTION documentos_fiscales_bitacora_inmutable();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS documentos_fiscales_bitacora_inmutable ON documentos_fiscales_bitacora")
        op.execute("DROP FUNCTION IF EXISTS documentos_fiscales_bitacora_inmutable()")
    op.drop_table("documentos_fiscales_bitacora")
    # Bajar la secuencia sólo es posible si no hay dos XML del mismo tipo por documento.
    with op.batch_alter_table("documentos_fiscales_xml") as batch:
        batch.drop_constraint("uq_documentos_fiscales_xml_tipo_secuencia", type_="unique")
        batch.create_unique_constraint("uq_documentos_fiscales_xml_tipo", ["documento_id", "tipo"])
        batch.drop_column("secuencia")
    with op.batch_alter_table("documentos_fiscales") as batch:
        for columna in (
            "estatus_consultado_at",
            "estatus_cancelacion_sat",
            "es_cancelable",
            "estatus_sat",
            "cancelacion_solicitada_at",
            "cancelacion_folio_sustitucion",
            "cancelacion_motivo",
            "ultimo_error",
            "timbrado_enviado_at",
            "timbrado_intentos",
            "id_idempotente",
            "no_certificado",
        ):
            batch.drop_column(column_name=columna)
