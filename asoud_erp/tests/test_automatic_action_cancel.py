"""Cancellation of queued automatic actions in `automatic_action_runtime.cancel`.

When a requester withdraws a request, any automatic action still queued for that
instance must be cancelled so it does not fire in the background. A receipt that is
already Running is owned by a worker holding the row lock; the worker's own
instance-status check cancels it, so `cancel` must leave it alone.
"""

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
    restore = fake.isolate(["asoud_erp.services.automatic_action_runtime"])
    module = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    yield module, site
    restore()


def _instance(site):
    return fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-CX",
                                       workflow_definition="WF-CX", status="Running",
                                       started_by=site.user))


def test_cancel_clears_queued_receipts(aar):
    module, site = aar
    instance = _instance(site)
    site.add("ASOUD Action Execution", "RX-PENDING", workflow_instance=instance.name,
             status="Pending")
    site.add("ASOUD Action Execution", "RX-RETRY", workflow_instance=instance.name,
             status="Retry Pending")
    # A terminal receipt from an earlier pass is already settled; it is not queued.
    site.add("ASOUD Action Execution", "RX-DONE", workflow_instance=instance.name,
             status="Succeeded")
    cancelled = module.cancel(instance)
    assert cancelled == 2
    assert site.table("ASOUD Action Execution")["RX-PENDING"]["status"] == "Cancelled"
    assert site.table("ASOUD Action Execution")["RX-RETRY"]["status"] == "Cancelled"
    assert site.table("ASOUD Action Execution")["RX-DONE"]["status"] == "Succeeded"


def test_cancel_leaves_a_running_receipt_to_the_worker(aar):
    module, site = aar
    instance = _instance(site)
    site.add("ASOUD Action Execution", "RX-RUNNING", workflow_instance=instance.name,
             status="Running")
    cancelled = module.cancel(instance)
    assert cancelled == 0
    assert site.table("ASOUD Action Execution")["RX-RUNNING"]["status"] == "Running"


def test_cancel_is_scoped_to_the_instance(aar):
    module, site = aar
    instance = _instance(site)
    other = fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-OTHER",
                                        workflow_definition="WF-CX", status="Running",
                                        started_by=site.user))
    site.add("ASOUD Action Execution", "RX-MINE", workflow_instance=instance.name,
             status="Pending")
    site.add("ASOUD Action Execution", "RX-THEIRS", workflow_instance=other.name,
             status="Pending")
    module.cancel(instance)
    assert site.table("ASOUD Action Execution")["RX-MINE"]["status"] == "Cancelled"
    assert site.table("ASOUD Action Execution")["RX-THEIRS"]["status"] == "Pending"
