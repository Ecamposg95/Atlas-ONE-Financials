"""Propiedad del libro: pase lo que pase, la contabilidad cuadra.

En vez de un caso a mano, se generan secuencias al azar (con semilla fija, así
un fallo se reproduce) de ventas, gastos, cuentas por cobrar y por pagar con
cobros y pagos parciales, y cancelaciones. Después de CADA operación:

1. cada póliza cuadra por sí sola y la balanza cuadra;
2. el auxiliar coincide con el mayor: lo abierto por cobrar es el saldo de 1200
   y lo abierto por pagar es el de 2100;
3. el saldo de la caja coincide con el de su cuenta contable (1100).
"""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.models.accounting import JournalEntry, JournalEntryLine
from tests.helpers import auth_headers, register

ZERO = Decimal("0")
STEPS = 40


def _money(rng: random.Random, low: int, high: int) -> str:
    return f"{Decimal(rng.randint(low * 100, high * 100)) / 100:.2f}"


class _World:
    def __init__(self, client, db, rng):
        self.client, self.db, self.rng = client, db, rng
        body = register(client, initial_cash="50000")
        self.org_id = body["organization"]["id"]
        self.headers = auth_headers(body)
        self.account = client.get("/api/accounts", headers=self.headers).json()[0]
        income = client.get("/api/categories?kind=INCOME", headers=self.headers).json()
        expense = client.get("/api/categories?kind=EXPENSE", headers=self.headers).json()
        self.ventas = next(c for c in income if c["name"] == "Ventas")
        self.renta = next(c for c in expense if c["name"] == "Renta")
        self.customer = self._post("/api/customers", {"name": "Cliente"}, 201)
        self.vendor = self._post("/api/vendors", {"name": "Proveedor"}, 201)
        self.incomes: list[str] = []
        self.expenses: list[str] = []
        self.receivables: dict[str, Decimal] = {}  # id → saldo abierto
        self.payables: dict[str, Decimal] = {}

    def _post(self, path, payload, expected):
        response = self.client.post(path, headers=self.headers, json=payload)
        assert response.status_code == expected, f"{path}: {response.status_code} {response.text}"
        return response.json()

    def cash(self) -> Decimal:
        account = self.client.get(f"/api/accounts/{self.account['id']}", headers=self.headers).json()
        return Decimal(account["current_balance"])

    # --- operaciones -------------------------------------------------------
    def income(self):
        created = self._post(
            "/api/income",
            {
                "date": date.today().isoformat(),
                "description": "Venta",
                "amount": _money(self.rng, 10, 5000),
                "category_id": self.ventas["id"],
                "financial_account_id": self.account["id"],
                "status": "PAID",
            },
            201,
        )
        self.incomes.append(created["id"])

    def expense(self):
        amount = Decimal(_money(self.rng, 10, 3000))
        if amount > self.cash():
            return
        created = self._post(
            "/api/expenses",
            {
                "date": date.today().isoformat(),
                "description": "Gasto",
                "amount": str(amount),
                "category_id": self.renta["id"],
                "financial_account_id": self.account["id"],
                "status": "PAID",
            },
            201,
        )
        self.expenses.append(created["id"])

    def receivable(self):
        amount = _money(self.rng, 100, 8000)
        created = self._post(
            "/api/receivables",
            {
                "customer_id": self.customer["id"],
                "description": "Factura a crédito",
                "amount": amount,
                "due_date": "2027-01-31",
                "category_id": self.ventas["id"],
            },
            201,
        )
        self.receivables[created["id"]] = Decimal(created["balance"])

    def collect(self):
        open_ids = [key for key, balance in self.receivables.items() if balance > ZERO]
        if not open_ids:
            return
        target = self.rng.choice(open_ids)
        balance = self.receivables[target]
        amount = balance if self.rng.random() < 0.4 else (balance * Decimal(self.rng.randint(1, 99)) / 100).quantize(Decimal("0.01"))
        if amount <= ZERO:
            return
        updated = self._post(
            f"/api/receivables/{target}/collect",
            {"amount": str(amount), "financial_account_id": self.account["id"]},
            200,
        )
        self.receivables[target] = Decimal(updated["balance"])

    def payable(self):
        created = self._post(
            "/api/payables",
            {
                "vendor_id": self.vendor["id"],
                "description": "Factura de proveedor",
                "amount": _money(self.rng, 100, 6000),
                "due_date": "2027-01-31",
                "category_id": self.renta["id"],
            },
            201,
        )
        self.payables[created["id"]] = Decimal(created["balance"])

    def pay(self):
        open_ids = [key for key, balance in self.payables.items() if balance > ZERO]
        if not open_ids:
            return
        target = self.rng.choice(open_ids)
        balance = self.payables[target]
        amount = balance if self.rng.random() < 0.4 else (balance * Decimal(self.rng.randint(1, 99)) / 100).quantize(Decimal("0.01"))
        if amount <= ZERO or amount > self.cash():
            return
        updated = self._post(
            f"/api/payables/{target}/pay",
            {"amount": str(amount), "financial_account_id": self.account["id"]},
            200,
        )
        self.payables[target] = Decimal(updated["balance"])

    def cancel(self):
        """Cancela algo al azar. Un rechazo (p. ej. dejaría la caja en negativo)
        es válido: lo que no puede pasar es que el libro quede descuadrado."""
        pools = {
            "income": self.incomes,
            "expenses": self.expenses,
            "receivables": list(self.receivables),
            "payables": list(self.payables),
        }
        kind = self.rng.choice([name for name, pool in pools.items() if pool] or [None])
        if kind is None:
            return
        target = self.rng.choice(pools[kind])
        response = self.client.post(f"/api/{kind}/{target}/cancel", headers=self.headers, json={"reason": "Captura duplicada"})
        assert response.status_code < 500, response.text
        if response.status_code >= 400:
            return
        if kind == "income":
            self.incomes.remove(target)
        elif kind == "expenses":
            self.expenses.remove(target)
        elif kind == "receivables":
            del self.receivables[target]
        else:
            del self.payables[target]

    # --- lo que siempre debe ser cierto ------------------------------------
    def check(self, step: str):
        unbalanced = (
            self.db.query(JournalEntry.folio)
            .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.id)
            .filter(JournalEntry.organization_id == self.org_id)
            .group_by(JournalEntry.id, JournalEntry.folio)
            .having(func.sum(JournalEntryLine.debit) != func.sum(JournalEntryLine.credit))
            .all()
        )
        assert unbalanced == [], f"{step}: pólizas descuadradas {unbalanced}"

        report = self.client.get("/api/accounting/trial-balance", headers=self.headers).json()
        assert Decimal(str(report["total_debit"])) == Decimal(str(report["total_credit"])), step
        balances = {row["code"]: Decimal(str(row["balance"])) for row in report["rows"]}

        assert balances.get("1200", ZERO) == sum(self.receivables.values(), ZERO), f"{step}: CxC ≠ 1200"
        assert balances.get("2100", ZERO) == sum(self.payables.values(), ZERO), f"{step}: CxP ≠ 2100"
        assert balances.get("1100", ZERO) == self.cash(), f"{step}: caja ≠ 1100"


@pytest.mark.parametrize("seed", [1, 7, 42, 2026, 90210])
def test_cualquier_secuencia_deja_el_libro_cuadrado(client, db, seed):
    rng = random.Random(seed)
    world = _World(client, db, rng)
    world.check("inicio")
    operations = [
        world.income,
        world.expense,
        world.receivable,
        world.collect,
        world.collect,
        world.payable,
        world.pay,
        world.pay,
        world.cancel,
    ]
    for index in range(STEPS):
        operation = rng.choice(operations)
        operation()
        world.check(f"semilla {seed}, paso {index} ({operation.__name__})")
