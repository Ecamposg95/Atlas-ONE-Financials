from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TransactionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    date: date_type
    description: str
    reference: str | None = None
    transaction_type: str
    amount: Decimal  # con signo: entrada positiva, salida negativa
    status: str


class Suggestion(BaseModel):
    kind: str  # EXACT | GROUP
    transactions: list[TransactionBrief]


class LineRead(BaseModel):
    id: str
    row_number: int
    date: date_type
    description: str
    reference: str | None = None
    amount: Decimal
    status: str
    difference: Decimal | None = None
    note: str | None = None
    matches: list[TransactionBrief] = []
    suggestions: list[Suggestion] = []


class Alert(BaseModel):
    kind: str
    count: int
    amount: Decimal | None = None
    message: str


class Summary(BaseModel):
    lines_count: int
    deposits: Decimal
    withdrawals: Decimal
    pending_count: int
    matched_count: int
    ignored_count: int
    differences_count: int
    differences_total: Decimal
    ignored_total: Decimal
    book_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    in_transit_in: Decimal
    in_transit_out: Decimal
    unexplained: Decimal | None = None
    alerts: list[Alert]


class StatementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    financial_account_id: str
    account_name: str | None = None
    filename: str
    period_start: date_type
    period_end: date_type
    status: str
    closing_balance: Decimal | None = None
    closed_at: datetime | None = None
    created_at: datetime
    lines_count: int = 0
    pending_count: int = 0
    differences_count: int = 0


class StatementDetail(BaseModel):
    statement: StatementRead
    summary: Summary
    lines: list[LineRead]
    in_transit: list[TransactionBrief]


class MatchRequest(BaseModel):
    transaction_ids: list[str] = Field(min_length=1, max_length=200)


class IgnoreRequest(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class CloseRequest(BaseModel):
    closing_balance: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=14, decimal_places=2)


class BalanceRequest(BaseModel):
    closing_balance: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=14, decimal_places=2)
