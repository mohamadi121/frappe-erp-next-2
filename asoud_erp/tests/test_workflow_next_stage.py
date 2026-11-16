"""Route selection in `workflow_runtime._next_stage` on the in-memory fake site.

The runtime action is the English canonical name (``Complete``/``Approve``/...) while a
designer may label a route in Persian (e.g. «ادامه»). The translation must apply to every
source stage type, not only Approval, or a multi-route User Task / System Action stage
would never match and the workflow would stall with "no next stage".
"""

import importlib
import json
import sys

import pytest

from asoud_erp.tests import _fake_site as fake

# frappe.utils names that `workflow_runtime` and its imports read at module load.
_EXTRA_UTILS = [
    "add_to_date", "cint", "cstr", "get_first_day", "get_last_day", "date_diff", "add_days",
    "get_weekday", "formatdate", "get_url", "random_string", "get_site_name", "get_site_url",
    "get_system_timezone", "is_scheduler_inactive", "get_time", "get_time_delta", "now",
    "today", "get_datetime", "money_in_words", "format_money", "get_link_to_form",
]


@pytest.fixture
def runtime(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name in _EXTRA_UTILS:
        if not hasattr(utils, name):
            setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    restore = fake.isolate(["asoud_erp.api.v1.workflow_runtime",
                           "asoud_erp.services.request_link_values"])
    module = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    yield module, site
    restore()


def _graph(site, source_type, edges):
    """A definition with one source stage and one destination per edge label."""
    definition = "WF-NS"
    site.add("ASOUD Workflow Definition", definition, company="WP", status="Active")
    source = site.add("ASOUD Workflow Stage", "SRC", workflow_definition=definition,
                      stage_type=source_type, config_json="{}")["name"]
    destinations = {}
    for index, (label, condition) in enumerate(edges, 1):
        dest = site.add("ASOUD Workflow Stage", f"DST-{index}", workflow_definition=definition,
                        stage_type="End", config_json="{}")["name"]
        destinations[label] = dest
        site.add("ASOUD Workflow Transition", f"EDGE-{index}", workflow_definition=definition,
                 from_stage=source, to_stage=dest, transition_label=label,
                 condition_json=json.dumps(condition, ensure_ascii=False), sequence_no=index)
    instance = fake.FakeDoc(site, site.add("ASOUD Workflow Instance", "WFI-NS",
                                           workflow_definition=definition, status="Running",
                                           current_stage=source, started_by=site.user))
    return source, instance, destinations


def test_user_task_persian_continue_label_matches_complete(runtime):
    module, site = runtime
    source, instance, destinations = _graph(
        site, "User Task", [("ادامه", {}), ("رد", {"action": "Reject"})])
    selected = module._next_stage(instance, source, "Complete")
    assert selected is not None
    assert selected.name == destinations["ادامه"]


def test_system_action_persian_continue_label_matches_complete(runtime):
    module, site = runtime
    source, instance, destinations = _graph(
        site, "System Action", [("ادامه", {}), ("خطا", {"action": "Error"})])
    selected = module._next_stage(instance, source, "Complete")
    assert selected is not None
    assert selected.name == destinations["ادامه"]


def test_approval_persian_labels_still_match(runtime):
    module, site = runtime
    source, instance, destinations = _graph(
        site, "Approval", [("تأیید", {"action": "Approve"}), ("رد", {"action": "Reject"})])
    assert module._next_stage(instance, source, "Approve").name == destinations["تأیید"]
    assert module._next_stage(instance, source, "Reject").name == destinations["رد"]


def test_unmatched_action_on_multi_route_user_task_returns_none(runtime):
    module, site = runtime
    source, instance, _ = _graph(
        site, "User Task", [("ادامه", {}), ("رد", {"action": "Reject"})])
    # A forward action with no matching route must not fall back to a default.
    assert module._next_stage(instance, source, "Reject") is not None
    assert module._next_stage(instance, source, "Approve") is None
