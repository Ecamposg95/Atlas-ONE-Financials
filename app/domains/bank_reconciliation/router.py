import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.bank_reconciliation import service
from app.domains.bank_reconciliation.schemas import (
    BalanceRequest,
    CloseRequest,
    IgnoreRequest,
    LineRead,
    MatchRequest,
    StatementDetail,
    StatementRead,
    Suggestion,
    Summary,
    TransactionBrief,
)
from app.models.bank_reconciliation import BankStatement, BankStatementLine
from app.models.financial_account import FinancialAccount
from app.models.organization import ROLE_ADMIN, ROLE_OWNER, WRITE_ROLES
from app.models.transaction import FinancialTransaction
from app.models.user import User
from app.security.deps import get_current_org_id, get_current_user, require_role

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"])

# Reabrir una conciliación cerrada cambia lo que ya se dio por bueno.
REOPEN_ROLES = (ROLE_OWNER, ROLE_ADMIN)


def _fail(error: Exception) -> HTTPException:
    if isinstance(error, LookupError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, service.ReconciliationConflictError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=400, detail=str(error))


def _brief(transaction: FinancialTransaction) -> TransactionBrief:
    return TransactionBrief(
        id=transaction.id,
        date=transaction.date,
        description=transaction.description,
        reference=transaction.reference,
        transaction_type=transaction.transaction_type,
        amount=service.signed(transaction),
        status=transaction.status,
    )


def _mapping(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="El mapeo de columnas no es válido.") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="El mapeo de columnas no es válido.")
    return value


def _money(raw: str | None) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail="El saldo final no es un número.") from exc
    if not value.is_finite():
        raise HTTPException(status_code=400, detail="El saldo final no es un número.")
    return value


def _statement(db: Session, org_id: str, statement_id: str) -> BankStatement:
    try:
        return service.get_statement(db, org_id, statement_id)
    except LookupError as error:
        raise _fail(error) from error


def _reads(db: Session, org_id: str, statements: list[BankStatement]) -> list[StatementRead]:
    if not statements:
        return []
    ids = [s.id for s in statements]
    names = dict(
        db.query(FinancialAccount.id, FinancialAccount.name)
        .filter(
            FinancialAccount.organization_id == org_id,
            FinancialAccount.id.in_({s.financial_account_id for s in statements}),
        )
        .all()
    )
    counts = {
        row.statement_id: row
        for row in db.query(
            BankStatementLine.statement_id,
            func.count(BankStatementLine.id).label("total"),
            func.sum(case((BankStatementLine.status == "PENDING", 1), else_=0)).label("pending"),
            func.sum(
                case(
                    ((BankStatementLine.status == "MATCHED") & (BankStatementLine.difference != 0), 1),
                    else_=0,
                )
            ).label("differences"),
        )
        .filter(BankStatementLine.statement_id.in_(ids))
        .group_by(BankStatementLine.statement_id)
        .all()
    }
    items = []
    for statement in statements:
        item = StatementRead.model_validate(statement)
        item.account_name = names.get(statement.financial_account_id)
        row = counts.get(statement.id)
        if row is not None:
            item.lines_count = int(row.total or 0)
            item.pending_count = int(row.pending or 0)
            item.differences_count = int(row.differences or 0)
        items.append(item)
    return items


def _detail(db: Session, org_id: str, statement: BankStatement) -> StatementDetail:
    lines = service.lines_of(db, statement)
    matches = service.matches_of(db, statement)
    live = statement.status == "OPEN"
    in_transit = service.in_transit_of(db, statement) if live else []
    suggestions: dict = {}
    if live:
        pool = service.unmatched_transactions(
            db,
            statement,
            statement.period_start - timedelta(days=service.SUGGESTION_WINDOW_DAYS),
            statement.period_end + timedelta(days=service.SUGGESTION_WINDOW_DAYS),
        )
        suggestions = service.suggestions_for(lines, pool)
    return StatementDetail(
        statement=_reads(db, org_id, [statement])[0],
        summary=Summary(**service.summarize(db, statement, lines, matches, in_transit)),
        lines=[
            LineRead(
                id=line.id,
                row_number=line.row_number,
                date=line.date,
                description=line.description,
                reference=line.reference,
                amount=line.amount,
                status=line.status,
                difference=line.difference,
                note=line.note,
                matches=[_brief(t) for t in matches.get(line.id, [])],
                suggestions=[
                    Suggestion(kind=s["kind"], transactions=[_brief(t) for t in s["transactions"]])
                    for s in suggestions.get(line.id, [])
                ],
            )
            for line in lines
        ],
        in_transit=[_brief(t) for t in in_transit],
    )


@router.post("/preview")
def preview(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    mapping: str | None = Form(default=None),
    _org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    """Lee el archivo y muestra cómo se interpretaría. No guarda nada."""
    content = file.file.read(service.MAX_FILE_BYTES + 1)
    try:
        return service.preview(content, file.filename or "archivo", sheet or None, _mapping(mapping))
    except ValueError as error:
        raise _fail(error) from error


@router.post("", response_model=StatementDetail, status_code=201)
def create(
    file: UploadFile = File(...),
    financial_account_id: str = Form(...),
    sheet: str | None = Form(default=None),
    mapping: str | None = Form(default=None),
    closing_balance: str | None = Form(default=None),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    content = file.file.read(service.MAX_FILE_BYTES + 1)
    try:
        statement = service.create_statement(
            db,
            org_id,
            financial_account_id,
            file.filename or "archivo",
            content,
            sheet or None,
            _mapping(mapping),
            _money(closing_balance),
            user.id,
        )
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese archivo ya se importó en esta cuenta.") from error
    except (LookupError, ValueError) as error:
        db.rollback()
        raise _fail(error) from error
    return _detail(db, org_id, statement)


@router.get("")
def list_statements(
    account_id: str | None = None,
    status: str | None = Query(default=None, pattern="^(OPEN|CLOSED|CANCELLED)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    query = db.query(BankStatement).filter(BankStatement.organization_id == org_id)
    if account_id:
        query = query.filter(BankStatement.financial_account_id == account_id)
    if status:
        query = query.filter(BankStatement.status == status)
    else:
        query = query.filter(BankStatement.status != "CANCELLED")
    total = query.count()
    rows = (
        query.order_by(BankStatement.period_end.desc(), BankStatement.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": _reads(db, org_id, rows), "total": total, "limit": limit, "offset": offset}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    return service.open_alerts(db, org_id)


@router.get("/{statement_id}", response_model=StatementDetail)
def get(statement_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_current_org_id)):
    return _detail(db, org_id, _statement(db, org_id, statement_id))


@router.get("/{statement_id}/lines/{line_id}/candidates", response_model=list[TransactionBrief])
def candidates(
    statement_id: str,
    line_id: str,
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
):
    statement = _statement(db, org_id, statement_id)
    try:
        return [_brief(t) for t in service.candidates(db, statement, line_id, search)]
    except LookupError as error:
        raise _fail(error) from error


def _act(db: Session, org_id: str, statement: BankStatement, action) -> StatementDetail:
    try:
        action()
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Alguno de los movimientos ya está conciliado con otro renglón."
        ) from error
    except (LookupError, ValueError) as error:
        db.rollback()
        raise _fail(error) from error
    db.refresh(statement)
    return _detail(db, org_id, statement)


@router.post("/{statement_id}/lines/{line_id}/match", response_model=StatementDetail)
def match(
    statement_id: str,
    line_id: str,
    payload: MatchRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    return _act(
        db, org_id, statement, lambda: service.match_line(db, statement, line_id, payload.transaction_ids, user.id)
    )


@router.post("/{statement_id}/lines/{line_id}/ignore", response_model=StatementDetail)
def ignore(
    statement_id: str,
    line_id: str,
    payload: IgnoreRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    return _act(db, org_id, statement, lambda: service.ignore_line(db, statement, line_id, payload.note, user.id))


@router.post("/{statement_id}/lines/{line_id}/reset", response_model=StatementDetail)
def reset(
    statement_id: str,
    line_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    return _act(db, org_id, statement, lambda: service.reset_line(db, statement, line_id))


@router.post("/{statement_id}/auto-match")
def auto_match(
    statement_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    confirmed = {"count": 0}

    def run():
        confirmed["count"] = service.auto_match(db, statement, user.id)

    detail = _act(db, org_id, statement, run)
    return {"confirmed": confirmed["count"], "detail": detail}


@router.patch("/{statement_id}", response_model=StatementDetail)
def set_balance(
    statement_id: str,
    payload: BalanceRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)

    def run():
        service._open(statement)
        statement.closing_balance = payload.closing_balance

    return _act(db, org_id, statement, run)


@router.post("/{statement_id}/close", response_model=StatementDetail)
def close(
    statement_id: str,
    payload: CloseRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    return _act(
        db, org_id, statement, lambda: service.close_statement(db, statement, payload.closing_balance, user.id)
    )


@router.post("/{statement_id}/reopen", response_model=StatementDetail)
def reopen(
    statement_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    _membership=Depends(require_role(REOPEN_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    return _act(db, org_id, statement, lambda: service.reopen_statement(db, statement))


@router.post("/{statement_id}/cancel", response_model=StatementRead)
def cancel(
    statement_id: str,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_current_org_id),
    user: User = Depends(get_current_user),
    _membership=Depends(require_role(WRITE_ROLES)),
):
    statement = _statement(db, org_id, statement_id)
    try:
        service.cancel_statement(db, statement, user.id)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise _fail(error) from error
    db.refresh(statement)
    return _reads(db, org_id, [statement])[0]
