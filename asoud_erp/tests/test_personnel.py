import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from asoud_erp.services.personnel_contract import PERSONAL_FIELDS, validate_record


def test_financial_fields_excluded():
    assert not {"bank_name", "iban", "account_number", "credit_limit", "opening_balance"} & PERSONAL_FIELDS


@pytest.mark.parametrize("value", [
    {"kind":"attendance", "title":"Work", "date":"2026-09-08", "start":"09:00", "end":"08:00"},
    {"kind":"evaluation", "title":"Review", "date":"2026-09-08", "score":101},
    {"kind":"photo", "title":"Photo", "date":"2026-09-08", "file":"ZmFrZQ=="},
    {"kind":"history", "title":"Event", "date":"2026-02-31"},
])
def test_invalid_record_rejected(value):
    with pytest.raises(ValueError):
        validate_record(value)


def test_valid_attendance():
    record = {"kind":"attendance", "title":"Work", "date":"2026-09-08", "start":"08:00", "end":"16:00"}
    assert validate_record(record) == record


@pytest.fixture
def api(monkeypatch):
    fake = ModuleType("frappe")
    fake.whitelist = lambda *a, **kw: lambda fn: fn
    fake.session = SimpleNamespace(user="employee@example.com")
    fake.PermissionError = PermissionError
    fake.throw = lambda msg, *args: (_ for _ in ()).throw(PermissionError(msg))
    fake.get_roles = lambda: ["Employee"]
    fake.get_list = lambda *args, **kwargs: ["office"]
    fake.db = SimpleNamespace(get_value=Mock(return_value="another@example.com"))
    fake.get_doc = Mock(return_value=SimpleNamespace(company="office", employee="EMP1", roles_text='["Employee"]'))
    monkeypatch.setitem(sys.modules, "frappe", fake)
    path = Path(__file__).parents[1] / "api" / "v1" / "personnel.py"
    spec = importlib.util.spec_from_file_location("personnel_test_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_employee_cannot_read_other_person(api):
    with pytest.raises(PermissionError):
        api._person("other")


def test_employee_reads_only_self_and_cannot_write(api):
    api.frappe.db.get_value.return_value = api.frappe.session.user
    assert api._person("self").employee == "EMP1"
    with pytest.raises(PermissionError):
        api._person("self", write=True)


def test_hr_manager_denied_other_company(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    api.frappe.get_list = lambda *args, **kwargs: []
    with pytest.raises(PermissionError):
        api._person("other", write=True)


def test_hr_manager_can_edit_authorized_company(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    assert api._person("allowed", write=True).company == "office"


def test_hr_update_rejects_financial_payload(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    with pytest.raises(PermissionError, match="HR profile fields"):
        api.update_personnel("allowed", {"iban":"123"}, "revision")


def test_update_retry_uses_original_request_without_second_write(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    values = {"display_name": "Updated"}
    fingerprint = json.dumps({"values": values, "revision": "old"}, sort_keys=True, ensure_ascii=False)
    api.frappe.db.get_value.return_value = SimpleNamespace(
        party="allowed", payload=json.dumps({"_update": fingerprint}))
    api.get_personnel = Mock(return_value={"ok": True})
    assert api.update_personnel("allowed", values, "old", "request-123") == {"ok": True}
    api.get_personnel.assert_called_once_with("allowed")


def test_update_retry_rejects_different_payload(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    api.frappe.db.get_value.return_value = SimpleNamespace(party="allowed", payload='{}')
    with pytest.raises(PermissionError, match="Request ID conflict"):
        api.update_personnel("allowed", {"display_name": "Changed"}, "old", "request-123")


@pytest.fixture
def record_api(api):
    api.frappe.get_roles = lambda: ["HR Manager"]
    api._person = Mock(return_value=SimpleNamespace(company="office"))
    api.frappe.TimestampMismatchError = RuntimeError
    api.frappe.db.sql = Mock()
    api.frappe.db.get_value = Mock(return_value=None)
    doc = SimpleNamespace(name="record-1", party="allowed", company="office", kind="evaluation",
                          modified="1", payload=json.dumps({"kind": "evaluation", "title": "Review", "date": "2026-09-12", "score": 70}))
    doc.save = Mock(side_effect=lambda **kw: setattr(doc, "modified", "2"))
    audits = []

    def get_doc(*args):
        if isinstance(args[0], dict):
            audits.append(args[0])
            return SimpleNamespace(insert=Mock())
        return doc

    api.frappe.get_doc = get_doc
    return api, doc, audits


def test_record_edit_updates_original_and_retry_does_not_duplicate_audit(record_api):
    api, doc, audits = record_api
    payload = {"kind": "evaluation", "title": "Updated review", "date": "2026-09-12", "score": 90}
    response = api.update_record("allowed", "record-1", payload, "1", "edit-request-1")
    assert response["data"]["score"] == 90
    assert response["data"]["_revision"] == "2"
    assert response["data"]["_can_edit"] is True
    assert len(audits) == 1
    assert doc.title == "Updated review"
    api.frappe.db.get_value.return_value = SimpleNamespace(party="allowed", payload=audits[0]["payload"])
    api.update_record("allowed", "record-1", payload, "1", "edit-request-1")
    assert len(audits) == 1
    assert doc.save.call_count == 1
    with pytest.raises(PermissionError, match="Request ID conflict"):
        api.update_record("allowed", "record-1", {**payload, "score": 80}, "1", "edit-request-1")


def test_record_edit_rejects_stale_revision_wrong_person_and_kind(record_api):
    api, doc, _ = record_api
    payload = {"kind": "evaluation", "title": "Review", "date": "2026-09-12", "score": 90}
    with pytest.raises(PermissionError, match="Record changed"):
        api.update_record("allowed", "record-1", payload, "stale", "edit-request-1")
    doc.party = "another"
    with pytest.raises(PermissionError, match="does not belong"):
        api.update_record("allowed", "record-1", payload, "1", "edit-request-1")
    doc.party = "allowed"
    with pytest.raises(PermissionError, match="kind cannot"):
        api.update_record("allowed", "record-1", {**payload, "kind": "history"}, "1", "edit-request-1")
    doc.save.assert_not_called()


def test_system_history_cannot_be_edited_or_expose_private_receipt(record_api):
    api, doc, _ = record_api
    doc.kind = "history"
    doc.payload = json.dumps({"kind": "history", "title": "Audit", "date": "2026-09-12", "_record_update": "private-receipt"})
    value = api.get_record(doc.name)["data"]
    assert value["_can_edit"] is False
    assert "_record_update" not in value
    with pytest.raises(PermissionError, match="Automatic history"):
        api.update_record("allowed", doc.name, {"kind": "history", "title": "Changed", "date": "2026-09-12"}, "1", "edit-request-1")
    doc.save.assert_not_called()
