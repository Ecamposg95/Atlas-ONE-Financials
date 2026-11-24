"""conciliación bancaria: estados de cuenta, renglones y coincidencias

Revision ID: 20261124_01
Revises: 20261123_01
Create Date: 2026-11-24

Tres tablas nuevas. No tocan pólizas, movimientos ni saldos: conciliar sólo
liga renglones del banco con movimientos existentes.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261124_01"
down_revision = "20261123_01"
branch_labels = None
depends_on = None


def _audit() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "bank_statements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("financial_account_id", sa.String(36), sa.ForeignKey("financial_accounts.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_hash", sa.String(110), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("closing_balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("book_balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("in_transit_in", sa.Numeric(14, 2), nullable=True),
        sa.Column("in_transit_out", sa.Numeric(14, 2), nullable=True),
        sa.Column("differences_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("ignored_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("unexplained", sa.Numeric(14, 2), nullable=True),
        sa.Column("closed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        *_audit(),
        sa.UniqueConstraint("financial_account_id", "file_hash", name="uq_bank_statements_account_file"),
    )
    op.create_index("ix_bank_statements_organization_id", "bank_statements", ["organization_id"])
    op.create_index("ix_bank_statements_financial_account_id", "bank_statements", ["financial_account_id"])
    op.create_index("ix_bank_statements_period_end", "bank_statements", ["period_end"])

    op.create_table(
        "bank_statement_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("statement_id", sa.String(36), sa.ForeignKey("bank_statements.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("difference", sa.Numeric(14, 2), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("resolved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_audit(),
    )
    op.create_index("ix_bank_statement_lines_organization_id", "bank_statement_lines", ["organization_id"])
    op.create_index("ix_bank_statement_lines_statement_id", "bank_statement_lines", ["statement_id"])
    op.create_index("ix_bank_statement_lines_date", "bank_statement_lines", ["date"])

    op.create_table(
        "bank_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("line_id", sa.String(36), sa.ForeignKey("bank_statement_lines.id"), nullable=False),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("financial_transactions.id"), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        *_audit(),
        sa.UniqueConstraint("transaction_id", name="uq_bank_matches_transaction"),
    )
    op.create_index("ix_bank_matches_organization_id", "bank_matches", ["organization_id"])
    op.create_index("ix_bank_matches_line_id", "bank_matches", ["line_id"])


def downgrade() -> None:
    op.drop_table("bank_matches")
    op.drop_table("bank_statement_lines")
    op.drop_table("bank_statements")
