import pytest

from asoud_erp.services.transaction_lines import (
    MAX_LINES,
    normalize_lines,
    normalize_references,
    paging,
)


def test_lines_keep_only_requested_parts() -> None:
    raw = '[{"item_code": " ITM-1 ", "qty": "2", "rate": 150, "discount_percentage": 10,' \
          ' "warehouse": "Stores - T", "uom": "Box"}]'
    assert normalize_lines(raw) == [{"item_code": "ITM-1", "qty": 2.0, "uom": "Box"}]
    assert normalize_lines(raw, rates=True, warehouses=True) == [{
        "item_code": "ITM-1", "qty": 2.0, "uom": "Box", "rate": 150.0,
        "discount_percentage": 10.0, "warehouse": "Stores - T",
    }]


def test_missing_rate_is_left_to_erpnext_pricing() -> None:
    assert "rate" not in normalize_lines([{"item_code": "A", "qty": 1, "rate": ""}], rates=True)[0]


def test_stock_lines_keep_source_and_target_warehouses() -> None:
    line = normalize_lines([{"item_code": "A", "qty": 1, "s_warehouse": "S", "t_warehouse": "T"}],
                           target_warehouses=True)[0]
    assert (line["s_warehouse"], line["t_warehouse"]) == ("S", "T")


@pytest.mark.parametrize("items", [
    [], "not json", [{"qty": 1}], [{"item_code": "A", "qty": 0}], [{"item_code": "A", "qty": "x"}],
    [{"item_code": "A", "qty": True}], [{"item_code": "A", "qty": float("inf")}],
    [{"item_code": "A", "qty": 1}] * (MAX_LINES + 1), ["A"],
])
def test_invalid_lines_are_rejected(items) -> None:
    with pytest.raises(ValueError):
        normalize_lines(items)


@pytest.mark.parametrize("row", [{"rate": -1}, {"discount_percentage": 101}, {"discount_percentage": -5}])
def test_invalid_prices_are_rejected(row) -> None:
    with pytest.raises(ValueError):
        normalize_lines([{"item_code": "A", "qty": 1, **row}], rates=True)


def test_references_are_checked_against_party_and_amount() -> None:
    rows = normalize_references([{"reference_doctype": "Sales Invoice", "reference_name": "SINV-1",
                                  "allocated_amount": "60"},
                                 {"reference_doctype": "Sales Invoice", "reference_name": "SINV-2",
                                  "allocated_amount": 40}], "Customer", 100)
    assert [row["allocated_amount"] for row in rows] == [60.0, 40.0]
    assert normalize_references(None, "Customer", 100) == []


@pytest.mark.parametrize("references, party_type", [
    ([{"reference_doctype": "Purchase Invoice", "reference_name": "P", "allocated_amount": 1}], "Customer"),
    ([{"reference_doctype": "Sales Invoice", "reference_name": "S", "allocated_amount": 101}], "Customer"),
    ([{"reference_doctype": "Sales Invoice", "reference_name": "S", "allocated_amount": 0}], "Customer"),
    ([{"reference_doctype": "Sales Invoice", "reference_name": "S", "allocated_amount": 1}] * 2, "Customer"),
    ([{"reference_doctype": "Expense Claim", "reference_name": "", "allocated_amount": 1}], "Employee"),
])
def test_invalid_references_are_rejected(references, party_type) -> None:
    with pytest.raises(ValueError):
        normalize_references(references, party_type, 100)


def test_paging_is_bounded() -> None:
    assert paging(None, None) == (0, 20)
    assert paging("40", "500") == (40, 100)
    with pytest.raises(ValueError):
        paging(-1, 10)
