"""Idempotent per-company seeding of the system request templates.

Each `TemplateSpec` becomes one `ASOUD Workflow Definition` per company with the stages
Start -> Form -> Approval (direct manager) -> End. Re-running changes nothing. When a
spec's `version` is higher than the stored `template_version`, only the form fields and
the version are rewritten, so approvers an admin redesigned stay as they are.
"""

import json
import re

import frappe

from asoud_erp.services.request_templates.base import TemplateSpec, all_specs
from asoud_erp.services.workflow_stage_policy import normalize_stage_config

__all__ = ["all_specs", "ensure_system_templates", "on_company_insert"]

NATIVE_WORKFLOW = "ASOUD-SYSTEM-REQUEST-NATIVE"
NATIVE_STATE = "ASOUD Draft"
FORM_TITLE = "تکمیل فرم درخواست"
APPROVAL_TITLE = "تأیید مدیر مستقیم"


def on_company_insert(doc, method=None) -> None:
    """Company `after_insert` hook. The migrate hook seeds again, so a failure must not block the company."""
    try:
        ensure_system_templates(doc.name)
    except Exception:
        frappe.log_error(title="Seeding the system request templates failed", message=frappe.get_traceback())


def ensure_system_templates(company: str | None = None) -> dict:
    """Creates or upgrades the system request types; returns `{created, updated, skipped}`."""
    summary = {"created": 0, "updated": 0, "skipped": 0}
    specs = all_specs()
    companies = [company] if company else frappe.get_all("Company", pluck="name")
    if not specs or not companies:
        return summary
    native = _ensure_native_workflow()
    for name in companies:
        abbr = frappe.db.get_value("Company", name, "abbr")
        if not abbr:
            summary["skipped"] += len(specs)
            continue
        for spec in specs:
            summary[_ensure_definition(name, abbr, spec, native)] += 1
    return summary


def _ensure_native_workflow() -> str:
    """The shared inactive Frappe Workflow every system definition links to (the engine needs a link)."""
    if frappe.db.exists("Workflow", NATIVE_WORKFLOW):
        return NATIVE_WORKFLOW
    if not frappe.db.exists("Workflow State", NATIVE_STATE):
        frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": NATIVE_STATE}).insert(
            ignore_permissions=True)
    frappe.get_doc({
        "doctype": "Workflow", "workflow_name": NATIVE_WORKFLOW, "document_type": "ASOUD Workflow Request",
        "is_active": 0, "states": [{"state": NATIVE_STATE, "doc_status": "0", "allow_edit": "System Manager"}],
    }).insert(ignore_permissions=True)
    return NATIVE_WORKFLOW


def _form_config(spec: TemplateSpec) -> dict:
    return normalize_stage_config("User Task", {
        "title": FORM_TITLE, "activity_type": "Data Entry", "assignment_type": "Initiator",
        "form_fields": spec.form_fields, "allow_draft": False, "allow_reject": False, "allow_return": False})


def _approval_config(spec: TemplateSpec) -> dict:
    return normalize_stage_config("Approval", {
        "title": APPROVAL_TITLE, "assignment_type": spec.approval.get("assignment_type") or "Direct Manager",
        "approval_mode": "Any", "allow_reject": True, "allow_return": True, "reject_comment_required": True})


def _ensure_definition(company: str, abbr: str, spec: TemplateSpec, native: str) -> str:
    """One definition; returns the summary key `created`, `updated` or `skipped`."""
    existing = frappe.db.get_value(
        "ASOUD Workflow Definition", {"company": company, "template_key": spec.key},
        ["name", "template_version"], as_dict=True)
    if not existing:
        code = f"SYS-{spec.key.upper()}-{abbr}"
        if frappe.db.exists("ASOUD Workflow Definition", code):
            return "skipped"  # the code belongs to a definition an admin made; never overwrite it
        _create_definition(company, abbr, code, spec, native)
        return "created"

    from asoud_erp.api.v1.workflow_request import _form_stage_or_none

    stage = _form_stage_or_none(existing.name)
    if not stage:
        return "skipped"
    config = json.loads(stage.config_json or "{}")
    desired_fields = _form_config(spec)["form_fields"]
    current_fields = config.get("form_fields") or []
    if (existing.template_version or 0) >= spec.version and current_fields == desired_fields:
        return "skipped"
    config["form_fields"] = desired_fields
    frappe.db.set_value("ASOUD Workflow Stage", stage.name, "config_json",
                        json.dumps(config, ensure_ascii=False), update_modified=False)
    frappe.db.set_value("ASOUD Workflow Definition", existing.name, "template_version", spec.version,
                        update_modified=False)
    return "updated"


def _create_definition(company: str, abbr: str, code: str, spec: TemplateSpec, native: str) -> None:
    # Seeding runs as the system (migrate or company creation), so the inserts skip user permissions.
    definition = frappe.get_doc({
        "doctype": "ASOUD Workflow Definition", "workflow_code": code, "workflow_title": spec.title,
        "short_title": spec.short_title, "process_description": spec.description, "company": company,
        "module_key": spec.module_key, "creation_mode": "Template", "target_doctype": "ASOUD Workflow Request",
        "status": "Active", "readiness_status": "Ready", "frappe_workflow": native,
        "missing_requirements_json": "[]", "request_category": spec.category, "icon_key": spec.icon_key,
        "color_hex": spec.color_hex, "show_in_request_list": 1, "allow_user_submission": 1,
        "template_key": spec.key, "template_version": spec.version, "is_system_template": 1,
    }).insert(ignore_permissions=True)
    slug = re.sub(r"[^a-z0-9]+", "-", abbr.lower()).strip("-") or "co"
    start = {"trigger_type": "Manual", "initiator_roles": [], "subject_source": "General Subject",
             "pass_mode": "Direct"}
    form, approval = _form_config(spec), _approval_config(spec)
    plan = [
        ("start", "Start", "شروع", start),
        ("form", "User Task", form["title"], form),
        ("approval", "Approval", approval["title"], approval),
        ("end", "End", "پایان", {"title": "پایان", "outcome": "Completed", "result_label": ""}),
    ]
    stages = []
    for sequence, (part, stage_type, title, config) in enumerate(plan):
        config = {key: value for key, value in config.items() if key != "title"} if stage_type != "Start" \
            else config
        stages.append(frappe.get_doc({
            "doctype": "ASOUD Workflow Stage", "workflow_definition": definition.name,
            "stage_key": f"sys-{spec.key}-{slug}-{part}", "stage_type": stage_type, "stage_title": title,
            "sequence_no": sequence, "config_json": json.dumps(config, ensure_ascii=False),
            "configuration_status": "Complete",
        }).insert(ignore_permissions=True))
    for sequence, (source, target) in enumerate(zip(stages, stages[1:]), start=1):
        approve = source.stage_type == "Approval"
        frappe.get_doc({
            "doctype": "ASOUD Workflow Transition", "workflow_definition": definition.name,
            "from_stage": source.name, "to_stage": target.name,
            "transition_label": "تأیید" if approve else "",
            "condition_json": json.dumps({"action": "Approve"}) if approve else "{}", "sequence_no": sequence,
        }).insert(ignore_permissions=True)
    frappe.db.set_value("ASOUD Workflow Definition", definition.name, "steps_count", len(stages) - 1,
                        update_modified=False)
