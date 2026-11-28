"""Pure wiring test (F-4): a specialised HR module's ``on_instance_update`` routes a failed
finalization through the shared guard, so the entry is marked Failed with a Persian reason and
the approval (instance status) is untouched. Uses the in-memory fake site, not a real bench."""

import importlib
import json
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake

RELOADED = ["asoud_erp.services.hiring_order_workflow", "asoud_erp.services.completion_guard"]


@pytest.fixture
def env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    module = importlib.import_module("asoud_erp.services.hiring_order_workflow")
    env = types.SimpleNamespace(site=site, frappe=frappe, module=module, monkeypatch=monkeypatch)
    yield env
    restore()


def _seed(env, *, finalize_raises):
    site = env.site
    comp = "Wind Power LLC"
    definition = "DEF-HIRE"
    request = "REQ-HIRE-1"
    instance = "WFI-HIRE-1"
    entry = "ENTRY-HIRE-1"
    site.add("ASOUD Workflow Request", request, company=comp, status="Submitted")
    site.add("ASOUD Workflow Instance", instance, workflow_definition=definition, status="Completed",
             reference_doctype="ASOUD Workflow Request", reference_name=request)
    site.add("ASOUD Form Entry", entry, reference_doctype="ASOUD Hiring Order", reference_name=request,
             company=comp, values_json=json.dumps({
                 "status": "pending", "workflow_instance": instance, "workflow_request": request,
                 "template_snapshot": {"workflow": definition}, "revision": 1}, ensure_ascii=False))
    if finalize_raises:
        env.monkeypatch.setattr(env.module, "_finalize",
                                lambda data, company: (_ for _ in ()).throw(KeyError("payroll.base_salary")))
    return instance, entry


def test_failed_finalization_marks_entry_failed_and_keeps_the_approval(env):
    instance, entry = _seed(env, finalize_raises=True)
    doc = types.SimpleNamespace(reference_doctype="ASOUD Workflow Request", reference_name="REQ-HIRE-1",
                                name=instance, workflow_definition="DEF-HIRE")
    env.module.on_instance_update(doc)  # must not raise: the approval survives the failure
    stored = json.loads(env.site.table("ASOUD Form Entry")[entry]["values_json"])
    assert stored["status"] == "failed"
    assert stored["status_label"] == "ناموفق"
    assert "payroll.base_salary" not in stored["failure_reason"]  # raw key never leaks
    assert any("۰" <= ch <= "۹" or "؀" <= ch <= "ۿ" for ch in stored["failure_reason"])  # Persian reason
    assert stored["revision"] == 2
    # The approval is kept: the instance is still Completed, not Failed.
    assert env.site.table("ASOUD Workflow Instance")[instance]["status"] == "Completed"


def test_successful_finalization_finalizes_the_entry(env):
    instance, entry = _seed(env, finalize_raises=False)
    doc = types.SimpleNamespace(reference_doctype="ASOUD Workflow Request", reference_name="REQ-HIRE-1",
                                name=instance, workflow_definition="DEF-HIRE")
    env.module.on_instance_update(doc)
    stored = json.loads(env.site.table("ASOUD Form Entry")[entry]["values_json"])
    assert stored["status"] == "final"
    assert "failure_reason" not in stored
    assert stored["number"].startswith("HIRE-")
