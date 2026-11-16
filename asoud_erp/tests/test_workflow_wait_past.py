"""Recoverable past-date handling in `workflow_wait._mark_past`.

A past due date under the Error policy is a business condition (the date is in the
past), not a technical failure. The old code called ``failed`` and burned the instance
to a terminal ``Failed`` state. Now the wait is parked: the instance stays ``Running``
and recoverable (the owner can correct the source date or cancel the request).
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


def _snapshot(**overrides):
    base = {"state": "Waiting", "stage": "WAIT-1",
            "due_utc": "2001-01-01T09:00:00+00:00",
            "config": {"wait_type": "Date", "past_policy": "Error"}}
    base.update(overrides)
    return base


def test_mark_past_parks_the_instance_without_burning_it(waits):
    module, site = waits
    instance = _instance(site)
    module._mark_past(instance, _snapshot())
    # The instance is NOT terminal: it stays Running and recoverable.
    assert instance.status == "Running"
    assert instance.completed_on is None
    assert json.loads(instance.wait_snapshot_json)["state"] == "Past"
    # A non-Recalculate parked wait is not polled by the dispatcher.
    assert instance.wait_due_utc is None


def test_mark_past_keeps_due_for_a_recalculate_wait(waits):
    module, site = waits
    instance = _instance(site)
    snapshot = _snapshot(config={"wait_type": "FormDate", "past_policy": "Error",
                                 "date_change_policy": "Recalculate"})
    module._mark_past(instance, snapshot)
    # A Recalculate parked wait keeps its (past) due so the dispatcher re-checks it
    # after the source date is corrected.
    assert instance.status == "Running"
    assert instance.wait_due_utc is not None


def test_mark_past_audits_and_notifies_the_owner(waits):
    module, site = waits
    instance = _instance(site)
    module._mark_past(instance, _snapshot())
    actions = [row["action"] for row in site.table("ASOUD Workflow Activity").values()]
    assert "Wait Past Date" in actions
    notified = {row["for_user"] for row in site.table("Notification Log").values()}
    assert "owner@example.com" in notified
