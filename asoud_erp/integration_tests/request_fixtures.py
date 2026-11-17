"""Request types and test specs shared by the request-engine integration tests.

The engine tests must not depend on the real purchase/supply/leave specs, so they run
against two small test specs registered under the keys `purchase` and `leave` (the
registry is patched for the duration of a test).
"""

import json
from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.services.request_templates import base as templates

NATIVE_WORKFLOW = "ASOUD Request Test Native"
REQUEST_FIELDS = [
    {"key": "requester", "label": "درخواست‌کننده", "type": "User", "required": True, "editable": False,
     "default_source": "session_user"},
    {"key": "priority", "label": "اولویت", "type": "Choice", "options": ["Normal", "High", "Urgent"],
     "option_labels": {"Normal": "عادی", "High": "مهم", "Urgent": "فوری"}, "default_value": "Normal"},
    {"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 2000},
    {"key": "proof", "label": "مدرک", "type": "Attachment"},
    {"key": "items", "label": "اقلام", "type": "Item Table",
     "row_options": {"item_scope": "all", "note": True, "attachment": True, "min_rows": 0, "max_rows": 10}},
]


def native_workflow() -> str:
    if not frappe.db.exists("Workflow State", "ASOUD Request Test Draft"):
        frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": "ASOUD Request Test Draft"}).insert()
    if not frappe.db.exists("Workflow", NATIVE_WORKFLOW):
        frappe.get_doc({"doctype": "Workflow", "workflow_name": NATIVE_WORKFLOW,
                        "document_type": "ASOUD Workflow Request", "is_active": 0,
                        "states": [{"state": "ASOUD Request Test Draft", "doc_status": "0",
                                    "allow_edit": "System Manager"}]}).insert()
    return NATIVE_WORKFLOW


def make_definition(company: str, approvals: int = 1, fields: list | None = None, template_key: str = "",
                    token: str | None = None) -> tuple[str, dict]:
    """A request type Start -> Form -> `approvals` x direct-manager approval -> End."""
    token = token or uuid4().hex[:8]
    definition = frappe.get_doc({
        "doctype": "ASOUD Workflow Definition", "workflow_code": f"req-{token}",
        "workflow_title": f"درخواست آزمایشی {token}", "company": company, "module_key": "Support",
        "target_doctype": "ASOUD Workflow Request", "status": "Active", "readiness_status": "Ready",
        "allow_user_submission": 1, "frappe_workflow": native_workflow(), "template_key": template_key,
        "template_version": 1 if template_key else 0, "is_system_template": 1 if template_key else 0,
    }).insert(ignore_permissions=True)
    configs = [("Start", {"title": "شروع"}),
               ("User Task", {"title": "ثبت درخواست", "activity_type": "Data Entry", "assignment_type": "Initiator",
                              "form_fields": fields if fields is not None else REQUEST_FIELDS})]
    configs += [("Approval", {"title": f"تأیید {index + 1}", "assignment_type": "Direct Manager",
                              "approval_mode": "Any", "allow_reject": True, "allow_return": True,
                              "reject_comment_required": True}) for index in range(approvals)]
    configs.append(("End", {"title": "پایان", "outcome": "Completed"}))
    stages = []
    for index, (kind, config) in enumerate(configs):
        stages.append(frappe.get_doc({
            "doctype": "ASOUD Workflow Stage", "workflow_definition": definition.name,
            "stage_key": f"{kind.lower().replace(' ', '-')}-{index}-{token}", "stage_title": config["title"],
            "stage_type": kind, "sequence_no": index + 1, "config_json": json.dumps(config),
            "configuration_status": "Complete"}).insert(ignore_permissions=True))
    for first, second in zip(stages, stages[1:]):
        approve = first.stage_type == "Approval"
        frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": definition.name,
                        "from_stage": first.name, "to_stage": second.name,
                        "condition_json": json.dumps({"action": "Approve"}) if approve else "{}"}
                       ).insert(ignore_permissions=True)
    return definition.name, {stage.stage_type + str(index): stage for index, stage in enumerate(stages)}


def make_spec(key: str, prefix: str, **extra) -> templates.TemplateSpec:
    return templates.TemplateSpec(
        key=key, title=f"درخواست {key}", short_title=key, description="آزمایشی", number_prefix=prefix,
        category="HR" if key == "leave" else "Purchase", module_key="HR" if key == "leave" else "Purchase",
        icon_key=key, color_hex="#1769F6", version=1, subject_mode="generated" if key == "leave" else "input",
        form_fields=REQUEST_FIELDS, attachments={"max_files": 10, "max_mb": 10, "extensions": [
            "pdf", "png", "jpg", "jpeg", "xls", "xlsx", "doc", "docx"]},
        approval={"assignment_type": "Direct Manager"},
        build_subject=(lambda values: "مرخصی آزمایشی") if key == "leave" else None,
        denormalize=lambda values: {"priority": values.get("priority") or "Normal", "required_by": None,
                                    "project": "", "department": ""},
        **extra)


def patched_specs():
    """Registry with the two test specs only (and no module loading), as a context manager."""
    registry = {"purchase": make_spec("purchase", "PR"), "leave": make_spec("leave", "LV")}
    return _Patched(registry)


class _Patched:
    def __init__(self, registry):
        self.patches = [patch.object(templates, "_REGISTRY", registry),
                        patch.object(templates, "_load_spec_modules", lambda: None)]

    def __enter__(self):
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in reversed(self.patches):
            item.stop()


def seed_test_templates(company: str) -> dict:
    """Replaces the company's system definitions with ones seeded from the test specs.

    Call inside `patched_specs()`. The deletions are rolled back with the test.
    """
    from asoud_erp.services.request_templates.seed import ensure_system_templates

    old = frappe.get_all("ASOUD Workflow Definition", filters={
        "company": company, "template_key": ["in", ["purchase", "supply", "leave"]]}, pluck="name")
    for name in old:
        frappe.db.delete("ASOUD Workflow Transition", {"workflow_definition": name})
        frappe.db.delete("ASOUD Workflow Stage", {"workflow_definition": name})
        frappe.db.delete("ASOUD Workflow Definition", {"name": name})
    ensure_system_templates(company)
    return {row.template_key: row.name for row in frappe.get_all(
        "ASOUD Workflow Definition", filters={"company": company, "is_system_template": 1},
        fields=["name", "template_key"])}
