"""Pure regression: request_level enforces the office boundary (PA-055, defect 2).

``_readable_request`` calls ``request_level`` directly, so the company gate that used to
live in ``request_permission`` must live in ``request_level`` too: an owner or an
Open-task holder without company access to the request's company is NONE, not FULL.
"""

import importlib
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake

RELOADED = ["asoud_erp.services.request_access", "asoud_erp.services.certificate_access"]


@pytest.fixture
def world(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name, module in {"frappe": frappe, "frappe.utils": utils}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    access = importlib.import_module("asoud_erp.services.request_access")
    # A request owned by the current user, with an Open task for them.
    site.add("ASOUD Workflow Request", "REQ-1", company="WP", owner="sara@example.com",
             workflow_instance="WFI-1")
    site.add("ASOUD Workflow Task", "T-1", workflow_instance="WFI-1", assigned_to="sara@example.com",
             status="Open")
    site.user = "sara@example.com"
    yield types.SimpleNamespace(site=site, frappe=frappe, access=access)
    restore()


def test_owner_without_company_access_is_none(world, monkeypatch):
    monkeypatch.setattr(world.access, "company_access", lambda company, user=None: False)
    doc = world.frappe.get_doc("ASOUD Workflow Request", "REQ-1")
    assert world.access.request_level(doc) == "NONE"


def test_open_task_holder_without_company_access_is_none(world, monkeypatch):
    # A different user holds the Open task but has no company access.
    world.site.user = "other@example.com"
    monkeypatch.setattr(world.access, "company_access", lambda company, user=None: False)
    doc = world.frappe.get_doc("ASOUD Workflow Request", "REQ-1")
    assert world.access.request_level(doc) == "NONE"


def test_owner_with_company_access_is_full(world, monkeypatch):
    monkeypatch.setattr(world.access, "company_access", lambda company, user=None: True)
    doc = world.frappe.get_doc("ASOUD Workflow Request", "REQ-1")
    assert world.access.request_level(doc) == "FULL"
