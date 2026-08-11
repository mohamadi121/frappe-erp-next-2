import pytest

from asoud_erp.services.purchase_request import normalize_purchase_items


def test_purchase_items_are_normalized():
    result = normalize_purchase_items(
        [{"item_code": "ITEM-1", "qty": "2", "uom": "عدد", "warehouse": "انبار اصلی"}]
    )
    assert result[0]["item_code"] == "ITEM-1"
    assert result[0]["qty"] == 2


@pytest.mark.parametrize(
    "items",
    [[], [{"item_code": "", "qty": 1}], [{"item_code": "ITEM-1", "qty": 0}]],
)
def test_invalid_purchase_items_are_rejected(items):
    with pytest.raises(ValueError):
        normalize_purchase_items(items)
