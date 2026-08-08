import importlib
import sys
from types import ModuleType, SimpleNamespace

fake_frappe = ModuleType("frappe")
fake_frappe._ = lambda value: value
fake_frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))
sys.modules.setdefault("frappe", fake_frappe)
detail_code_service = importlib.import_module("asoud_erp.services.detail_code_service")


def test_group_code_is_the_first_detail_code(monkeypatch) -> None:
    responses = iter([[{"group_code": "1000"}], []])
    detail_code_service.frappe.db = SimpleNamespace(
        sql=lambda *args, **kwargs: next(responses)
    )

    assert detail_code_service.next_detail_code("customers", 5) == "1000"


def test_next_detail_code_increments_the_highest_group_code(monkeypatch) -> None:
    responses = iter(
        [[{"group_code": "1000"}], [["1000"], ["1002"], ["1001"]]]
    )
    detail_code_service.frappe.db = SimpleNamespace(
        sql=lambda *args, **kwargs: next(responses)
    )

    assert detail_code_service.next_detail_code("customers", 5) == "1003"
