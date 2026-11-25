"""B2: no route may lead into the Start stage, through any way of creating one."""

import importlib
import json

import pytest

from asoud_erp.services.workflow_contract import START_ROUTE, activation_requirements
from asoud_erp.tests import _fake_site as fake

RELOADED = [
    "asoud_erp.api.v1.workflow", "asoud_erp.services.request_access",
    "asoud_erp.services.erp_documents", "asoud_erp.services.workflow_condition_binding",
]


@pytest.fixture
def env(monkeypatch):
    import sys
    import types

    site = fake.Site()
    frappe, utils = fake.install(site)
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    utils.cint = int
    utils.now_datetime = lambda: "now"
    runtime = types.ModuleType("asoud_erp.api.v1.workflow_runtime")
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming, "asoud_erp.api.v1.workflow_runtime": runtime}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    site.user = "Administrator"
    frappe.db.sql = lambda *args, **kwargs: None
    site.add("ASOUD Workflow Definition", "DEF", workflow_code="DEF", company=None, status="Inactive",
             target_doctype="ASOUD Workflow Request")
    for name, kind in (("START", "Start"), ("TASK", "User Task"), ("ACTION", "System Action")):
        site.add("ASOUD Workflow Stage", name, workflow_definition="DEF", stage_type=kind, config_json="{}")
    binding = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    monkeypatch.setattr(binding, "assert_editable", lambda definition: None)  # editability has its own tests
    module = importlib.import_module("asoud_erp.api.v1.workflow")
    module._touch_workflow = lambda definition: None
    module._design_payload = lambda definition: {}
    yield types.SimpleNamespace(site=site, module=module)
    restore()


@pytest.mark.parametrize("source", ["TASK", "ACTION"])
def test_connecting_a_non_condition_stage_to_start_is_refused(env, source):
    with pytest.raises(fake.ValidationError) as caught:
        env.module.connect_workflow_stages("DEF", source, "START", "ادامه")
    assert str(caught.value) == START_ROUTE
    assert not env.site.table("ASOUD Workflow Transition")


def test_other_destinations_still_connect(env):
    env.site.add("ASOUD Workflow Stage", "NEXT", workflow_definition="DEF", stage_type="User Task", config_json="{}")
    env.module.connect_workflow_stages("DEF", "TASK", "NEXT", "ادامه")
    assert len(env.site.table("ASOUD Workflow Transition")) == 1


def row(name, kind):
    return dict(name=name, stage_type=kind, stage_title=name, config_json=json.dumps({}),
                configuration_status="Complete")


def test_activation_rejects_a_route_into_start():
    stages = [row("S", "Start"), row("T", "User Task"), row("E", "End")]
    edges = [dict(name="a", from_stage="S", to_stage="T", condition_json="{}"),
             dict(name="b", from_stage="T", to_stage="E", condition_json="{}"),
             dict(name="c", from_stage="T", to_stage="S", condition_json="{}")]
    assert START_ROUTE in activation_requirements(stages, edges)
    assert START_ROUTE not in activation_requirements(stages, edges[:2])
