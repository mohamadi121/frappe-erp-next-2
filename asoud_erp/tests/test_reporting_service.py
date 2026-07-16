from decimal import Decimal

from asoud_erp.services.reporting_service import running_balance, summarize_entries


def test_summarize_entries_by_account():
    result = summarize_entries(
        [
            {"account": "Cash", "opening": 100, "debit": 50, "credit": 0},
            {"account": "Cash", "opening": 0, "debit": 0, "credit": 20},
            {"account": "Sales", "opening": 0, "debit": 0, "credit": 50},
        ]
    )
    assert result["Cash"].closing == Decimal("130")
    assert result["Sales"].closing == Decimal("-50")


def test_running_balance_is_added_to_each_entry():
    rows = running_balance(100, [{"debit": 20, "credit": 0}, {"debit": 0, "credit": 35}])
    assert rows[0]["balance"] == Decimal("120")
    assert rows[1]["balance"] == Decimal("85")
