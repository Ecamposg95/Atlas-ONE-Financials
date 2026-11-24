"""Conciliación bancaria: el estado de cuenta contra los movimientos registrados.

Conciliar no mueve dinero ni escribe al libro. Un renglón del banco se liga
con uno o varios movimientos que ya existen; lo que el banco trae y los libros
no, se registra por los módulos de siempre y luego se liga. El sistema propone
coincidencias, pero ninguna cuenta hasta que una persona la confirma.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bank_reconciliation import BankMatch, BankStatement, BankStatementLine
from app.models.financial_account import ASSET_ACCOUNT_TYPES, FinancialAccount
from app.models.transaction import INFLOW_TYPES, FinancialTransaction
from app.services.imports.tabular import TabularFormatError, read_table
from app.services.imports.values import clean_text, parse_date, parse_money

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_LINES = 5000
PREVIEW_ROWS = 20
# El banco suele registrar después que los libros (liquidaciones, cheques).
SUGGESTION_WINDOW_DAYS = 7
CANDIDATE_WINDOW_DAYS = 45
# Un estado de cuenta es de un banco o de un procesador; la caja se arquea con
# cortes y la tarjeta de crédito es pasivo (su signo va al revés).
RECONCILABLE_TYPES = tuple(t for t in ASSET_ACCOUNT_TYPES if t != "CASH")

ZERO = Decimal("0")
CENT = Decimal("0.01")

FIELDS = ("date", "description", "reference", "amount", "deposit", "withdrawal")
_SYNONYMS = {
    "date": ("fecha", "fecha operacion", "fecha de operacion", "fecha de movimiento", "dia", "date"),
    "description": ("descripcion", "concepto", "detalle", "movimiento", "description"),
    "reference": ("referencia", "folio", "ref", "numero de referencia", "clave de rastreo", "reference"),
    "amount": ("importe", "monto", "cantidad", "amount"),
    "deposit": ("abono", "abonos", "deposito", "depositos", "credito", "creditos", "ingreso", "ingresos"),
    "withdrawal": ("cargo", "cargos", "retiro", "retiros", "debito", "debitos", "egreso", "egresos"),
}


class ReconciliationConflictError(ValueError):
    """El estado de cuenta ya existe o ya no admite cambios (409)."""


def _q(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT)


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", clean_text(text).lower())
    return "".join(ch for ch in plain if not unicodedata.combining(ch))


def detect_mapping(columns: list[str]) -> dict[str, str]:
    """Columna del archivo para cada campo, por el nombre del encabezado."""
    mapping: dict[str, str] = {}
    normalized = {column: _norm(column) for column in columns}
    for field, names in _SYNONYMS.items():
        for column, name in normalized.items():
            if name in names and column not in mapping.values():
                mapping[field] = column
                break
    return mapping


def _clean_mapping(columns: list[str], mapping: dict | None) -> dict[str, str]:
    detected = detect_mapping(columns)
    if mapping:
        for field, column in mapping.items():
            if field not in FIELDS:
                raise ValueError(f"No existe el campo {field}.")
            if column in (None, ""):
                detected.pop(field, None)
            elif column not in columns:
                raise ValueError(f"El archivo no tiene una columna llamada {column}.")
            else:
                detected[field] = column
    if "date" not in detected:
        raise ValueError("Indica qué columna trae la fecha.")
    if "amount" not in detected and "deposit" not in detected and "withdrawal" not in detected:
        raise ValueError("Indica qué columna trae el importe, o las de abonos y cargos.")
    return detected


def parse_rows(rows: list[dict], mapping: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Renglones válidos y renglones omitidos con su motivo. Un renglón sin
    fecha (subtotales, leyendas del banco) o sin importe se omite: no se inventa."""
    parsed: list[dict] = []
    skipped: list[dict] = []
    for row in rows:
        number = row.get("_row_number")
        try:
            when = parse_date(row.get(mapping["date"]))
        except ValueError:
            skipped.append({"row_number": number, "reason": "No trae una fecha válida."})
            continue
        try:
            if "amount" in mapping:
                amount = parse_money(row.get(mapping["amount"]))
            else:
                deposit = abs(parse_money(row.get(mapping["deposit"]))) if "deposit" in mapping else ZERO
                withdrawal = abs(parse_money(row.get(mapping["withdrawal"]))) if "withdrawal" in mapping else ZERO
                amount = deposit - withdrawal
        except ValueError:
            skipped.append({"row_number": number, "reason": "El importe no es un número."})
            continue
        amount = _q(amount)
        if amount == ZERO:
            skipped.append({"row_number": number, "reason": "No trae importe."})
            continue
        description = clean_text(row.get(mapping["description"])) if "description" in mapping else ""
        reference = clean_text(row.get(mapping["reference"])) if "reference" in mapping else ""
        parsed.append(
            {
                "row_number": number,
                "date": when,
                "description": (description or "Sin descripción")[:500],
                "reference": reference[:100] or None,
                "amount": amount,
            }
        )
    return parsed, skipped


def _read(content: bytes, filename: str, sheet: str | None):
    if not content:
        raise ValueError("El archivo está vacío.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("El archivo pesa más de 10 MB.")
    try:
        return read_table(content, filename, sheet)
    except TabularFormatError as exc:
        raise ValueError(str(exc)) from exc


def preview(content: bytes, filename: str, sheet: str | None, mapping: dict | None) -> dict:
    table = _read(content, filename, sheet)
    detected = detect_mapping(table.columns)
    try:
        effective = _clean_mapping(table.columns, mapping)
        parsed, skipped = parse_rows(table.rows, effective)
        problem = None
    except ValueError as exc:
        effective, parsed, skipped, problem = {**detected, **(mapping or {})}, [], [], str(exc)
    return {
        "columns": table.columns,
        "sheets": table.sheets,
        "sheet": table.sheet,
        "mapping": effective,
        "problem": problem,
        "total_rows": len(parsed),
        "skipped": skipped[:50],
        "skipped_count": len(skipped),
        "period_start": min((r["date"] for r in parsed), default=None),
        "period_end": max((r["date"] for r in parsed), default=None),
        "deposits": sum((r["amount"] for r in parsed if r["amount"] > 0), ZERO),
        "withdrawals": -sum((r["amount"] for r in parsed if r["amount"] < 0), ZERO),
        "rows": parsed[:PREVIEW_ROWS],
    }


def get_account(db: Session, org_id: str, account_id: str) -> FinancialAccount:
    account = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.id == account_id,
            FinancialAccount.organization_id == org_id,
            FinancialAccount.deleted_at.is_(None),
        )
        .first()
    )
    if account is None:
        raise LookupError("Esa cuenta no existe.")
    if account.type not in RECONCILABLE_TYPES:
        raise ValueError("Sólo se concilian cuentas de banco y procesadores de pago.")
    return account


def create_statement(
    db: Session,
    org_id: str,
    account_id: str,
    filename: str,
    content: bytes,
    sheet: str | None,
    mapping: dict | None,
    closing_balance: Decimal | None,
    user_id: str | None,
) -> BankStatement:
    account = get_account(db, org_id, account_id)
    table = _read(content, filename, sheet)
    parsed, _skipped = parse_rows(table.rows, _clean_mapping(table.columns, mapping))
    if not parsed:
        raise ValueError("El archivo no trae ningún renglón con fecha e importe.")
    if len(parsed) > MAX_LINES:
        raise ValueError(f"El archivo trae más de {MAX_LINES} renglones; divídelo por mes.")
    file_hash = hashlib.sha256(content).hexdigest()
    duplicate = (
        db.query(BankStatement.id)
        .filter(
            BankStatement.organization_id == org_id,
            BankStatement.financial_account_id == account.id,
            BankStatement.file_hash == file_hash,
        )
        .first()
    )
    if duplicate is not None:
        raise ReconciliationConflictError("Ese archivo ya se importó en esta cuenta.")
    statement = BankStatement(
        organization_id=org_id,
        financial_account_id=account.id,
        filename=(filename or "archivo")[:255],
        file_hash=file_hash,
        period_start=min(r["date"] for r in parsed),
        period_end=max(r["date"] for r in parsed),
        closing_balance=_q(closing_balance) if closing_balance is not None else None,
        created_by=user_id,
    )
    db.add(statement)
    db.flush()
    for row in parsed:
        db.add(BankStatementLine(organization_id=org_id, statement_id=statement.id, **row))
    db.commit()
    db.refresh(statement)
    return statement


def get_statement(db: Session, org_id: str, statement_id: str) -> BankStatement:
    statement = (
        db.query(BankStatement)
        .filter(BankStatement.id == statement_id, BankStatement.organization_id == org_id)
        .first()
    )
    if statement is None:
        raise LookupError("Ese estado de cuenta no existe.")
    return statement


def _open(statement: BankStatement) -> None:
    if statement.status != "OPEN":
        raise ReconciliationConflictError("Esta conciliación ya está cerrada o cancelada. Reábrela para cambiarla.")


def _line(db: Session, statement: BankStatement, line_id: str) -> BankStatementLine:
    line = (
        db.query(BankStatementLine)
        .filter(
            BankStatementLine.id == line_id,
            BankStatementLine.statement_id == statement.id,
            BankStatementLine.organization_id == statement.organization_id,
        )
        .first()
    )
    if line is None:
        raise LookupError("Ese renglón no existe.")
    return line


def signed(transaction: FinancialTransaction) -> Decimal:
    amount = Decimal(transaction.amount)
    return amount if transaction.transaction_type in INFLOW_TYPES else -amount


def lines_of(db: Session, statement: BankStatement) -> list[BankStatementLine]:
    return (
        db.query(BankStatementLine)
        .filter(BankStatementLine.statement_id == statement.id)
        .order_by(BankStatementLine.date, BankStatementLine.row_number)
        .all()
    )


def matches_of(db: Session, statement: BankStatement) -> dict[str, list[FinancialTransaction]]:
    """Movimientos ligados a cada renglón, incluidos los que se cancelaron después."""
    rows = (
        db.query(BankMatch.line_id, FinancialTransaction)
        .join(FinancialTransaction, FinancialTransaction.id == BankMatch.transaction_id)
        .join(BankStatementLine, BankStatementLine.id == BankMatch.line_id)
        .filter(BankStatementLine.statement_id == statement.id)
        .order_by(FinancialTransaction.date, FinancialTransaction.created_at)
        .all()
    )
    grouped: dict[str, list[FinancialTransaction]] = {}
    for line_id, transaction in rows:
        grouped.setdefault(line_id, []).append(transaction)
    return grouped


def unmatched_transactions(
    db: Session, statement: BankStatement, date_from: date_type, date_to: date_type
) -> list[FinancialTransaction]:
    """Movimientos vigentes de la cuenta que ningún renglón de banco ha tomado."""
    taken = db.query(BankMatch.transaction_id).filter(BankMatch.organization_id == statement.organization_id)
    return (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.organization_id == statement.organization_id,
            FinancialTransaction.financial_account_id == statement.financial_account_id,
            FinancialTransaction.status == "ACTIVE",
            FinancialTransaction.date >= date_from,
            FinancialTransaction.date <= date_to,
            FinancialTransaction.id.notin_(taken),
        )
        .order_by(FinancialTransaction.date, FinancialTransaction.created_at)
        .all()
    )


def suggestions_for(
    lines: list[BankStatementLine], pool: list[FinancialTransaction]
) -> dict[str, list[dict]]:
    """Propuestas por renglón pendiente: movimientos del mismo importe en ±7 días
    (primero el de la misma referencia, luego el más cercano) y, si no hay, el
    conjunto de movimientos de un día que suma el renglón (un depósito que
    liquida varias ventas). Son propuestas: nada cuenta hasta confirmarse."""
    window = timedelta(days=SUGGESTION_WINDOW_DAYS)
    result: dict[str, list[dict]] = {}
    for line in lines:
        if line.status != "PENDING":
            continue
        amount = Decimal(line.amount)
        near = [t for t in pool if abs(t.date - line.date) <= window and (signed(t) > 0) == (amount > 0)]
        reference = _norm(line.reference or "")

        def rank(t: FinancialTransaction, reference=reference, day=line.date):
            same_reference = bool(reference) and _norm(t.reference or "") == reference
            return (0 if same_reference else 1, abs((t.date - day).days), t.date)

        exact = sorted((t for t in near if signed(t) == amount), key=rank)
        found = [{"kind": "EXACT", "transactions": [t]} for t in exact[:3]]
        if not found:
            by_day: dict[date_type, list[FinancialTransaction]] = {}
            for t in near:
                by_day.setdefault(t.date, []).append(t)
            for day in sorted(by_day, key=lambda d: abs((d - line.date).days)):
                group = by_day[day]
                if len(group) > 1 and sum((signed(t) for t in group), ZERO) == amount:
                    found.append({"kind": "GROUP", "transactions": group})
                    break
        if found:
            result[line.id] = found
    return result


def match_line(
    db: Session, statement: BankStatement, line_id: str, transaction_ids: list[str], user_id: str | None
) -> BankStatementLine:
    _open(statement)
    line = _line(db, statement, line_id)
    if line.status != "PENDING":
        raise ReconciliationConflictError("Ese renglón ya está resuelto. Deshazlo antes de volver a ligarlo.")
    ids = list(dict.fromkeys(transaction_ids))
    if not ids:
        raise ValueError("Elige al menos un movimiento.")
    transactions = (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.organization_id == statement.organization_id,
            FinancialTransaction.financial_account_id == statement.financial_account_id,
            FinancialTransaction.id.in_(ids),
        )
        .all()
    )
    if len(transactions) != len(ids):
        raise LookupError("Alguno de los movimientos no existe en esta cuenta.")
    if any(t.status != "ACTIVE" for t in transactions):
        raise ValueError("Alguno de los movimientos está cancelado.")
    taken = db.query(BankMatch.id).filter(BankMatch.transaction_id.in_(ids)).first()
    if taken is not None:
        raise ReconciliationConflictError("Alguno de los movimientos ya está conciliado con otro renglón.")
    for transaction in transactions:
        db.add(
            BankMatch(
                organization_id=statement.organization_id,
                line_id=line.id,
                transaction_id=transaction.id,
                created_by=user_id,
            )
        )
    line.status = "MATCHED"
    line.difference = _q(Decimal(line.amount) - sum((signed(t) for t in transactions), ZERO))
    line.resolved_by = user_id
    line.resolved_at = datetime.now(timezone.utc)
    return line


def reset_line(db: Session, statement: BankStatement, line_id: str) -> BankStatementLine:
    """Deshace la coincidencia o el "no corresponde": el renglón vuelve a pendiente."""
    _open(statement)
    line = _line(db, statement, line_id)
    db.query(BankMatch).filter(BankMatch.line_id == line.id).delete(synchronize_session=False)
    line.status = "PENDING"
    line.difference = None
    line.note = None
    line.resolved_by = None
    line.resolved_at = None
    return line


def ignore_line(
    db: Session, statement: BankStatement, line_id: str, note: str, user_id: str | None
) -> BankStatementLine:
    _open(statement)
    line = _line(db, statement, line_id)
    if line.status != "PENDING":
        raise ReconciliationConflictError("Ese renglón ya está resuelto.")
    note = clean_text(note)
    if not note:
        raise ValueError("Explica por qué este renglón no corresponde a ningún movimiento.")
    line.status = "IGNORED"
    line.note = note[:500]
    line.resolved_by = user_id
    line.resolved_at = datetime.now(timezone.utc)
    return line


def auto_match(db: Session, statement: BankStatement, user_id: str | None) -> int:
    """Confirma de una vez las coincidencias sin ambigüedad: un renglón con un
    solo movimiento posible del mismo importe, que a su vez no sirve para ningún
    otro renglón. Lo dispara una persona; lo dudoso se queda pendiente."""
    _open(statement)
    confirmed = 0
    while True:
        lines = [line for line in lines_of(db, statement) if line.status == "PENDING"]
        pool = unmatched_transactions(
            db,
            statement,
            statement.period_start - timedelta(days=SUGGESTION_WINDOW_DAYS),
            statement.period_end + timedelta(days=SUGGESTION_WINDOW_DAYS),
        )
        window = timedelta(days=SUGGESTION_WINDOW_DAYS)
        options: dict[str, list[str]] = {}
        uses: dict[str, int] = {}
        for line in lines:
            ids = [
                t.id
                for t in pool
                if signed(t) == Decimal(line.amount) and abs(t.date - line.date) <= window
            ]
            options[line.id] = ids
            for transaction_id in ids:
                uses[transaction_id] = uses.get(transaction_id, 0) + 1
        sure = [(line_id, ids[0]) for line_id, ids in options.items() if len(ids) == 1 and uses[ids[0]] == 1]
        if not sure:
            break
        for line_id, transaction_id in sure:
            match_line(db, statement, line_id, [transaction_id], user_id)
            confirmed += 1
        db.flush()
    return confirmed


def book_balance_at(db: Session, statement: BankStatement, when: date_type) -> Decimal:
    """Saldo en libros al cierre del día: el saldo actual menos lo posterior."""
    account = db.get(FinancialAccount, statement.financial_account_id)
    later = (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.organization_id == statement.organization_id,
            FinancialTransaction.financial_account_id == statement.financial_account_id,
            FinancialTransaction.status == "ACTIVE",
            FinancialTransaction.date > when,
        )
        .all()
    )
    return _q(Decimal(account.current_balance) - sum((signed(t) for t in later), ZERO))


def reversed_ids(db: Session, org_id: str, transactions: list[FinancialTransaction]) -> set[str]:
    """Movimientos cuya operación se revirtió después. Cancelar no borra ni
    desactiva el movimiento: agrega uno espejo con origen `<origen>_reversal`."""
    origins = {(t.source_type, t.source_id) for t in transactions if t.source_type and t.source_id}
    if not origins:
        return set()
    rows = (
        db.query(FinancialTransaction.source_type, FinancialTransaction.source_id)
        .filter(
            FinancialTransaction.organization_id == org_id,
            FinancialTransaction.status == "ACTIVE",
            FinancialTransaction.source_type.in_({f"{source_type}_reversal" for source_type, _ in origins}),
            FinancialTransaction.source_id.in_({source_id for _, source_id in origins}),
        )
        .all()
    )
    undone = {(source_type.removesuffix("_reversal"), source_id) for source_type, source_id in rows}
    return {t.id for t in transactions if (t.source_type, t.source_id) in undone}


def summarize(
    db: Session,
    statement: BankStatement,
    lines: list[BankStatementLine],
    matches: dict[str, list[FinancialTransaction]],
    in_transit: list[FinancialTransaction],
) -> dict:
    """Las cifras de la conciliación. Abierta se calcula al momento; cerrada
    devuelve la fotografía que se guardó al cerrar.

    Saldo en banco = saldo en libros − entradas en tránsito + salidas en
    tránsito + renglones sin movimiento + diferencias. Lo que no cierre con
    esa cuenta es "sin explicar" (típicamente, periodos anteriores sin conciliar).
    """
    pending = [line for line in lines if line.status == "PENDING"]
    ignored = [line for line in lines if line.status == "IGNORED"]
    with_difference = [line for line in lines if line.status == "MATCHED" and _q(line.difference) != ZERO]
    undone = reversed_ids(db, statement.organization_id, [t for group in matches.values() for t in group])
    cancelled_after = [
        line
        for line in lines
        if any(t.status != "ACTIVE" or t.id in undone for t in matches.get(line.id, []))
    ]
    closed = statement.status == "CLOSED"
    if closed:
        book_balance = statement.book_balance
        transit_in, transit_out = _q(statement.in_transit_in), _q(statement.in_transit_out)
        differences_total, ignored_total = _q(statement.differences_total), _q(statement.ignored_total)
        unexplained = statement.unexplained
    else:
        book_balance = book_balance_at(db, statement, statement.period_end)
        transit_in = _q(sum((signed(t) for t in in_transit if signed(t) > 0), ZERO))
        transit_out = _q(-sum((signed(t) for t in in_transit if signed(t) < 0), ZERO))
        differences_total = _q(sum((Decimal(line.difference) for line in with_difference), ZERO))
        ignored_total = _q(sum((Decimal(line.amount) for line in ignored), ZERO))
        unexplained = None
        if statement.closing_balance is not None:
            expected = book_balance - transit_in + transit_out + ignored_total + differences_total
            unexplained = _q(Decimal(statement.closing_balance) - expected)

    alerts: list[dict] = []
    if with_difference:
        alerts.append(
            {
                "kind": "DIFFERENCE",
                "count": len(with_difference),
                "amount": differences_total,
                "message": "Renglones ligados cuyo importe no coincide con sus movimientos.",
            }
        )
    if pending:
        alerts.append(
            {
                "kind": "PENDING",
                "count": len(pending),
                "amount": _q(sum((Decimal(line.amount) for line in pending), ZERO)),
                "message": "Renglones del banco que nadie ha ligado ni explicado.",
            }
        )
    if cancelled_after:
        alerts.append(
            {
                "kind": "CANCELLED_MATCH",
                "count": len(cancelled_after),
                "amount": None,
                "message": "Renglones ligados a un movimiento que después se canceló o se revirtió.",
            }
        )
    if not closed and in_transit:
        alerts.append(
            {
                "kind": "BOOK_UNMATCHED",
                "count": len(in_transit),
                "amount": _q(transit_in - transit_out),
                "message": "Movimientos registrados en el periodo que no aparecen en el banco.",
            }
        )
    if unexplained is not None and _q(unexplained) != ZERO:
        alerts.append(
            {
                "kind": "UNEXPLAINED",
                "count": 1,
                "amount": _q(unexplained),
                "message": "El saldo del banco y el de libros no cuadran con las partidas identificadas.",
            }
        )
    return {
        "lines_count": len(lines),
        "deposits": _q(sum((Decimal(line.amount) for line in lines if line.amount > 0), ZERO)),
        "withdrawals": _q(-sum((Decimal(line.amount) for line in lines if line.amount < 0), ZERO)),
        "pending_count": len(pending),
        "matched_count": len([line for line in lines if line.status == "MATCHED"]),
        "ignored_count": len(ignored),
        "differences_count": len(with_difference),
        "differences_total": differences_total,
        "ignored_total": ignored_total,
        "book_balance": book_balance,
        "closing_balance": statement.closing_balance,
        "in_transit_in": transit_in,
        "in_transit_out": transit_out,
        "unexplained": unexplained,
        "alerts": alerts,
    }


def in_transit_of(db: Session, statement: BankStatement) -> list[FinancialTransaction]:
    return unmatched_transactions(db, statement, statement.period_start, statement.period_end)


def close_statement(
    db: Session, statement: BankStatement, closing_balance: Decimal | None, user_id: str | None
) -> BankStatement:
    _open(statement)
    if closing_balance is not None:
        statement.closing_balance = _q(closing_balance)
    if statement.closing_balance is None:
        raise ValueError("Captura el saldo final que marca el estado de cuenta.")
    lines = lines_of(db, statement)
    if any(line.status == "PENDING" for line in lines):
        raise ValueError("Quedan renglones pendientes: lígalos o explica por qué no corresponden.")
    summary = summarize(db, statement, lines, matches_of(db, statement), in_transit_of(db, statement))
    statement.book_balance = summary["book_balance"]
    statement.in_transit_in = summary["in_transit_in"]
    statement.in_transit_out = summary["in_transit_out"]
    statement.differences_total = summary["differences_total"]
    statement.ignored_total = summary["ignored_total"]
    statement.unexplained = summary["unexplained"]
    statement.status = "CLOSED"
    statement.closed_by = user_id
    statement.closed_at = datetime.now(timezone.utc)
    return statement


def reopen_statement(db: Session, statement: BankStatement) -> BankStatement:
    if statement.status != "CLOSED":
        raise ReconciliationConflictError("Sólo se reabre una conciliación cerrada.")
    statement.status = "OPEN"
    statement.closed_by = None
    statement.closed_at = None
    for column in ("book_balance", "in_transit_in", "in_transit_out", "differences_total", "ignored_total", "unexplained"):
        setattr(statement, column, None)
    return statement


def cancel_statement(db: Session, statement: BankStatement, user_id: str | None) -> BankStatement:
    """Descarta el archivo: sus movimientos quedan libres y el mismo archivo se
    puede volver a subir. La fila y sus renglones se conservan."""
    if statement.status == "CANCELLED":
        raise ReconciliationConflictError("Ese estado de cuenta ya estaba cancelado.")
    line_ids = db.query(BankStatementLine.id).filter(BankStatementLine.statement_id == statement.id)
    db.query(BankMatch).filter(BankMatch.line_id.in_(line_ids)).delete(synchronize_session=False)
    statement.status = "CANCELLED"
    statement.file_hash = f"{statement.file_hash}:{statement.id}"
    statement.cancelled_by = user_id
    statement.cancelled_at = datetime.now(timezone.utc)
    return statement


def candidates(
    db: Session, statement: BankStatement, line_id: str, search: str | None
) -> list[FinancialTransaction]:
    """Movimientos libres cerca del renglón, para ligar a mano."""
    line = _line(db, statement, line_id)
    window = timedelta(days=CANDIDATE_WINDOW_DAYS)
    pool = unmatched_transactions(db, statement, line.date - window, line.date + window)
    needle = _norm(search or "")
    if needle:
        pool = [
            t
            for t in pool
            if needle in _norm(t.description) or needle in _norm(t.reference or "") or needle in str(t.amount)
        ]
    pool.sort(key=lambda t: (abs((t.date - line.date).days), t.date))
    return pool[:100]


def open_alerts(db: Session, org_id: str) -> dict:
    """Lo que está sin resolver en las conciliaciones abiertas de la empresa."""
    open_ids = db.query(BankStatement.id).filter(
        BankStatement.organization_id == org_id, BankStatement.status == "OPEN"
    )
    pending = (
        db.query(func.count(BankStatementLine.id))
        .filter(BankStatementLine.statement_id.in_(open_ids), BankStatementLine.status == "PENDING")
        .scalar()
    )
    differences = (
        db.query(func.count(BankStatementLine.id))
        .filter(
            BankStatementLine.statement_id.in_(open_ids),
            BankStatementLine.status == "MATCHED",
            BankStatementLine.difference != 0,
        )
        .scalar()
    )
    return {
        "open_statements": open_ids.count(),
        "pending_lines": int(pending or 0),
        "difference_lines": int(differences or 0),
    }
