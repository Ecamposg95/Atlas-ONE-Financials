"""tratamiento de IVA por operación y tasa de las retenciones (R2·HU-05)

Revision ID: 20261127_01
Revises: 20261126_01
Create Date: 2026-11-27

- ``tax_treatment`` en gastos, ingresos, cuentas por pagar y por cobrar:
  gravado, tasa 0, exento, no objeto o sin clasificar. Lo que ya lleva IVA
  queda como gravado; lo que está en 0 % queda SIN CLASIFICAR, porque hoy
  "Sin IVA / exento" mezclaba los tres casos y decidir cuál es le toca a
  contabilidad, no a una migración.
- ``retention_isr_rate`` y ``retention_iva_rate`` en gastos: la tasa con que se
  calculó cada retención (nula si se capturó el importe).

No toca pólizas, movimientos ni saldos.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261127_01"
down_revision = "20261126_01"
branch_labels = None
depends_on = None

TABLES = ("expenses", "incomes", "payables", "receivables")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("tax_treatment", sa.String(20), nullable=False, server_default="UNCLASSIFIED")
            )
        op.execute(f"UPDATE {table} SET tax_treatment = 'TAXED' WHERE tax_rate > 0")
    with op.batch_alter_table("expenses") as batch:
        batch.add_column(sa.Column("retention_isr_rate", sa.Numeric(7, 6), nullable=True))
        batch.add_column(sa.Column("retention_iva_rate", sa.Numeric(7, 6), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("expenses") as batch:
        batch.drop_column("retention_iva_rate")
        batch.drop_column("retention_isr_rate")
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("tax_treatment")
