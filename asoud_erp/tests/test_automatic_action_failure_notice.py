"""Final-failure notification in `automatic_action_runtime._final_failure`.

When an automatic action fails with no Error route, the instance is marked Failed.
The requester (``instance.started_by``) must be notified, not only System Managers,
so a stuck request is visible to the person who owns it.
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
        ["asoud_erp.services.automatic_action_runtime", "asoud_erp.api.v1.workflow_runtime"])
    module = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    runtime = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    yield module, site, runtime
    restore()


def _receipt(site):
    return fake.FakeDoc(site, site.add("ASOUD Action Execution", "RX-FAIL",
                                       workflow_instance="WFI-FF", workflow_stage="SA",
                                       status="Failed", action_type="Send Notification",
                                       attempts=1, service_user="svc@example.com",
                                       routes_json=json.dumps({}), config_json="{}"))


def _instance(site, started_by):
    return fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-FF",
                                       workflow_definition="WF-FF", status="Running",
                                       current_stage="SA", started_by=started_by))


def _notified(site):
    return {row["for_user"] for row in site.table("Notification Log").values()}


def test_final_failure_notifies_the_initiator(aar, monkeypatch):
    module, site, runtime = aar
    monkeypatch.setattr(runtime, "_users_for_roles", lambda roles: ["sm@example.com"])
    instance = _instance(site, "initiator@example.com")
    receipt = _receipt(site)
    module._final_failure(receipt, instance)
    assert instance.status == "Failed"
    # The requester is notified, alongside the System Manager.
    assert "initiator@example.com" in _notified(site)
    assert "sm@example.com" in _notified(site)


def test_final_failure_notifies_initiator_even_without_system_managers(aar, monkeypatch):
    module, site, runtime = aar
    monkeypatch.setattr(runtime, "_users_for_roles", lambda roles: [])
    instance = _instance(site, "initiator@example.com")
    receipt = _receipt(site)
    module._final_failure(receipt, instance)
    assert instance.status == "Failed"
    assert _notified(site) == {"initiator@example.com"}
