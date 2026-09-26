import importlib.util
import json
import sys
from datetime import datetime
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
    utils = ModuleType("frappe.utils")
    utils.get_datetime = lambda value: datetime.fromisoformat(str(value))
    utils.strip_html = lambda value: value
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    fake.db = SimpleNamespace(get_value=Mock(return_value="another@example.com"))
    fake.get_doc = Mock(return_value=SimpleNamespace(company="office", employee="EMP1", roles_text='["Employee"]'))
    monkeypatch.setitem(sys.modules, "frappe", fake)
    path = Path(__file__).parents[1] / "api" / "v1" / "personnel.py"
    spec = importlib.util.spec_from_file_location("personnel_test_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for service in ("personnel_employee", "personnel_native"):
        key = "asoud_erp.services." + service
        service_spec = importlib.util.spec_from_file_location(key, Path(__file__).parents[1] / "services" / (service + ".py"))
        loaded = importlib.util.module_from_spec(service_spec)
        monkeypatch.setitem(sys.modules, key, loaded)
        service_spec.loader.exec_module(loaded)
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
    api._person = Mock(return_value=SimpleNamespace(name="allowed", company="office"))
    api.frappe.TimestampMismatchError = RuntimeError
    api.frappe.db.sql = Mock()
    api.frappe.db.get_value = Mock(return_value=None)
    doc = SimpleNamespace(name="record-1", party="allowed", company="office", kind="evaluation",
                          modified="1", payload=json.dumps({"kind": "evaluation", "title": "Review", "date": "2026-09-12", "score": 70}))
    doc.get = lambda key: getattr(doc, key, None)
    doc.save = Mock(side_effect=lambda **kw: setattr(doc, "modified", "2"))
    audits = []

    def get_doc(*args, **kwargs):
        if isinstance(args[0], dict):
            audits.append(args[0])
            return SimpleNamespace(insert=Mock())
        return doc

    api.frappe.get_doc = get_doc
    return api, doc, audits


def test_legacy_record_is_read_only_and_preserved(record_api):
    api, doc, audits = record_api
    original = doc.payload
    result = api.get_record(doc.name)["data"]
    assert result["score"] == 70
    assert result["_legacy"] is True
    assert result["_can_edit"] is False
    with pytest.raises(PermissionError, match="Legacy records"):
        api.update_record("allowed", doc.name, json.loads(original), "1", "edit-request-1")
    assert doc.payload == original
    assert audits == []
    doc.save.assert_not_called()


def test_record_edit_rejects_wrong_person_and_kind(record_api):
    api, doc, _ = record_api
    payload = {"kind": "evaluation", "title": "Review", "date": "2026-09-12", "score": 90}
    doc.party = "another"
    with pytest.raises(PermissionError, match="does not belong"):
        api.update_record("allowed", "record-1", payload, "1", "edit-request-1")
    doc.party = "allowed"
    with pytest.raises(PermissionError, match="kind cannot"):
        api.update_record("allowed", "record-1", {**payload, "kind": "history"}, "1", "edit-request-1")
    doc.save.assert_not_called()


def test_system_history_does_not_expose_private_receipt(record_api):
    api, doc, _ = record_api
    doc.kind = "history"
    doc.payload = json.dumps({"kind": "history", "title": "Audit", "date": "2026-09-12", "_record_update": "private-receipt"})
    value = api.get_record(doc.name)["data"]
    assert value["_can_edit"] is False
    assert "_record_update" not in value


def test_evaluation_context_is_kept_by_contract():
    data = {"kind": "evaluation", "title": "Review", "date": "2026-09-12", "score": 80,
            "appraisal_cycle": "Annual"}
    assert validate_record(data)["appraisal_cycle"] == "Annual"


def test_native_revision_detects_external_changes(api):
    native = sys.modules["asoud_erp.services.personnel_native"]
    link = SimpleNamespace(modified="1")
    checkin = SimpleNamespace(doctype="Employee Checkin", name="IN-1", modified="1")
    before = native.revision(link, [checkin])
    checkin.modified = "2"
    assert native.revision(link, [checkin]) != before


def test_native_record_cannot_point_to_another_employee(api):
    native = sys.modules["asoud_erp.services.personnel_native"]
    native.employee_for = Mock(return_value=SimpleNamespace(name="EMP1", company="office"))
    api.frappe.get_doc = Mock(return_value=SimpleNamespace(doctype="Appraisal", employee="EMP2", company="office"))
    with pytest.raises(PermissionError, match="does not belong"):
        native.native_documents(SimpleNamespace(kind="evaluation", native_doctype="Appraisal", native_name="A1"), object())


def test_shared_fields_prefer_employee_even_when_empty(api):
    service = sys.modules["asoud_erp.services.personnel_employee"]
    employee = SimpleNamespace(status="Active", meta=SimpleNamespace(has_field=lambda key: True))
    employee.get = lambda key: {"employee_name": "ERP name", "cell_number": ""}.get(key)
    service.employee_for = Mock(return_value=employee)
    person = {"employee": "EMP1", "display_name": "old", "mobile": "old number"}
    assert service.shared_values(person)["disabled"] is False
    assert service.shared_values(person)["display_name"] == "ERP name"
    assert service.shared_values(person)["mobile"] == ""


def test_document_metadata_is_validated_and_kept():
    pdf = __import__("base64").b64encode(b"%PDF-1.4 test").decode()
    record = {"kind": "document", "title": "کارت ملی", "date": "2020-01-01", "file": pdf,
              "document_category": "Identity", "document_number": "0012345678", "expiry_date": "2030-01-01"}
    assert validate_record(record)["document_category"] == "Identity"
    for change in ({"document_category": "Secret"}, {"expiry_date": "2019-12-31"},
                   {"document_number": "x" * 141}):
        with pytest.raises(ValueError):
            validate_record({**record, **change})
