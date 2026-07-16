from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable


@dataclass(frozen=True)
class AccountBalance:
    opening: Decimal
    debit: Decimal
    credit: Decimal

    @property
    def closing(self) -> Decimal:
        return self.opening + self.debit - self.credit


def decimal_amount(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def summarize_entries(entries: Iterable[dict[str, Any]]) -> dict[str, AccountBalance]:
    balances: dict[str, AccountBalance] = {}
    for row in entries:
        account = str(row.get("account") or "").strip()
        if not account:
            continue
        current = balances.get(account, AccountBalance(Decimal(0), Decimal(0), Decimal(0)))
        balances[account] = AccountBalance(
            opening=current.opening + decimal_amount(row.get("opening")),
            debit=current.debit + decimal_amount(row.get("debit")),
            credit=current.credit + decimal_amount(row.get("credit")),
        )
    return balances


def running_balance(opening: Any, entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    balance = decimal_amount(opening)
    result = []
    for row in entries:
        balance += decimal_amount(row.get("debit")) - decimal_amount(row.get("credit"))
        result.append({**row, "balance": balance})
    return result
