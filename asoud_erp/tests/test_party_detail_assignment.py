import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock


def test_explicit_group_does_not_allocate_role_default_codes(monkeypatch):
    fake = ModuleType("frappe")
    fake._ = lambda text: text
    fake.whitelist = lambda *args, **kwargs: lambda fn: fn
    fake.get_single = lambda name: SimpleNamespace(detail_code_digits=5)
    fake.db = SimpleNamespace(
        exists=lambda doctype, filters: doctype == "ASOUD Detail Group",
        get_value=Mock(return_value="unrelated-default"),
        set_value=Mock(),
    )
    fake.get_doc = Mock(return_value=SimpleNamespace(insert=Mock()))
    monkeypatch.setitem(sys.modules, "frappe", fake)
    path = Path(__file__).parents[1] / "api" / "v1" / "party.py"
    spec = importlib.util.spec_from_file_location("party_assignment_test_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    allocate = Mock(return_value="01000")
    monkeypatch.setattr(module, "next_detail_code", allocate)

    module._sync_floating_details(
        "person", "Person", ["Customer", "Supplier", "Employee"],
        primary_role="Customer", detail_groups=["people"],
    )

    allocate.assert_called_once_with("people", 5)
    fake.db.get_value.assert_not_called()
    payload = fake.get_doc.call_args.args[0]
    assert payload["detail_code"] == "01000"
    assert payload["detail_group"] == "people"

    # Editing the same profile updates the title without consuming a code.
    fake.db.exists = lambda doctype, filters: (
        "existing-detail" if doctype == "ASOUD Floating Detail" else True
    )
    allocate.reset_mock()
    module._sync_floating_details(
        "person", "Renamed", ["Customer", "Employee"],
        primary_role="Customer", detail_groups=["people"],
    )
    allocate.assert_not_called()
    fake.db.set_value.assert_called_once_with(
        "ASOUD Floating Detail", "existing-detail", "title", "Renamed"
    )
