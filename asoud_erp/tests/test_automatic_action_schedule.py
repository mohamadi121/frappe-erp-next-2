"""Receipt idempotency in `automatic_action_runtime.schedule` on the in-memory fake site.

The receipt key is ``hash(instance|stage|trigger)``. The trigger is the completing task's
name (``source_task.name``) for a human-driven entry, and ``_activate_stage`` always inserts
a *new* task on every activation (``workflow_runtime._activate_stage``). So a
return-for-correction followed by a resubmit re-enters the automatic stage with a fresh task
name, i.e. a fresh trigger, and the key does not repeat. These tests pin that the guard is
keyed on the trigger: a genuine repeated trigger with a terminal receipt still raises, while
the fresh trigger that a re-entry produces schedules a new receipt.
"""

import hashlib
import importlib
import sys

import pytest

from asoud_erp.tests import _fake_site as fake

_EXTRA_UTILS = [
    "add_to_date", "cint", "cstr", "get_first_day", "get_last_day", "date_diff", "add_days",
    "get_weekday", "formatdate", "get_url", "random_string", "get_site_name", "get_site_url",
    "get_system_timezone", "is_scheduler_inactive", "get_time", "get_time_delta", "now",
    "today", "get_datetime", "money_in_words", "format_money", "get_link_to_form",
]


@pytest.fixture
def aar(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name in _EXTRA_UTILS:
        if not hasattr(utils, name):
            setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    restore = fake.isolate(
        ["asoud_erp.services.automatic_action_runtime", "asoud_erp.api.v1.workflow_runtime"])
    module = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    yield module, site
    restore()


def _setup(site):
    definition = "WF-AA"
    site.add("ASOUD Workflow Definition", definition, company="WP", status="Active")
    stage = fake.FakeDoc(site, site.add("ASOUD Workflow Stage", "SA",
                                        workflow_definition=definition,
                                        stage_type="System Action", config_json="{}"))
    instance = fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-AA",
                                           workflow_definition=definition, status="Running",
                                           current_stage=stage.name, started_by=site.user))
    return stage, instance


def _key(instance, stage, trigger):
    return hashlib.sha256(f"{instance.name}|{stage.name}|{trigger}".encode()).hexdigest()


def _receipts(site):
    return len(site.table("ASOUD Action Execution"))


def test_reentry_with_fresh_trigger_schedules_a_new_receipt(aar, monkeypatch):
    module, site = aar
    monkeypatch.setattr(module, "service_user", lambda company: "svc@example.com")
    monkeypatch.setattr(module, "_company", lambda instance: "WP")
    stage, instance = _setup(site)
    config = {"action_type": "Send Notification", "operation": {}, "execution": {}}
    # First pass through the automatic stage, keyed on the original form task.
    site.add("ASOUD Action Execution", _key(instance, stage, "TASK-0001"),
             status="Succeeded", workflow_instance=instance.name, workflow_stage=stage.name)
    # A return-for-correction re-opens the form as a NEW task; the resubmit re-enters the
    # automatic stage with that fresh task name. The key differs, so no collision.
    module.schedule(instance, stage, config, trigger="TASK-0003")
    assert _receipts(site) == 2


def test_genuine_duplicate_trigger_with_terminal_receipt_still_raises(aar, monkeypatch):
    module, site = aar
    monkeypatch.setattr(module, "service_user", lambda company: "svc@example.com")
    monkeypatch.setattr(module, "_company", lambda instance: "WP")
    stage, instance = _setup(site)
    config = {"action_type": "Send Notification", "operation": {}, "execution": {}}
    # A previous receipt for this exact trigger is already terminal.
    site.add("ASOUD Action Execution", _key(instance, stage, "TASK-0001"),
             status="Succeeded", workflow_instance=instance.name, workflow_stage=stage.name)
    with pytest.raises(ValueError):
        module.schedule(instance, stage, config, trigger="TASK-0001")
