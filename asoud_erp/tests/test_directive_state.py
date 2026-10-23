"""Directive status summary as a pure function; frappe is stubbed so no site is needed."""

import importlib
import sys
import types
from types import SimpleNamespace

import pytest

MODULE = "asoud_erp.api.v1.directives"
UTILS = ("get_datetime", "get_fullname", "getdate", "now_datetime", "nowdate", "strip_html")


@pytest.fixture
def directives(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.session = SimpleNamespace(user="Administrator")
    frappe.whitelist = lambda *args, **kwargs: (lambda function: function)
    utils = types.ModuleType("frappe.utils")
    for name in UTILS:
        setattr(utils, name, lambda *args, **kwargs: None)
    frappe.utils = utils
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    sys.modules.pop(MODULE, None)
    module = importlib.import_module(MODULE)
    yield module
    sys.modules.pop(MODULE, None)


def _doc(status, *states):
    recipients = [SimpleNamespace(recipient_type="To", directive_state=state, user=f"user{i}@example.com")
                  for i, state in enumerate(states)]
    return SimpleNamespace(status=status, recipients=recipients)


@pytest.mark.parametrize(
    ("status", "states", "expected"),
    [
        ("Draft", (), "Draft"),
        ("Closed", ("Approved",), "Closed"),
        ("Sent", ("Pending", "Pending"), "Issued"),
        ("Sent", ("Pending", "In Progress"), "In Progress"),
        ("Sent", ("In Progress",), "In Progress"),
        ("Sent", ("Approved", "Awaiting Review"), "Awaiting Review"),
        ("Sent", ("Approved", "Returned"), "Returned"),
        ("Sent", ("Approved", "Approved"), "Approved"),
        ("Sent", ("Transferred", "Approved"), "Approved"),
        ("Sent", ("Transferred", "Pending"), "Issued"),
    ],
)
def test_state_summarises_active_recipients(directives, status, states, expected):
    assert directives._state(_doc(status, *states)) == expected
