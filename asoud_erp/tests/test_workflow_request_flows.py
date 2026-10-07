"""create, update, detail, cancel and comments of `workflow_request` on the in-memory fake site.

They execute the engine's real code paths without a database. The integration tests in
`integration_tests/test_request_*.py` cover the same behavior against a real site.
"""

import base64
import importlib
import json
import sys
import types
from datetime import date, timedelta

import pytest

from asoud_erp.services.request_templates import base as templates
from asoud_erp.tests import _fake_site as fake

RELOADED = [
    "asoud_erp.api.v1.workflow_request", "asoud_erp.services.request_access",
    "asoud_erp.services.erp_documents", "asoud_erp.services.request_link_values",
    "asoud_erp.services.request_comments",
]
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
FIELDS = [
    {"key": "requester", "label": "درخواست‌کننده", "type": "User", "required": True, "editable": False,
     "default_source": "session_user"},
    {"key": "kind", "label": "نوع درخواست", "type": "Choice", "required": True, "options": ["Daily", "Hourly"]},
    {"key": "proof", "label": "مدرک", "type": "Attachment"},
    {"key": "needed_date", "label": "تاریخ", "type": "Date", "min_date": "today"},
    {"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 50},
    {"key": "duration", "label": "مدت", "type": "Auto", "auto": "leave_duration"},
    {"key": "items", "label": "اقلام", "type": "Item Table", "required": True,
     "row_options": {"item_scope": "all", "note": True, "attachment": True, "min_rows": 1, "max_rows": 5}},
]


def b64(data=b"file-content"):
    return base64.b64encode(data).decode()


def fake_links(fields, values, company):
    """Stands in for validate_link_values: derives the item row keys ERPNext would."""
    for field in fields:
        if field.get("type") == "Item Table" and values.get(field["key"]):
            values[field["key"]] = [{
                **row, "item_name": "نام " + row["item_code"], "stock_uom": "Nos", "uom": row["uom"] or "Nos",
                "conversion_factor": 1.0, "stock_qty": row["qty"], "is_stock_item": 1} for row in values[field["key"]]]
    return values


class World:
    def __init__(self, module, site, runtime):
        self.module, self.site, self.runtime = module, site, runtime
        self.completed = []

    def create(self, values=None, **kwargs):
        data = {"company": "WP", "workflow_definition": "SYS-TEST-WP", "subject": "درخواست آزمایشی",
                "request_id": "request-" + "x" * 12, "values": {
                    "kind": "Daily", "reason": "دلیل", "needed_date": TOMORROW,
                    "items": [{"item_code": "ICU-MON-01", "qty": 2}], **(values or {})}}
        data.update(kwargs)
        return self.module.create_request(**data)["data"]


@pytest.fixture
def world(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    runtime = types.ModuleType("asoud_erp.api.v1.workflow_runtime")
    for name, module in {"frappe": frappe, "frappe.utils": utils,
                         "asoud_erp.api.v1.workflow_runtime": runtime}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    site.add("User", "sara@example.com")
    site.add("Employee", "HR-EMP-1", user_id="sara@example.com", company="WP", status="Active",
             employee_name="سارا محمدی", department="ICU - WP", branch="Tehran")
    site.add("Department", "ICU - WP", department_name="ICU")
    site.add("ASOUD Workflow Definition", "SYS-TEST-WP", status="Active", readiness_status="Ready",
             target_doctype="ASOUD Workflow Request", allow_user_submission=1, company="WP",
             workflow_title="درخواست آزمایشی", template_key="", template_version=0)
    site.add("ASOUD Workflow Stage", "START", workflow_definition="SYS-TEST-WP", stage_type="Start",
             config_json="{}")
    form = site.add("ASOUD Workflow Stage", "FORM", workflow_definition="SYS-TEST-WP", stage_type="User Task",
                    config_json=json.dumps({"form_fields": FIELDS}))
    runtime._next_stage = lambda instance, current, action=None: fake.FakeDoc(site, form)

    def start_workflow_instance(definition, subject, reference_doctype=None, reference_name=None):
        row = site.add("ASOUD Workflow Instance", "WFI-1", workflow_definition=definition, subject=subject,
                       reference_doctype=reference_doctype, reference_name=reference_name, status="Running",
                       current_stage="FORM", started_by=site.user)
        site.add("ASOUD Workflow Task", "TASK-1", workflow_instance=row["name"], workflow_stage="FORM",
                 status="Open", assigned_to=site.user)
        return {"ok": True, "data": {"name": row["name"], "status": "Running"}}

    state = World(None, site, runtime)

    def complete_workflow_task(task, action, comment=None, response=None):
        state.completed.append((task, action, response))
        site.table("ASOUD Workflow Task")[task].update(
            status="Completed", response_json=json.dumps(response), completed_on="2026-10-05 10:30:00")

    runtime.start_workflow_instance, runtime.complete_workflow_task = start_workflow_instance, complete_workflow_task
    module = importlib.import_module("asoud_erp.api.v1.workflow_request")
    monkeypatch.setattr(module, "require_company", lambda company: None)
    monkeypatch.setattr(module, "validate_link_values", fake_links)
    monkeypatch.setattr(module, "request_permission",
                        lambda doc, user=None, permission_type=None: doc.owner == site.user or "HR Manager" in site.roles)
    state.module = module
    yield state
    restore()


def test_custom_create_stores_files_values_header_and_returns_the_detail(world):
    site = world.site
    uploads = [{"filename": "price.pdf", "content_base64": b64(b"one"), "ref": "att-1"},
               {"filename": "price.pdf", "content_base64": b64(b"two"), "ref": "att-2"},
               {"filename": "notes.docx", "content_base64": b64(b"three"), "ref": "att-3"}]
    detail = world.create({"proof": "attachment:att-1", "items": [
        {"item_code": "ICU-MON-01", "qty": 2, "note": "فوری", "attachment": "attachment:att-2"},
        {"item_code": "CABLE", "qty": 1}]}, attachments=uploads)
    assert detail["name"] == detail["number"] and detail["status_key"] == "submitted"
    assert detail["status"] == "Running" and detail["status_label"] == "ارسال شده" and detail["status_group"] == "pending"
    assert detail["template_key"] == "" and detail["subject"] == "درخواست آزمایشی"
    assert (detail["item_count"], detail["attachment_count"], detail["comment_count"]) == (2, 3, 0)
    assert detail["can_edit"] is True and detail["can_cancel"] is True and detail["requester_name"] == "سارا محمدی"
    assert detail["native"] == {"doctype": "", "name": "", "status": "", "error": ""}
    assert detail["fields"][0]["key"] == "requester" and detail["workflow_instance"] == "WFI-1"
    scopes = {entry["name"]: entry["scope"] for entry in detail["attachments"]}
    assert sorted(scopes.values()) == ["field:proof", "general", "row:items:0"]
    proof = next(entry for entry in detail["attachments"] if entry["scope"] == "field:proof")
    row_file = next(entry for entry in detail["attachments"] if entry["scope"] == "row:items:0")
    assert detail["values"]["proof"] == proof["file_url"]
    assert detail["values"]["requester"] == "sara@example.com"  # filled from the session user
    first, second = detail["values"]["items"]
    assert first["attachment"] == row_file["file_url"] and first["note"] == "فوری"
    assert first["attachment_ref"] == {"name": row_file["name"], "filename": "price.pdf", "is_image": False}
    assert second["attachment"] is None and "attachment_ref" not in second
    assert "duration" not in detail["values"]  # Auto values only exist when a template computes them
    stored = site.table("ASOUD Workflow Request")[detail["name"]]
    assert "pending" not in stored["values_json"]
    assert stored["status_key"] == "submitted" and stored["status"] == "Submitted"
    assert "ICU-MON-01" in stored["search_text"] and "سارا محمدی" in stored["search_text"]
    assert site.table("File") and all(row["attached_to_doctype"] == "ASOUD Workflow Request" and row["is_private"] == 1
                                      for row in site.table("File").values())
    # The form task was completed with the validated values, template validation not repeated.
    task, action, response = world.completed[0]
    assert (task, action) == ("TASK-1", "Complete") and response["items"][0]["item_name"] == "نام ICU-MON-01"
    assert world.module.frappe.flags.get("asoud_request_form_validated") is None


def test_replaying_a_create_returns_the_same_request_and_a_changed_payload_conflicts(world):
    first = world.create()
    again = world.create()
    assert again["name"] == first["name"] and len(world.site.table("ASOUD Workflow Request")) == 1
    with pytest.raises(fake.ValidationError) as error:
        world.create(subject="موضوع دیگر")
    assert error.value.title == "REQUEST_ID_CONFLICT"
    with pytest.raises(fake.ValidationError):
        world.create(request_id="short")


@pytest.mark.parametrize("values,code", [
    ({"requester": "someone@example.com"}, "REQUESTER_MISMATCH"),
    ({"needed_date": "2020-01-01"}, "DATE_IN_PAST"),
])
def test_engine_rules_carry_their_error_code(world, values, code):
    with pytest.raises(fake.ValidationError) as error:
        world.create(values)
    assert error.value.title == code


def test_invalid_values_are_validation_errors_not_crashes(world):
    for values in ({"kind": "Weekly"}, {"reason": "x" * 51}, {"items": []}, {"unknown": 1},
                   {"duration": {"unit": "day"}}):
        with pytest.raises(fake.ValidationError):
            world.create(values, request_id="request-" + str(len(str(values))) * 12)
    assert not world.site.table("ASOUD Workflow Request")


def test_attachment_problems_are_reported_with_the_attachment_code(world):
    bad = [
        {"attachments": [{"filename": "a.exe", "content_base64": b64()}]},
        {"attachments": [{"filename": "a.pdf", "content_base64": "###"}]},
        {"attachments": [{"filename": "a.pdf", "content_base64": b64()}] * 2},
        {"attachments": "not a list"},
        {"values": {"kind": "Daily", "reason": "r", "proof": "attachment:ghost",
                    "items": [{"item_code": "A", "qty": 1}]}},
    ]
    for index, extra in enumerate(bad):
        with pytest.raises(fake.ValidationError) as error:
            world.create(request_id=f"request-bad-{index}-xxxx", **extra)
        assert error.value.title == "ATTACHMENT_INVALID", extra
    assert not world.site.table("File") and not world.site.table("ASOUD Workflow Request")


def test_same_filename_needs_refs_and_total_files_are_limited(world):
    same = [{"filename": "a.pdf", "content_base64": b64(b"1")}, {"filename": "a.pdf", "content_base64": b64(b"2")}]
    with pytest.raises(fake.ValidationError):
        world.create(attachments=same)
    world.create(attachments=[{**item, "ref": f"r{index}"} for index, item in enumerate(same)])
    many = [{"filename": f"{n}.pdf", "content_base64": b64(bytes([n])), "ref": f"r{n}"} for n in range(11)]
    with pytest.raises(fake.ValidationError):
        world.create(attachments=many, request_id="request-many-files-1")


def _template(monkeypatch, **overrides):
    def validate(ctx):
        values = dict(ctx.values)
        values["duration"] = {"unit": "day", "days": 3.0, "hours": None, "day_equivalent": 3.0}
        values["_seen"] = (ctx.is_update, ctx.request_name, ctx.employee, ctx.user)
        values.pop("_seen")
        return values

    spec = templates.TemplateSpec(
        key="leave", title="درخواست مرخصی", short_title="مرخصی", description="", number_prefix="LV",
        category="HR", module_key="HR", icon_key="leave", color_hex="#000000", version=1,
        subject_mode="generated", form_fields=FIELDS, attachments={"max_files": 2, "max_mb": 1, "extensions": ["pdf"]},
        approval={"assignment_type": "Direct Manager"}, validate=validate,
        build_subject=lambda values: "مرخصی سالانه (روزانه)",
        denormalize=lambda values: {"priority": "Normal", "required_by": values.get("needed_date"),
                                    "project": "", "department": "ICU - WP"},
        summarize=lambda values, row: {"kind": values.get("kind")}, **overrides)
    monkeypatch.setitem(templates._REGISTRY, "leave", spec)
    return spec


def test_template_create_derives_header_and_uses_template_validation(world, monkeypatch):
    spec = _template(monkeypatch)
    site = world.site
    site.table("ASOUD Workflow Definition")["SYS-TEST-WP"].update(template_key="leave", template_version=1)
    detail = world.create(subject="client subject", priority="Urgent", project="X", department="Y", required_by="2000-01-01")
    assert detail["subject"] == "مرخصی سالانه (روزانه)" and detail["priority"] == "Normal"
    assert detail["department"] == "ICU - WP" and detail["required_by"] == TOMORROW and detail["project"] == ""
    assert detail["template_key"] == "leave" and detail["template_version"] == 1
    assert detail["requester_employee"] == "HR-EMP-1"
    assert detail["values"]["duration"]["day_equivalent"] == 3.0
    # Selecting the template by key resolves the definition of the company.
    by_key = world.module.create_request(
        company="WP", template_key="leave", request_id="request-by-key-0001",
        values={"kind": "Daily", "needed_date": TOMORROW, "items": [{"item_code": "A", "qty": 1}]})["data"]
    assert by_key["workflow_definition"] == "SYS-TEST-WP"
    # Template attachment limits apply (2 files, pdf only).
    with pytest.raises(fake.ValidationError) as error:
        world.create(request_id="request-ext-000001", attachments=[{"filename": "a.docx", "content_base64": b64()}])
    assert error.value.title == "ATTACHMENT_INVALID"
    assert spec.available_for("WP", "sara@example.com")


def test_template_errors(world, monkeypatch):
    _template(monkeypatch)
    site = world.site
    with pytest.raises(fake.ValidationError) as error:
        world.module.create_request(company="WP", template_key="leave", request_id="request-nokey-0001", values={})
    assert error.value.title == "TEMPLATE_NOT_AVAILABLE"
    site.table("ASOUD Workflow Definition")["SYS-TEST-WP"].update(template_key="leave", template_version=1)
    monkeypatch.setitem(templates._REGISTRY, "leave", templates._REGISTRY["leave"].__class__(
        **{**templates._REGISTRY["leave"].__dict__, "available_for": lambda company, user: False}))
    with pytest.raises(fake.ValidationError) as error:
        world.create()
    assert error.value.title == "EMPLOYEE_NOT_FOUND"
    monkeypatch.delitem(templates._REGISTRY, "leave")
    monkeypatch.setattr(templates, "_load_spec_modules", lambda: None)
    with pytest.raises(fake.ValidationError) as error:
        world.create(request_id="request-nospec-0001")
    assert error.value.title == "TEMPLATE_NOT_AVAILABLE"


def test_update_adds_and_removes_files_and_clears_references(world):
    site, module = world.site, world.module
    uploads = [{"filename": "a.pdf", "content_base64": b64(b"aaa"), "ref": "a"},
               {"filename": "b.png", "content_base64": b64(b"bbb"), "ref": "b"}]
    created = world.create({"proof": "attachment:a", "items": [
        {"item_code": "X", "qty": 1, "attachment": "attachment:b"}]}, attachments=uploads)
    proof = next(e for e in created["attachments"] if e["scope"] == "field:proof")
    row_file = next(e for e in created["attachments"] if e["scope"] == "row:items:0")
    new = {"filename": "c.pdf", "content_base64": b64(b"ccc"), "ref": "c"}
    updated = module.update_request(created["name"], "", {
        "kind": "Hourly", "proof": proof["file_url"], "reason": "تغییر", "needed_date": TOMORROW,
        "items": [{"item_code": "X", "qty": 3, "attachment": "attachment:c"}]},
        attachments=[new], remove_attachments=[row_file["name"]])["data"]
    assert updated["subject"] == "درخواست آزمایشی" and updated["values"]["kind"] == "Hourly"
    assert updated["values"]["items"][0]["qty"] == 3
    new_entry = next(e for e in updated["attachments"] if e["scope"] == "row:items:0")
    assert new_entry["filename"] == "c.pdf" and new_entry["name"] != row_file["name"]
    assert row_file["name"] in site.deleted_files and len(updated["attachments"]) == 2
    assert updated["values"]["items"][0]["attachment_ref"]["name"] == new_entry["name"]
    task = site.table("ASOUD Workflow Task")["TASK-1"]
    assert json.loads(task["response_json"])["kind"] == "Hourly"
    assert site.table("ASOUD Workflow Activity") and next(iter(site.table("ASOUD Workflow Activity").values()))["action"] == "Edited"
    # Replaying the same update neither duplicates the new file nor fails on the removed one.
    again = module.update_request(created["name"], "", {
        "kind": "Hourly", "proof": proof["file_url"], "reason": "تغییر", "needed_date": TOMORROW,
        "items": [{"item_code": "X", "qty": 3, "attachment": "attachment:c"}]},
        attachments=[new], remove_attachments=[row_file["name"]])["data"]
    assert len(again["attachments"]) == 2 and len(site.table("File")) == 2
    assert {e["name"] for e in again["attachments"]} == {e["name"] for e in updated["attachments"]}


def test_update_clears_a_field_whose_file_was_removed_and_keeps_omitted_attachment_keys(world):
    module = world.module
    created = world.create({"proof": "attachment:a"}, attachments=[
        {"filename": "a.pdf", "content_base64": b64(b"aaa"), "ref": "a"}])
    proof = created["attachments"][0]
    kept = module.update_request(created["name"], "", {
        "kind": "Daily", "reason": "x", "needed_date": TOMORROW, "items": [{"item_code": "X", "qty": 1}]})["data"]
    assert kept["values"]["proof"] == proof["file_url"] and len(kept["attachments"]) == 1
    cleared = module.update_request(created["name"], "", {
        "kind": "Daily", "reason": "x", "needed_date": TOMORROW, "proof": proof["file_url"],
        "items": [{"item_code": "X", "qty": 1}]}, remove_attachments=[proof["name"]])["data"]
    assert cleared["values"]["proof"] is None and cleared["attachments"] == []


def test_a_required_attachment_field_cannot_lose_its_file(world, monkeypatch):
    required = [{**field, "required": True} if field["key"] == "proof" else field for field in FIELDS]
    world.site.table("ASOUD Workflow Stage")["FORM"]["config_json"] = json.dumps({"form_fields": required})
    created = world.create({"proof": "attachment:a"}, attachments=[
        {"filename": "a.pdf", "content_base64": b64(b"aaa"), "ref": "a"}])
    with pytest.raises(fake.ValidationError) as error:
        world.module.update_request(created["name"], "", {
            "kind": "Daily", "reason": "x", "needed_date": TOMORROW, "items": [{"item_code": "X", "qty": 1}]},
            remove_attachments=[created["attachments"][0]["name"]])
    assert error.value.title == "ATTACHMENT_INVALID" and world.site.deleted_files == []


def test_update_refuses_foreign_files_other_owners_and_reviewed_requests(world):
    module, site = world.module, world.site
    created = world.create(attachments=[{"filename": "a.pdf", "content_base64": b64(b"aaa"), "ref": "a"}])
    foreign = site.add("File", "FILE-OTHER", file_name="x.pdf", attached_to_doctype="Item", attached_to_name="I")
    values = {"kind": "Daily", "reason": "x", "needed_date": TOMORROW, "items": [{"item_code": "X", "qty": 1}]}
    with pytest.raises(fake.ValidationError) as error:
        module.update_request(created["name"], "", values, remove_attachments=[foreign["name"]])
    assert error.value.title == "ATTACHMENT_INVALID"
    with pytest.raises(fake.ValidationError) as error:
        module.update_request(created["name"], "", {**values, "proof": "/private/files/not-mine.pdf"})
    assert error.value.title == "ATTACHMENT_INVALID"
    with pytest.raises(fake.ValidationError) as error:
        module.update_request(created["name"], "", {**values, "requester": "boss@example.com"})
    assert error.value.title == "REQUESTER_MISMATCH"
    site.add("ASOUD Workflow Task", "TASK-2", workflow_instance="WFI-1", workflow_stage="APPROVAL",
             status="Completed", assigned_to="mgr@example.com")
    with pytest.raises(fake.ValidationError) as error:
        module.update_request(created["name"], "", values)
    assert error.value.title == "REQUEST_NOT_EDITABLE"
    assert module.get_request(created["name"])["data"]["can_edit"] is False
    site.table("ASOUD Workflow Task").pop("TASK-2")
    site.table("ASOUD Workflow Instance")["WFI-1"]["status"] = "Completed"
    with pytest.raises(fake.ValidationError) as error:
        module.update_request(created["name"], "", values)
    assert error.value.title == "REQUEST_NOT_EDITABLE"
    site.user = "mgr@example.com"
    with pytest.raises(fake.PermissionError_):
        module.update_request(created["name"], "", values)


def test_detail_permissions_rejection_reason_and_native_error(world):
    module, site = world.module, world.site
    created = world.create()
    row = site.table("ASOUD Workflow Request")[created["name"]]
    row.update(native_status="Failed", native_error="Leave balance exhausted", native_doctype="", native_name="")
    detail = module.get_request(created["name"])["data"]
    assert detail["native"] == {"doctype": "", "name": "", "status": "Failed", "error": ""}
    site.roles = ["HR Manager"]
    assert module.get_request(created["name"])["data"]["native"]["error"] == "Leave balance exhausted"
    site.roles = ["Employee"]
    site.user = "stranger@example.com"
    with pytest.raises(fake.PermissionError_):
        module.get_request(created["name"])
    site.user = "sara@example.com"
    site.table("ASOUD Workflow Instance")["WFI-1"]["status"] = "Rejected"
    site.add("ASOUD Workflow Task", "TASK-R", workflow_instance="WFI-1", workflow_stage="APPROVAL", status="Rejected",
             comment="بودجه کافی نیست", completed_on="2026-10-06 09:00:00")
    row["status_key"] = "rejected"
    rejected = module.get_request(created["name"])["data"]
    assert rejected["rejection_reason"] == "بودجه کافی نیست" and rejected["status_key"] == "rejected"
    assert rejected["can_edit"] is False and rejected["can_cancel"] is False and rejected["status"] == "Rejected"


def test_cancel_sets_the_instance_and_request_status(world):
    module, site = world.module, world.site
    created = world.create()
    cancelled = module.cancel_request(created["name"], "دیگر لازم نیست")["data"]
    assert cancelled["status"] == "Cancelled" and cancelled["can_cancel"] is False
    assert site.table("ASOUD Workflow Task")["TASK-1"]["status"] == "Completed"  # the form task was already done
    assert site.table("ASOUD Workflow Instance")["WFI-1"]["status"] == "Cancelled"
    with pytest.raises(fake.ValidationError):
        module.cancel_request(created["name"])  # only a request in progress can be changed


def test_comments_are_added_listed_and_notified(world):
    module, site = world.module, world.site
    created = world.create()
    site.add("ASOUD Workflow Task", "TASK-M", workflow_instance="WFI-1", workflow_stage="APPROVAL", status="Open",
             assigned_to="mgr@example.com")
    site.user = "mgr@example.com"
    site.roles = ["HR Manager"]
    comment = module.add_request_comment(created["name"], "<p>لطفاً پیش‌فاکتور را پیوست کنید.</p>")["data"]
    assert comment["content"] == "لطفاً پیش‌فاکتور را پیوست کنید." and comment["author"] == "mgr@example.com"
    assert comment["is_mine"] is True and comment["author_name"] == "Full mgr@example.com"
    notified = {row["for_user"] for row in site.table("Notification Log").values()}
    assert notified == {"sara@example.com"}  # never the author
    with pytest.raises(fake.ValidationError) as error:
        module.add_request_comment(created["name"], "  <br> ")
    assert error.value.title == "EMPTY_COMMENT"
    site.user = "sara@example.com"
    site.roles = ["Employee"]
    listed = module.list_request_comments(created["name"])
    assert listed["meta"] == {"api_version": "v1", "total": 1, "limit_start": 0, "limit_page_length": 50}
    assert listed["data"][0]["is_mine"] is False and listed["data"][0]["content"].startswith("لطفاً")
    assert module.get_request(created["name"])["data"]["comment_count"] == 1
    site.user = "stranger@example.com"
    with pytest.raises(fake.PermissionError_):
        module.list_request_comments(created["name"])
    with pytest.raises(fake.PermissionError_):
        module.add_request_comment(created["name"], "hello")


def test_options_resolve_defaults_and_settings(world, monkeypatch):
    _template(monkeypatch)
    site, module = world.site, world.module
    site.table("ASOUD Workflow Definition")["SYS-TEST-WP"].update(
        template_key="leave", template_version=1, is_system_template=1, workflow_code="SYS-TEST-WP",
        short_title="مرخصی", module_key="HR", request_category="HR", process_description="", icon_key="leave",
        color_hex="#000", show_in_request_list=1)
    site.table("Company")["WP"] = {"name": "WP", "asoud_daily_working_hours": 7.5,
                                    "asoud_request_cost_center_required": 1}
    row = module.request_options("WP")["data"][0]
    assert row["template_key"] == "leave" and row["number_prefix"] == "LV" and row["subject_mode"] == "generated"
    assert row["settings"] == {"cost_center_required": True, "daily_working_hours": 7.5}
    assert row["attachments"] == {"max_files": 2, "max_mb": 1, "extensions": ["pdf"]}
    requester = next(f for f in row["fields"] if f["key"] == "requester")
    assert requester["default_value"] == "sara@example.com" and requester["default_label"] == "سارا محمدی"
    assert "default_source" not in requester
