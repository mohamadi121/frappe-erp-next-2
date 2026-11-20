"""Pure regression: task attachments on a standard reference document (PA-046).

Runs the real ``workflow_record_permission`` against the in-memory fake site. When a
workflow instance references a standard ERPNext document (e.g. Purchase Order), a task
attachment on it is readable exactly when the user may read that document, instead of
always being denied.
"""

import pytest

from asoud_erp.tests import _fake_site as fake
from asoud_erp.tests._workflow_access_world import make_world


def _instance(site, reference_doctype, reference_name):
    return fake.FakeDoc(site, {
        "doctype": "ASOUD Workflow Instance", "name": "WFI-1",
        "reference_doctype": reference_doctype, "reference_name": reference_name,
    })


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_standard_reference_delegates_to_native_read(world, monkeypatch):
    site = world.site
    monkeypatch.setattr(world.frappe, "has_permission", lambda *a, **k: True)
    instance = _instance(site, "Purchase Order", "PO-001")
    from asoud_erp.services import request_access

    assert request_access.workflow_record_permission(instance, "u@example.com", "read") is True


def test_standard_reference_denied_without_native_read(world, monkeypatch):
    site = world.site
    monkeypatch.setattr(world.frappe, "has_permission", lambda *a, **k: False)
    instance = _instance(site, "Purchase Order", "PO-001")
    from asoud_erp.services import request_access

    assert request_access.workflow_record_permission(instance, "u@example.com", "read") is False


def test_standard_reference_without_name_is_denied(world, monkeypatch):
    site = world.site
    monkeypatch.setattr(world.frappe, "has_permission", lambda *a, **k: True)
    instance = _instance(site, "Purchase Order", None)
    from asoud_erp.services import request_access

    assert request_access.workflow_record_permission(instance, "u@example.com", "read") is False
