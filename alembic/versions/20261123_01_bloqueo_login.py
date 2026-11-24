"""bloqueo temporal de cuenta por contraseñas fallidas

Revision ID: 20261123_01
Revises: 20261112_01
Create Date: 2026-11-23

Contador de fallos consecutivos y fecha hasta la que la cuenta no acepta
inicios de sesión. El límite por IP vive en memoria (app/security/rate_limit.py).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261123_01"
down_revision = "20261112_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
