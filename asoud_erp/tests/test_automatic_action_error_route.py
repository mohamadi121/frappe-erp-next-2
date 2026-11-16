"""Error-route destination in `automatic_action_runtime._finish`.

A failed automatic action may route to a human task (for correction) or to an End
stage (to terminate the process as failed). It must not silently continue to some
other stage. These tests pin the destination rule: End is allowed, a System Action
or Condition target is refused.
"""

import importlib
import json
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
        ["asoud_erp.services.automatic_action_runtime", "asoud_erp.api.v1.workflow_runtime",
         "asoud_erp.services.request_link_values"])
    module = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    runtime = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    yield module, site, runtime
    restore()


def _graph(site):
    definition = "WF-ER"
    site.add("ASOUD Workflow Definition", definition, company="WP", status="Active")
    end = site.add("ASOUD Workflow Stage", "END-1", workflow_definition=definition,
                   stage_type="End", config_json="{}")["name"]
    system = site.add("ASOUD Workflow Stage", "SA-2", workflow_definition=definition,
                      stage_type="System Action", config_json="{}")["name"]
    instance = fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-ER",
                                           workflow_definition=definition, status="Running",
                                           current_stage="SA", started_by=site.user))
    return end, system, instance


def _receipt(site, error_target):
    return fake.FakeDoc(site, site.add("ASOUD Action Execution", "RX-ER",
                                       workflow_instance="WFI-ER", workflow_stage="SA",
                                       status="Failed", action_type="Send Notification",
                                       trigger_id="TASK-1",
                                       routes_json=json.dumps({"Error": error_target}),
                                       config_json="{}"))


def test_error_route_to_end_stage_is_allowed(aar, monkeypatch):
    module, site, runtime = aar
    end, _, instance = _graph(site)
    calls = []
    monkeypatch.setattr(runtime, "_activate_stage",
                        lambda instance, stage, automatic_trigger=None: calls.append(stage.name))
    module._finish(_receipt(site, end), instance, False)
    assert calls == [end]


def test_error_route_to_user_task_is_allowed(aar, monkeypatch):
    module, site, runtime = aar
    _, _, instance = _graph(site)
    task = site.add("ASOUD Workflow Stage", "UT-1", workflow_definition="WF-ER",
                    stage_type="User Task", config_json="{}")["name"]
    calls = []
    monkeypatch.setattr(runtime, "_activate_stage",
                        lambda instance, stage, automatic_trigger=None: calls.append(stage.name))
    module._finish(_receipt(site, task), instance, False)
    assert calls == [task]


def test_error_route_to_a_system_action_is_refused(aar, monkeypatch):
    module, site, runtime = aar
    _, system, instance = _graph(site)
    monkeypatch.setattr(runtime, "_activate_stage",
                        lambda *args, **kwargs: pytest.fail("must not activate"))
    with pytest.raises(ValueError):
        module._finish(_receipt(site, system), instance, False)
