from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class VoucherTotals:
    debit: Decimal
    credit: Decimal

    @property
    def balanced(self) -> bool:
        return self.debit == self.credit and self.debit > 0


def money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("1"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Amount is not valid") from exc
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    return amount


def validate_voucher_lines(lines: list[dict[str, Any]]) -> VoucherTotals:
    if len(lines) < 2:
        raise ValueError("A voucher requires at least two rows")
    debit = Decimal(0)
    credit = Decimal(0)
    for index, row in enumerate(lines, start=1):
        if not str(row.get("account") or "").strip():
            raise ValueError(f"Account is required in row {index}")
        row_debit = money(row.get("debit"))
        row_credit = money(row.get("credit"))
        if (row_debit > 0) == (row_credit > 0):
            raise ValueError(f"Row {index} must contain either debit or credit")
        debit += row_debit
        credit += row_credit
    totals = VoucherTotals(debit=debit, credit=credit)
    if not totals.balanced:
        raise ValueError("Total debit and credit must be equal and greater than zero")
    return totals
