from datetime import date

import pytest

from asoud_erp.services.personnel_file import (
    contract_state,
    days_remaining,
    document_status,
    promotion_rows,
    service_length,
    sort_history,
)

TODAY = date(2026, 9, 25)


@pytest.mark.parametrize("expiry, status", [
    (None, "no_expiry"), ("", "no_expiry"), ("2026-09-24", "expired"), ("2026-10-10", "expiring"),
    ("2026-10-25", "expiring"), ("2026-10-26", "valid"), (date(2030, 1, 1), "valid"),
])
def test_document_status(expiry, status) -> None:
    assert document_status(expiry, TODAY) == status


def test_service_length() -> None:
    assert service_length(None, TODAY) is None
    assert service_length("2020-03-21", TODAY) == {"years": 6, "months": 6, "days": 2379}
    assert service_length("2026-09-26", TODAY) == {"years": 0, "months": 0, "days": 0}
    assert service_length("2020-01-31", TODAY, until="2021-02-28")["months"] == 0
    assert service_length("2020-01-31", TODAY, until="2021-02-28")["years"] == 1


@pytest.mark.parametrize("args, state", [
    (("2026-01-01", "2026-12-31", 0, True), "draft"),
    (("2026-01-01", "2026-12-31", 2, True), "cancelled"),
    (("2026-01-01", "2026-12-31", 1, False), "unsigned"),
    (("2026-10-01", "2027-09-30", 1, True), "upcoming"),
    (("2025-01-01", "2026-09-24", 1, True), "expired"),
    (("2026-01-01", None, 1, True), "active"),
])
def test_contract_state(args, state) -> None:
    assert contract_state(*args, TODAY) == state


def test_days_remaining_and_history_order() -> None:
    assert days_remaining("2026-10-05", TODAY) == 10
    assert days_remaining(None, TODAY) is None
    events = [{"date": "2020-01-01", "kind": "joining"}, {"date": None, "kind": "x"},
              {"date": "2024-05-01", "kind": "promotion", "order": 2},
              {"date": "2024-05-01", "kind": "internal", "order": 1}]
    assert [e["kind"] for e in sort_history(events)] == ["promotion", "internal", "joining", "x"]


def test_promotion_rows() -> None:
    current = {"designation": "کارشناس", "department": "Sales - T", "branch": ""}
    rows = promotion_rows(current, {"designation": "سرپرست", "department": "Sales - T"})
    assert rows == [{"property": "Designation", "fieldname": "designation", "current": "کارشناس",
                     "new": "سرپرست"}]
    with pytest.raises(ValueError):
        promotion_rows(current, {"designation": "کارشناس"})
    with pytest.raises(ValueError):
        promotion_rows(current, {"salary": "1"})
