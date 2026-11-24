from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.database import Base
from app.models.mixins import AuditMixin, TenantMixin, UUIDPKMixin

# OPEN → CLOSED. Un estado cerrado puede reabrirse; CANCELLED descarta el
# archivo y libera sus coincidencias (la fila queda, invariante 8).
BANK_STATEMENT_STATUSES = ("OPEN", "CLOSED", "CANCELLED")

# PENDING: nadie ha dicho qué es. MATCHED: ligado a uno o más movimientos.
# IGNORED: no corresponde a ningún movimiento y alguien explicó por qué.
BANK_LINE_STATUSES = ("PENDING", "MATCHED", "IGNORED")


class BankStatement(Base, UUIDPKMixin, TenantMixin, AuditMixin):
    """Estado de cuenta importado de un banco o procesador.

    Conciliar no mueve dinero ni escribe al libro: sólo liga renglones del
    banco con movimientos que ya existen. Lo que falte se registra por los
    módulos de siempre (ingresos, gastos, traspasos, liquidaciones).
    """

    __tablename__ = "bank_statements"
    __table_args__ = (
        UniqueConstraint("financial_account_id", "file_hash", name="uq_bank_statements_account_file"),
    )

    financial_account_id = Column(String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    # sha256 del archivo: el mismo archivo no se importa dos veces en la misma
    # cuenta. Al cancelar se le agrega el id para que se pueda volver a subir.
    file_hash = Column(String(110), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="OPEN")  # BANK_STATEMENT_STATUSES
    # Saldo final que imprime el banco. Lo captura la persona: no todos los
    # archivos lo traen. Sin él no hay comparación de saldos, sólo de renglones.
    closing_balance = Column(Numeric(14, 2), nullable=True)
    # Fotografía al cerrar, para que la conciliación sea reproducible aunque
    # después se registren movimientos con fecha anterior.
    book_balance = Column(Numeric(14, 2), nullable=True)
    in_transit_in = Column(Numeric(14, 2), nullable=True)
    in_transit_out = Column(Numeric(14, 2), nullable=True)
    differences_total = Column(Numeric(14, 2), nullable=True)
    ignored_total = Column(Numeric(14, 2), nullable=True)
    unexplained = Column(Numeric(14, 2), nullable=True)
    closed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    cancelled_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)


class BankStatementLine(Base, UUIDPKMixin, TenantMixin, AuditMixin):
    """Un renglón del estado de cuenta. `amount` lleva signo: depósito positivo,
    retiro negativo. Nunca se edita: es lo que dijo el banco."""

    __tablename__ = "bank_statement_lines"

    statement_id = Column(String(36), ForeignKey("bank_statements.id"), nullable=False, index=True)
    row_number = Column(Integer, nullable=False)
    date = Column(Date, nullable=False, index=True)
    description = Column(String(500), nullable=False)
    reference = Column(String(100), nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # BANK_LINE_STATUSES
    # Renglón del banco menos los movimientos ligados. Distinto de cero es una
    # diferencia a revisar (comisión no registrada, depósito incompleto).
    difference = Column(Numeric(14, 2), nullable=True)
    note = Column(String(500), nullable=True)
    resolved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class BankMatch(Base, UUIDPKMixin, TenantMixin, AuditMixin):
    """Liga un renglón del banco con un movimiento. Un depósito puede liquidar
    varias ventas (varias filas para el mismo renglón); un movimiento sólo
    puede estar en un renglón."""

    __tablename__ = "bank_matches"
    __table_args__ = (UniqueConstraint("transaction_id", name="uq_bank_matches_transaction"),)

    line_id = Column(String(36), ForeignKey("bank_statement_lines.id"), nullable=False, index=True)
    transaction_id = Column(String(36), ForeignKey("financial_transactions.id"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
