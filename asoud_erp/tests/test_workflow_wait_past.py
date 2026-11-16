"""Past-date handling in `workflow_wait` under the Error policy.

A past due date is a business condition (the date is in the past), not a technical
failure. It is only recoverable when the wait recalculates from a source date
(``date_change_policy == 'Recalculate'``), because the dispatcher re-checks it after the
source date is corrected. Any other wait has nothing that would wake it, so parking it
would leave the instance ``Running`` forever; such a wait instead fails with a business
reason and the requester is notified.
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
def waits(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name in _EXTRA_UTILS:
        if not hasattr(utils, name):
            setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    restore = fake.isolate(
        ["asoud_erp.services.workflow_wait", "asoud_erp.api.v1.workflow_runtime",
         "asoud_erp.services.request_link_values"])
    module = importlib.import_module("asoud_erp.services.workflow_wait")
    yield module, site
    restore()


def _instance(site, started_by="owner@example.com"):
    return fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-PAST",
                                       workflow_definition="WF-PAST", status="Running",
                                       current_stage="WAIT-1", started_by=started_by))


def _snapshot(config):
    return {"state": "Waiting", "stage": "WAIT-1",
            "due_utc": "2001-01-01T09:00:00+00:00", "config": config}


def _recalculate():
    return {"wait_type": "FormDate", "past_policy": "Error", "date_change_policy": "Recalculate"}


def _notified(site):
    return {row["for_user"] for row in site.table("Notification Log").values()}


def test_handle_past_parks_a_recalculate_wait(waits):
    module, site = waits
    instance = _instance(site)
    module._handle_past(instance, _snapshot(_recalculate()))
    # The instance is NOT terminal: it stays Running and recoverable.
    assert instance.status == "Running"
    assert instance.completed_on is None
    assert json.loads(instance.wait_snapshot_json)["state"] == "Past"
    # A Recalculate parked wait keeps its (past) due so the dispatcher re-checks it.
    assert instance.wait_due_utc is not None


def test_handle_past_fails_a_non_recalculate_wait(waits):
    module, site = waits
    instance = _instance(site)
    # A Date wait has no source date to correct, so it cannot recover.
    module._handle_past(instance, _snapshot({"wait_type": "Date", "past_policy": "Error"}))
    assert instance.status == "Failed"
    assert instance.completed_on is not None
    snapshot = json.loads(instance.wait_snapshot_json)
    assert snapshot["state"] == "Failed"
    # A business reason, not a technical error: it names the past date and the stop.
    assert "گذشته" in snapshot["error"]
    assert "متوقف" in snapshot["error"]


def test_handle_past_fails_a_keep_formdate_wait(waits):
    module, site = waits
    instance = _instance(site)
    # A FormDate wait that keeps its date also cannot recover from a past date.
    module._handle_past(instance, _snapshot(
        {"wait_type": "FormDate", "past_policy": "Error", "date_change_policy": "Keep"}))
    assert instance.status == "Failed"
    assert json.loads(instance.wait_snapshot_json)["state"] == "Failed"


def test_fail_past_notifies_the_owner_with_a_business_reason(waits):
    module, site = waits
    instance = _instance(site)
    module._fail_past(instance, _snapshot({"wait_type": "Date", "past_policy": "Error"}))
    assert instance.status == "Failed"
    assert "owner@example.com" in _notified(site)


def test_mark_past_keeps_due_for_a_recalculate_wait(waits):
    module, site = waits
    instance = _instance(site)
    module._mark_past(instance, _snapshot(_recalculate()))
    assert instance.status == "Running"
    assert instance.wait_due_utc is not None


def test_mark_past_audits_and_notifies_the_owner(waits):
    module, site = waits
    instance = _instance(site)
    module._mark_past(instance, _snapshot(_recalculate()))
    actions = [row["action"] for row in site.table("ASOUD Workflow Activity").values()]
    assert "Wait Past Date" in actions
    assert "owner@example.com" in _notified(site)
