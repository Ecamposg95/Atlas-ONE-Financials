"""datos fiscales para CFDI: emisor, receptor y operación

Revision ID: 20261125_01
Revises: 20261124_01
Create Date: 2026-11-25

Fase 2 del megaplan de CFDI. Sólo columnas nuevas y nullable: régimen y código
postal fiscal en empresa, contribuyente y cliente (más razón social del
contribuyente y uso de CFDI por defecto del cliente); uso, forma y método de
pago del SAT en ingresos y cuentas por cobrar. Nada se borra ni se rellena; no
toca pólizas, movimientos ni saldos.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261125_01"
down_revision = "20261124_01"
branch_labels = None
depends_on = None

_COLUMNAS = {
    "organizations": [
        ("fiscal_regime", sa.String(3)),
        ("fiscal_postal_code", sa.String(5)),
    ],
    "fiscal_entities": [
        ("legal_name", sa.String(255)),
        ("fiscal_regime", sa.String(3)),
        ("fiscal_postal_code", sa.String(5)),
    ],
    "customers": [
        ("fiscal_regime", sa.String(3)),
        ("fiscal_postal_code", sa.String(5)),
        ("default_cfdi_use", sa.String(4)),
    ],
    "incomes": [
        ("cfdi_use", sa.String(4)),
        ("cfdi_payment_form", sa.String(2)),
        ("cfdi_payment_method", sa.String(3)),
    ],
    "receivables": [
        ("cfdi_use", sa.String(4)),
        ("cfdi_payment_form", sa.String(2)),
        ("cfdi_payment_method", sa.String(3)),
    ],
}


def upgrade() -> None:
    for tabla, columnas in _COLUMNAS.items():
        for nombre, tipo in columnas:
            op.add_column(tabla, sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    for tabla, columnas in _COLUMNAS.items():
        with op.batch_alter_table(tabla) as batch:
            for nombre, _tipo in reversed(columnas):
                batch.drop_column(nombre)
