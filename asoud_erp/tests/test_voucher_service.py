import pytest

from asoud_erp.services.voucher_service import validate_voucher_lines


def test_balanced_voucher_is_valid():
    totals = validate_voucher_lines(
        [
            {"account": "Cash", "debit": 1_000_000, "credit": 0},
            {"account": "Sales", "debit": 0, "credit": 1_000_000},
        ]
    )
    assert totals.balanced
    assert totals.debit == totals.credit


@pytest.mark.parametrize(
    "lines",
    [
        [{"account": "Cash", "debit": 1, "credit": 0}],
        [
            {"account": "Cash", "debit": 100, "credit": 0},
            {"account": "Sales", "debit": 0, "credit": 90},
        ],
        [
            {"account": "Cash", "debit": 100, "credit": 20},
            {"account": "Sales", "debit": 0, "credit": 80},
        ],
    ],
)
def test_invalid_voucher_is_rejected(lines):
    with pytest.raises(ValueError):
        validate_voucher_lines(lines)
