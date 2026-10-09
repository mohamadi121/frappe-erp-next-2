"""Seeding, status mirror, dispatch trigger and the system-form guard on the in-memory fake site."""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from asoud_erp.services.request_templates import base as templates
from asoud_erp.tests import _fake_site as fake

CONTRACT_FIELDS = json.loads((Path(__file__).parent / "fixtures" / "contract_form_fields.json").read_text())
RELOADED = [
    "asoud_erp.api.v1.workflow", "asoud_erp.api.v1.workflow_request", "asoud_erp.services.request_access",
    "asoud_erp.services.erp_documents", "asoud_erp.services.request_link_values",
    "asoud_erp.services.request_comments", "asoud_erp.services.request_templates.seed",
    "asoud_erp.services.request_templates.lifecycle", "asoud_erp.services.request_native_documents",
]


def make_spec(key, prefix, title, version=1, **extra):
    return templates.TemplateSpec(
        key=key, title=title, short_title=title, description="شرح " + title, number_prefix=prefix,
        category="HR" if key == "leave" else "Purchase", module_key="HR" if key == "leave" else "Purchase",
        icon_key="leave" if key == "leave" else "purchase", color_hex="#1769F6", version=version,
        subject_mode="generated" if key == "leave" else "input", form_fields=CONTRACT_FIELDS[key],
        attachments={"max_files": 10, "max_mb": 10, "extensions": ["pdf"]},
        approval={"assignment_type": "Direct Manager"}, **extra)


class Env:
    pass


@pytest.fixture
def env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    runtime = types.ModuleType("asoud_erp.api.v1.workflow_runtime")
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    utils.cint = int
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming, "asoud_erp.api.v1.workflow_runtime": runtime}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)

    def next_stage(instance, current, action=None):
        rows = [row for row in site.table("ASOUD Workflow Transition").values() if row["from_stage"] == current]
        return fake.FakeDoc(site, site.table("ASOUD Workflow Stage")[rows[0]["to_stage"]]) if len(rows) == 1 else None

    runtime._next_stage = next_stage
    runtime.start_workflow_instance = lambda **kwargs: None
    site.add("Company", "Wind Power LLC", abbr="WP")
    site.add("Company", "Second Co", abbr="SC")
    registry = {"purchase": make_spec("purchase", "PR", "درخواست خرید کالا"),
                "leave": make_spec("leave", "LV", "درخواست مرخصی")}
    monkeypatch.setattr(templates, "_REGISTRY", registry)
    monkeypatch.setattr(templates, "_load_spec_modules", lambda: None)
    env = Env()
    env.site, env.frappe, env.registry = site, frappe, registry
    env.seed = importlib.import_module("asoud_erp.services.request_templates.seed")
    env.lifecycle = importlib.import_module("asoud_erp.services.request_templates.lifecycle")
    env.monkeypatch = monkeypatch
    yield env
    restore()


def snapshot(site):
    return {doctype: json.dumps(site.table(doctype), sort_keys=True, default=str)
            for doctype in ("ASOUD Workflow Definition", "ASOUD Workflow Stage", "ASOUD Workflow Transition",
                            "Workflow", "Workflow State")}


def test_seeding_creates_a_definition_per_company_and_template(env):
    site = env.site
    assert env.seed.ensure_system_templates() == {"created": 4, "updated": 0, "skipped": 0}
    definitions = site.table("ASOUD Workflow Definition")
    assert sorted(definitions) == ["SYS-LEAVE-SC", "SYS-LEAVE-WP", "SYS-PURCHASE-SC", "SYS-PURCHASE-WP"]
    leave = definitions["SYS-LEAVE-WP"]
    assert (leave["company"], leave["workflow_title"], leave["template_key"], leave["template_version"],
            leave["is_system_template"]) == ("Wind Power LLC", "درخواست مرخصی", "leave", 1, 1)
    assert (leave["status"], leave["readiness_status"], leave["creation_mode"], leave["target_doctype"]) == (
        "Active", "Ready", "Template", "ASOUD Workflow Request")
    assert (leave["module_key"], leave["request_category"], leave["icon_key"], leave["color_hex"]) == (
        "HR", "HR", "leave", "#1769F6")
    assert (leave["show_in_request_list"], leave["allow_user_submission"], leave["steps_count"]) == (1, 1, 3)
    assert leave["frappe_workflow"] == "ASOUD-SYSTEM-REQUEST-NATIVE" and leave["missing_requirements_json"] == "[]"
    assert site.table("Workflow")["ASOUD-SYSTEM-REQUEST-NATIVE"]["is_active"] == 0
    assert "ASOUD Draft" in site.table("Workflow State")
    stages = sorted((row for row in site.table("ASOUD Workflow Stage").values()
                     if row["workflow_definition"] == "SYS-LEAVE-WP"), key=lambda row: row["sequence_no"])
    assert [row["stage_type"] for row in stages] == ["Start", "User Task", "Approval", "End"]
    assert [row["stage_key"] for row in stages] == [f"sys-leave-wp-{part}" for part in ("start", "form", "approval", "end")]
    assert json.loads(stages[0]["config_json"]) == {
        "trigger_type": "Manual", "initiator_roles": [], "subject_source": "General Subject", "pass_mode": "Direct"}
    form, approval = json.loads(stages[1]["config_json"]), json.loads(stages[2]["config_json"])
    assert form["assignment_type"] == "Initiator" and form["activity_type"] == "Data Entry"
    assert (form["allow_draft"], form["allow_reject"], form["allow_return"]) == (False, False, False)
    assert [field["key"] for field in form["form_fields"]] == [f["key"] for f in CONTRACT_FIELDS["leave"]]
    assert approval["assignment_type"] == "Direct Manager" and approval["approval_mode"] == "Any"
    assert (approval["allow_reject"], approval["allow_return"], approval["reject_comment_required"]) == (True, True, True)
    assert stages[2]["stage_title"] == "تأیید مدیر مستقیم"
    assert json.loads(stages[3]["config_json"])["outcome"] == "Completed"
    transitions = sorted((row for row in site.table("ASOUD Workflow Transition").values()
                          if row["workflow_definition"] == "SYS-LEAVE-WP"), key=lambda row: row["sequence_no"])
    assert [(row["from_stage"], row["to_stage"]) for row in transitions] == [
        (a["name"], b["name"]) for a, b in zip(stages, stages[1:])]
    assert [json.loads(row["condition_json"]) for row in transitions] == [{}, {}, {"action": "Approve"}]


def test_seeding_twice_changes_nothing(env):
    env.seed.ensure_system_templates()
    before = snapshot(env.site)
    assert env.seed.ensure_system_templates() == {"created": 0, "updated": 0, "skipped": 4}
    assert snapshot(env.site) == before
    assert len(env.site.table("Workflow")) == 1


def test_a_version_bump_rewrites_only_the_form_fields(env):
    env.seed.ensure_system_templates()
    site = env.site
    stages = {row["stage_type"]: row for row in site.table("ASOUD Workflow Stage").values()
              if row["workflow_definition"] == "SYS-LEAVE-WP"}
    approval = json.loads(stages["Approval"]["config_json"])
    approval.update(assignment_type="Role", approver_roles=["HR Manager"])
    stages["Approval"]["config_json"] = json.dumps(approval)
    old_form = stages["User Task"]["config_json"]
    stages["User Task"]["config_json"] = json.dumps({**json.loads(old_form), "form_fields": [], "instructions": "x"})
    changed = [*CONTRACT_FIELDS["leave"][:-1], {"key": "extra", "label": "اضافی", "type": "Short Text"}]
    env.registry["leave"] = make_spec("leave", "LV", "درخواست مرخصی", version=2)
    object.__setattr__(env.registry["leave"], "form_fields", changed)
    assert env.seed.ensure_system_templates() == {"created": 0, "updated": 2, "skipped": 2}
    assert json.loads(stages["Approval"]["config_json"]) == approval
    form = json.loads(stages["User Task"]["config_json"])
    assert form["instructions"] == "x" and form["form_fields"][-1]["key"] == "extra"
    assert site.table("ASOUD Workflow Definition")["SYS-LEAVE-WP"]["template_version"] == 2
    assert site.table("ASOUD Workflow Definition")["SYS-PURCHASE-WP"]["template_version"] == 1
    assert env.seed.ensure_system_templates() == {"created": 0, "updated": 0, "skipped": 4}


def test_a_company_inserted_later_is_seeded_and_a_failure_does_not_block_it(env):
    env.seed.ensure_system_templates()
    env.site.add("Company", "Third Co", abbr="TC")
    env.seed.on_company_insert(types.SimpleNamespace(name="Third Co"))
    assert {"SYS-LEAVE-TC", "SYS-PURCHASE-TC"} <= set(env.site.table("ASOUD Workflow Definition"))
    env.monkeypatch.setattr(env.seed, "ensure_system_templates",
                            lambda company=None: (_ for _ in ()).throw(RuntimeError("boom")))
    env.seed.on_company_insert(types.SimpleNamespace(name="Third Co"))  # logged, not raised


def test_a_definition_code_owned_by_an_admin_is_never_overwritten(env):
    env.site.add("ASOUD Workflow Definition", "SYS-LEAVE-WP", workflow_code="SYS-LEAVE-WP", company="Wind Power LLC",
                 template_key="", workflow_title="دست‌ساز")
    summary = env.seed.ensure_system_templates("Wind Power LLC")
    assert summary == {"created": 1, "updated": 0, "skipped": 1}
    assert env.site.table("ASOUD Workflow Definition")["SYS-LEAVE-WP"]["workflow_title"] == "دست‌ساز"


def test_seeding_without_specs_or_companies_does_nothing(env):
    env.registry.clear()
    assert env.seed.ensure_system_templates() == {"created": 0, "updated": 0, "skipped": 0}
    assert not env.site.table("ASOUD Workflow Definition")


def test_every_contract_form_is_accepted_by_the_form_policy_when_seeded(env):
    env.registry["supply"] = make_spec("supply", "SP", "درخواست تأمین کالا")
    env.seed.ensure_system_templates("Wind Power LLC")
    assert {"SYS-SUPPLY-WP", "SYS-PURCHASE-WP", "SYS-LEAVE-WP"} <= set(env.site.table("ASOUD Workflow Definition"))


# --------------------------------------------------------------------------- status mirror


def _running(env, **instance):
    site = env.site
    site.add("ASOUD Workflow Definition", "DEF", workflow_code="DEF", company="Wind Power LLC", template_key="leave")
    site.add("ASOUD Workflow Stage", "START", workflow_definition="DEF", stage_type="Start", config_json="{}")
    site.add("ASOUD Workflow Stage", "FORM", workflow_definition="DEF", stage_type="User Task", config_json="{}")
    site.add("ASOUD Workflow Stage", "APPROVAL", workflow_definition="DEF", stage_type="Approval", config_json="{}")
    site.add("ASOUD Workflow Transition", "T1", workflow_definition="DEF", from_stage="START", to_stage="FORM")
    site.add("ASOUD Workflow Request", "LV-1405-0001", company="Wind Power LLC", status="Submitted",
             status_key="submitted", template_key="leave", workflow_definition="DEF", workflow_instance="WFI-1",
             native_status="")
    row = site.add("ASOUD Workflow Instance", "WFI-1", workflow_definition="DEF", status="Running",
                   current_stage="FORM", reference_doctype="ASOUD Workflow Request", reference_name="LV-1405-0001",
                   **instance)
    return fake.FakeDoc(site, row)


def test_status_key_follows_the_stage_and_tasks(env):
    site, lifecycle = env.site, env.lifecycle
    instance = _running(env)
    assert lifecycle.request_status_key(instance, "Submitted") == "submitted"  # waiting at the form, not yet submitted
    site.add("ASOUD Workflow Task", "T-FORM", workflow_instance="WFI-1", workflow_stage="FORM", status="Completed")
    instance.current_stage = "APPROVAL"
    assert lifecycle.request_status_key(instance, "Submitted") == "submitted"
    site.add("ASOUD Workflow Task", "T-APPROVAL", workflow_instance="WFI-1", workflow_stage="APPROVAL",
             status="Completed", action="Return")
    instance.current_stage = "FORM"
    assert lifecycle.request_status_key(instance, "Submitted") == "returned"
    instance.current_stage = "APPROVAL"
    assert lifecycle.request_status_key(instance, "Submitted") == "in_review"
    for status, key in (("Completed", "approved"), ("Rejected", "rejected"), ("Cancelled", "cancelled"),
                        ("Failed", "failed")):
        instance.status = status
        assert lifecycle.request_status_key(instance, "Submitted") == key


def test_the_hook_mirrors_the_status_and_ignores_other_documents(env):
    site, lifecycle = env.site, env.lifecycle
    instance = _running(env)
    site.table("ASOUD Workflow Request")["LV-1405-0001"]["status_key"] = ""
    lifecycle.on_instance_update(instance)
    assert site.table("ASOUD Workflow Request")["LV-1405-0001"]["status_key"] == "submitted"
    instance.status = "Rejected"
    lifecycle.on_instance_update(instance)
    assert site.table("ASOUD Workflow Request")["LV-1405-0001"]["status_key"] == "rejected"
    other = types.SimpleNamespace(reference_doctype="Material Request", reference_name="MR-1")
    lifecycle.on_instance_update(other)
    lifecycle.on_instance_update(types.SimpleNamespace(reference_doctype="ASOUD Workflow Request", reference_name=None))
    lifecycle.on_instance_update(types.SimpleNamespace(reference_doctype="ASOUD Workflow Request",
                                                       reference_name="MISSING"))


def _dispatch_recorder(env):
    calls = []
    module = importlib.import_module("asoud_erp.services.request_native_documents")
    env.monkeypatch.setattr(module, "dispatch", lambda request: calls.append(request.name))
    return calls


def test_final_approval_dispatches_once_and_only_for_templates(env):
    site, lifecycle = env.site, env.lifecycle
    calls = _dispatch_recorder(env)
    instance = _running(env)
    instance.status = "Completed"
    instance.has_value_changed = lambda field: True
    lifecycle.on_instance_update(instance)
    assert calls == ["LV-1405-0001"]
    assert site.table("ASOUD Workflow Request")["LV-1405-0001"]["status_key"] == "approved"
    instance.has_value_changed = lambda field: False  # a later save of an already finished instance
    lifecycle.on_instance_update(instance)
    assert calls == ["LV-1405-0001"]
    instance.has_value_changed = lambda field: True
    instance.status = "Rejected"
    lifecycle.on_instance_update(instance)
    assert calls == ["LV-1405-0001"]
    site.table("ASOUD Workflow Request")["LV-1405-0001"]["template_key"] = ""
    instance.status = "Completed"
    lifecycle.on_instance_update(instance)
    assert calls == ["LV-1405-0001"]


def test_an_unexpected_native_failure_is_recorded_and_never_raised(env):
    site, lifecycle = env.site, env.lifecycle
    module = importlib.import_module("asoud_erp.services.request_native_documents")
    env.monkeypatch.setattr(module, "dispatch", lambda request: (_ for _ in ()).throw(KeyError("leave_type")))
    site.add("User", "mgr@example.com")
    site.add("Has Role", "HR-1", role="HR Manager", parenttype="User", parent="mgr@example.com")
    site.add("Has Role", "HR-2", role="System Manager", parenttype="User", parent="gone@example.com")
    site.table("User")["mgr@example.com"]["enabled"] = 1
    site.add("User", "gone@example.com", enabled=0)
    instance = _running(env)
    instance.status = "Completed"
    instance.has_value_changed = lambda field: True
    lifecycle.on_instance_update(instance)
    request = site.table("ASOUD Workflow Request")["LV-1405-0001"]
    assert request["native_status"] == "Failed" and "leave_type" in request["native_error"]
    assert request["status_key"] == "approved"  # the approval is kept
    notified = {row["for_user"] for row in site.table("Notification Log").values()}
    assert notified == {site.user, "mgr@example.com"}
    lifecycle.record_native_failure("LV-1405-0001", "x" * 2000)
    assert len(request["native_error"]) == 1000


def test_deadlocks_are_not_swallowed(env):
    lifecycle = env.lifecycle
    module = importlib.import_module("asoud_erp.services.request_native_documents")
    env.monkeypatch.setattr(module, "dispatch",
                            lambda request: (_ for _ in ()).throw(env.frappe.QueryDeadlockError()))
    _running(env)
    with pytest.raises(env.frappe.QueryDeadlockError):
        lifecycle.dispatch_native_document("LV-1405-0001")


# --------------------------------------------------------------------------- admin guard


def test_admin_cannot_save_the_system_form_stage_but_can_edit_the_approver(env):
    env.seed.ensure_system_templates("Wind Power LLC")
    site = env.site
    workflow = importlib.import_module("asoud_erp.api.v1.workflow")
    stages = {row["stage_type"]: row for row in site.table("ASOUD Workflow Stage").values()
              if row["workflow_definition"] == "SYS-LEAVE-WP"}
    form = fake.FakeDoc(site, stages["User Task"])
    with pytest.raises(fake.ValidationError) as error:
        workflow._assert_form_is_editable("SYS-LEAVE-WP", form)
    assert "فرم این نوع درخواست توسط سیستم مدیریت می‌شود" in str(error.value)
    workflow._assert_form_is_editable("SYS-LEAVE-WP", fake.FakeDoc(site, stages["Approval"]))
    site.table("ASOUD Workflow Definition")["SYS-LEAVE-WP"]["is_system_template"] = 0
    workflow._assert_form_is_editable("SYS-LEAVE-WP", form)  # custom types stay editable
