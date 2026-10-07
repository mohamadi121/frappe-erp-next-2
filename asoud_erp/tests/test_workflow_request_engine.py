"""Engine helpers and the list endpoint of `workflow_request`, against a stubbed frappe.

These run without a site. They check the logic of the request engine (locked defaults,
engine rules, default resolution, list filters and shape); the real database behavior
is covered by `integration_tests/test_request_*.py`.
"""

import importlib
import json
import sys
import types
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from asoud_erp.tests._fake_site import isolate

RELOADED = [
    "asoud_erp.api.v1.workflow_request", "asoud_erp.services.request_comments",
    "asoud_erp.services.request_link_values", "asoud_erp.services.request_access",
    "asoud_erp.services.erp_documents",
]


class _Error(Exception):
    def __init__(self, message="", title=None):
        super().__init__(message)
        self.title = title


class _ValidationError(_Error):
    pass


class _PermissionError(_Error):
    pass


class _Dict(dict):
    """frappe._dict: attribute access, missing keys read as None."""

    __getattr__ = dict.get


class _FakeDB:
    def __init__(self):
        self.values = {}

    def get_value(self, doctype, name, fields=None, as_dict=False, **kwargs):
        row = self.values.get((doctype, name if isinstance(name, str) else json.dumps(name, sort_keys=True)))
        if row is None:
            return None
        if isinstance(fields, str):
            return row.get(fields)
        return types.SimpleNamespace(**{field: row.get(field) for field in fields}) if not as_dict else {
            field: row.get(field) for field in fields}


@pytest.fixture
def engine(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.ValidationError, frappe.PermissionError = _ValidationError, _PermissionError
    frappe.DoesNotExistError = type("DoesNotExistError", (_Error,), {})
    frappe._ = lambda text: text
    frappe._dict = _Dict
    frappe.whitelist = lambda **kwargs: (lambda function: function)
    frappe.flags = {}
    frappe.session = types.SimpleNamespace(user="sara@example.com")
    frappe.db = _FakeDB()
    frappe.get_roles = lambda *args: ["Employee"]
    frappe.get_meta = lambda doctype: types.SimpleNamespace(has_field=lambda name: True)
    frappe.get_doc = MagicMock(side_effect=AssertionError("get_doc must not be used per row"))

    def throw(message, exc=None, title=None):
        raise (exc or _ValidationError)(message, title=title)

    frappe.throw = throw
    frappe.get_all = MagicMock(return_value=[])
    utils = types.ModuleType("frappe.utils")
    utils.get_fullname = lambda user: f"Full {user}"
    utils.getdate = lambda value=None: value if isinstance(value, date) else date.fromisoformat(str(value))
    utils.now_datetime = lambda: "now"
    utils.nowdate = lambda: date.today().isoformat()
    utils.flt = float
    frappe.utils = utils
    runtime = types.ModuleType("asoud_erp.api.v1.workflow_runtime")
    runtime._next_stage = MagicMock()
    runtime.start_workflow_instance = MagicMock()
    for name, module in {"frappe": frappe, "frappe.utils": utils,
                         "asoud_erp.api.v1.workflow_runtime": runtime}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = isolate(RELOADED)
    module = importlib.import_module("asoud_erp.api.v1.workflow_request")
    yield module, frappe
    restore()


def test_the_requester_field_is_the_session_user(engine):
    module, _frappe = engine
    fields = [{"key": "requester", "default_source": "session_user", "editable": False}, {"key": "reason"}]
    assert module._apply_locked_defaults(fields, {"reason": "x"}, "sara@example.com") == {
        "reason": "x", "requester": "sara@example.com"}
    assert module._apply_locked_defaults(fields, {"requester": "sara@example.com"}, "sara@example.com")
    with pytest.raises(_ValidationError) as error:
        module._apply_locked_defaults(fields, {"requester": "other@example.com"}, "sara@example.com")
    assert error.value.title == "REQUESTER_MISMATCH"
    editable = [{"key": "requester", "default_source": "session_user"}]
    assert module._apply_locked_defaults(editable, {"requester": "other@example.com"}, "sara@example.com")


def test_cost_center_and_past_date_rules(engine):
    module, frappe = engine
    frappe.db.values[("Company", "WP")] = {"asoud_request_cost_center_required": 1, "asoud_daily_working_hours": 7.5}
    fields = [{"key": "cost_center", "required_by_setting": "request_cost_center_required"},
              {"key": "needed_date", "min_date": "today"}]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    module._engine_checks(fields, {"cost_center": "Main - WP", "needed_date": tomorrow}, "WP", None)
    with pytest.raises(_ValidationError) as error:
        module._engine_checks(fields, {"cost_center": None, "needed_date": tomorrow}, "WP", None)
    assert error.value.title == "COST_CENTER_REQUIRED"
    with pytest.raises(_ValidationError) as error:
        module._engine_checks(fields, {"cost_center": "Main - WP", "needed_date": yesterday}, "WP", None)
    assert error.value.title == "DATE_IN_PAST"
    # On update only a changed date is checked.
    module._engine_checks(fields, {"cost_center": "Main - WP", "needed_date": yesterday}, "WP",
                          {"needed_date": yesterday})
    with pytest.raises(_ValidationError):
        module._engine_checks(fields, {"cost_center": "Main - WP", "needed_date": yesterday}, "WP",
                              {"needed_date": tomorrow})
    frappe.db.values[("Company", "WP")]["asoud_request_cost_center_required"] = 0
    module._engine_checks(fields, {"cost_center": None, "needed_date": None}, "WP", None)
    assert module.company_settings("WP") == {"cost_center_required": False, "daily_working_hours": 7.5}


def test_company_settings_default_when_unset(engine):
    module, frappe = engine
    frappe.db.values[("Company", "WP")] = {"asoud_request_cost_center_required": None,
                                           "asoud_daily_working_hours": None}
    assert module.company_settings("WP") == {"cost_center_required": False, "daily_working_hours": 8.0}


def test_defaults_and_required_are_resolved_for_the_user(engine):
    module, frappe = engine
    frappe.db.values[("Department", "ICU - WP")] = {"department_name": "ICU"}
    employee = types.SimpleNamespace(employee_name="سارا محمدی", department="ICU - WP", branch="Tehran")
    fields = [
        {"key": "requester", "type": "User", "default_source": "session_user", "editable": False},
        {"key": "org_unit", "type": "Department", "default_source": "employee_department"},
        {"key": "location", "type": "System Select", "default_source": "employee_branch"},
        {"key": "day", "type": "Date", "default_source": "today"},
        {"key": "priority", "type": "Choice", "default_value": "Normal"},
        {"key": "cost_center", "type": "System Select", "required_by_setting": "request_cost_center_required"},
    ]
    settings = {"cost_center_required": True, "daily_working_hours": 8.0}
    result = {f["key"]: f for f in module._resolve_form_fields(
        fields, "WP", "sara@example.com", employee, None, settings)}
    assert result["requester"]["default_value"] == "sara@example.com"
    assert result["requester"]["default_label"] == "سارا محمدی"
    assert "default_source" not in result["requester"] and "default_source" not in result["org_unit"]
    assert (result["org_unit"]["default_value"], result["org_unit"]["default_label"]) == ("ICU - WP", "ICU")
    assert (result["location"]["default_value"], result["location"]["default_label"]) == ("Tehran", "Tehran")
    assert result["day"]["default_value"] == date.today().isoformat() and "default_label" not in result["day"]
    assert result["priority"]["default_value"] == "Normal"
    assert result["cost_center"]["required"] is True
    assert fields[0]["default_source"] == "session_user"  # the stored definition is not modified
    without_employee = {f["key"]: f for f in module._resolve_form_fields(
        fields, "WP", "sara@example.com", None, None, {**settings, "cost_center_required": False})}
    assert without_employee["requester"]["default_label"] == "Full sara@example.com"
    assert "default_value" not in without_employee["org_unit"]
    assert without_employee["cost_center"]["required"] is False


def test_a_spec_default_overrides_the_builtin_one(engine):
    module, _frappe = engine
    spec = types.SimpleNamespace(resolve_defaults=lambda company, user: {
        "org_unit": {"value": "Ops - WP", "label": "عملیات"}})
    fields = [{"key": "org_unit", "type": "Department", "default_source": "employee_department"}]
    result = module._resolve_form_fields(fields, "WP", "u", None, spec, {"cost_center_required": False})
    assert (result[0]["default_value"], result[0]["default_label"]) == ("Ops - WP", "عملیات")


def test_generated_subject_and_derived_header_ignore_the_client(engine):
    module, _frappe = engine
    spec = types.SimpleNamespace(
        subject_mode="generated", build_subject=lambda values: "مرخصی سالانه (روزانه)",
        denormalize=lambda values: {"priority": "Normal", "required_by": "2026-10-10", "project": "",
                                    "department": "ICU - WP"})
    header = module._header(spec, {}, "client subject", "Urgent", "2000-01-01", "X", "Y")
    assert header == {"subject": "مرخصی سالانه (روزانه)", "priority": "Normal", "required_by": "2026-10-10",
                      "project": "", "department": "ICU - WP"}
    spec.subject_mode = "input"
    assert module._header(spec, {}, " عنوان ", "Urgent", None, "", "")["subject"] == "عنوان"
    custom = module._header(None, {}, " عنوان ", "Urgent", "2030-01-01", " P ", " D ")
    assert custom == {"subject": "عنوان", "priority": "Urgent", "required_by": "2030-01-01", "project": "P",
                      "department": "D"}


def test_like_escapes_wildcards(engine):
    module, _frappe = engine
    assert module._like("50%_off") == "%50\\%\\_off%"
    assert module._like("PR-1405") == "%PR-1405%"


def _row(name, status_key, **extra):
    return {"name": name, "company": "WP", "workflow_definition": "SYS-PURCHASE-WP", "request_type": "خرید",
            "subject": "خرید تجهیزات", "priority": "High", "required_by": date(2026, 10, 20), "project": "",
            "department": "ICU - WP", "workflow_instance": f"WFI-{name}", "status": "Submitted",
            "display_status": "", "request_id": f"request-{name}", "owner": "sara@example.com",
            "creation": "2026-10-04 10:15:00", "template_key": "", "status_key": status_key,
            "values_json": json.dumps({"org_unit": "ICU - WP", "needed_date": "2026-10-20", "items": [
                {"item_code": "A", "qty": 1}, {"item_code": "B", "qty": 2}]}),
            "attachments_json": json.dumps([{"name": "f1"}]), "native_status": "", **extra}


def _all(frappe, rows):
    """A get_all that answers the list queries from canned rows."""
    calls = []

    def get_all(doctype, **kwargs):
        calls.append((doctype, kwargs))
        if doctype == "ASOUD Workflow Request" and kwargs.get("group_by"):
            return [_Dict(status_key="submitted", total=2), _Dict(status_key="approved", total=1),
                    _Dict(status_key="rejected", total=1), _Dict(status_key="cancelled", total=3)]
        if doctype == "ASOUD Workflow Request":
            return [_Dict(row) for row in rows]
        if doctype == "ASOUD Workflow Instance":
            return [_Dict(name="WFI-PR-1", status="Running"), _Dict(name="WFI-PR-2", status="Rejected")]
        if doctype == "Employee":
            return [_Dict(user_id="sara@example.com", employee_name="سارا محمدی")]
        if doctype == "Department":
            return [_Dict(name="ICU - WP", department_name="ICU")]
        if doctype == "ASOUD Workflow Task":
            return [_Dict(workflow_instance="WFI-PR-2", comment="بودجه کافی نیست"),
                    _Dict(workflow_instance="WFI-PR-2", comment="older")]
        return []

    frappe.get_all = get_all
    return calls


def test_list_returns_cards_counts_and_no_per_row_get_doc(engine, monkeypatch):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    calls = _all(frappe, [_row("PR-1", "submitted"), _row("PR-2", "rejected")])
    response = module.list_my_requests(company="WP", template_key="purchase", status_group="pending",
                                       search="ICU", priority="High", date_from="2026-10-01",
                                       date_to="2026-10-31", limit_start=0, limit_page_length=20)
    assert response["meta"] == {"api_version": "v1", "total": 2, "limit_start": 0, "limit_page_length": 20,
                                "counts": {"all": 7, "pending": 2, "approved": 1, "rejected": 1}}
    first, second = response["data"]
    assert first["number"] == first["name"] == "PR-1" and first["requester_name"] == "سارا محمدی"
    assert (first["status"], first["status_key"], first["status_label"], first["status_group"]) == (
        "Running", "submitted", "ارسال شده", "pending")
    assert (second["status"], second["status_key"], second["status_group"]) == ("Rejected", "rejected", "rejected")
    assert first["item_count"] == 2 and first["attachment_count"] == 1
    assert first["required_by"] == "2026-10-20"
    assert first["summary"]["org_unit_label"] == "ICU" and first["summary"]["priority_label"] == "مهم"
    assert second["summary"]["rejection_reason"] == "بودجه کافی نیست" and first["summary"]["rejection_reason"] == ""
    # Old keys stay, values and attachments are not in list rows.
    for key in ("name", "company", "workflow_definition", "request_type", "subject", "priority", "required_by",
                "project", "department", "workflow_instance", "status", "request_id", "display_status", "owner",
                "requester_name", "creation"):
        assert key in first
    assert "values" not in first and "attachments" not in first
    frappe.get_doc.assert_not_called()
    page = next(kwargs for doctype, kwargs in calls
                if doctype == "ASOUD Workflow Request" and not kwargs.get("group_by"))
    counts_query = next(kwargs for doctype, kwargs in calls
                        if doctype == "ASOUD Workflow Request" and kwargs.get("group_by"))
    base = [["owner", "=", "sara@example.com"], ["company", "=", "WP"], ["template_key", "=", "purchase"],
            ["priority", "=", "High"], ["search_text", "like", "%ICU%"],
            ["creation", ">=", "2026-10-01 00:00:00"], ["creation", "<=", "2026-10-31 23:59:59"]]
    assert counts_query["filters"] == base  # counts ignore the status group
    assert page["filters"] == base + [["status_key", "in", ["submitted", "in_review", "returned", "failed"]]]
    assert page["order_by"] == "creation desc, name desc"
    assert (page["limit_start"], page["limit_page_length"]) == (0, 20)
    assert sum(1 for doctype, _ in calls if doctype == "ASOUD Workflow Request") == 2


def test_list_all_total_and_page_clamp(engine, monkeypatch):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    calls = _all(frappe, [])
    response = module.list_my_requests(limit_start="40", limit_page_length=500)
    assert response["meta"]["total"] == 7 and response["data"] == []
    assert (response["meta"]["limit_start"], response["meta"]["limit_page_length"]) == (40, 100)
    page = next(kwargs for doctype, kwargs in calls
                if doctype == "ASOUD Workflow Request" and not kwargs.get("group_by"))
    assert page["filters"] == [["owner", "=", "sara@example.com"]]
    assert module.list_my_requests(status_group="approved")["meta"]["total"] == 1


@pytest.mark.parametrize("kwargs", [{"status_group": "done"}, {"priority": "Whenever"}, {"limit_page_length": "x"}])
def test_list_rejects_bad_arguments(engine, monkeypatch, kwargs):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    _all(frappe, [])
    with pytest.raises(_ValidationError):
        module.list_my_requests(**kwargs)


def test_list_requires_company_access(engine):
    module, frappe = engine
    _all(frappe, [])
    with pytest.raises(_PermissionError):
        module.list_my_requests(company=None)


def test_a_spec_summary_is_used_and_a_broken_one_falls_back(engine, monkeypatch):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    seen = {}

    def summarize(values, request_row):
        seen.update(request_row)
        return {"leave_type": "Casual Leave"}

    spec = types.SimpleNamespace(summarize=summarize)
    monkeypatch.setattr(module.templates, "get", lambda key: spec if key == "leave" else None)
    _all(frappe, [_row("LV-1", "approved", template_key="leave")])
    data = module.list_my_requests()["data"][0]
    assert data["summary"]["leave_type"] == "Casual Leave" and data["template_key"] == "leave"
    assert seen["rejection_reason"] == "" and "department" in seen["_labels"]
    spec.summarize = lambda values, request_row: {}["missing"]
    assert module.list_my_requests()["data"][0]["summary"]["org_unit"] == "ICU - WP"


def test_status_label_prefers_the_custom_status_of_a_running_request(engine, monkeypatch):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    _all(frappe, [_row("PR-1", "in_review", display_status="در انتظار مدیر مالی")])
    item = module.list_my_requests()["data"][0]
    assert (item["status_label"], item["display_status"], item["status_key"]) == (
        "در انتظار مدیر مالی", "در انتظار مدیر مالی", "in_review")


def test_legacy_rows_without_a_status_key_fall_back_to_the_instance(engine, monkeypatch):
    module, frappe = engine
    monkeypatch.setattr(module, "require_company", lambda company: None)
    _all(frappe, [_row("PR-2", "")])
    item = module.list_my_requests()["data"][0]
    assert (item["status_key"], item["status_group"]) == ("rejected", "rejected")
