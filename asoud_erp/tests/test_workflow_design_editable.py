"""Pure tests for the DocType-level design-edit backstop (PA-015).

``assert_design_editable`` is called from the Stage/Transition controllers to
refuse design writes that bypass the guarded whitelisted functions (raw
``/api/resource``, ``frappe.client``, Desk, import, bulk edit). It must refuse
while an instance is Running or the definition is Active, and skip during
install/migrate/patch/test and for ``ignore_permissions`` writes (the directive
adapter, template seeding, setup reset, and the guarded functions themselves).
"""
import importlib
import sys

import pytest

from asoud_erp.tests import _fake_site as fake


@pytest.fixture
def guard(monkeypatch):
    site = fake.Site()
    frappe, _utils = fake.install(site)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    restore = fake.isolate(["asoud_erp.services.workflow_condition_binding"])
    module = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    yield module, site, frappe
    restore()


def _doc(site, definition, ignore_permissions=False):
    return fake.FakeDoc(site, {"workflow_definition": definition,
                               "flags": fake.Dict({"ignore_permissions": ignore_permissions})})


def _definition(site, name, status):
    site.add("ASOUD Workflow Definition", name, status=status)


def _running_instance(site, definition):
    site.add("ASOUD Workflow Instance", f"wfi-{definition}", workflow_definition=definition,
             status="Running")


def test_refuses_while_an_instance_is_running(guard):
    module, site, frappe = guard
    _definition(site, "def-1", "Inactive")
    _running_instance(site, "def-1")
    with pytest.raises(frappe.ValidationError):
        module.assert_design_editable(_doc(site, "def-1"))


def test_refuses_an_active_definition(guard):
    module, site, frappe = guard
    _definition(site, "def-1", "Active")
    with pytest.raises(frappe.ValidationError):
        module.assert_design_editable(_doc(site, "def-1"))


def test_allows_an_inactive_definition_with_no_running_instance(guard):
    module, site, _ = guard
    _definition(site, "def-1", "Inactive")
    module.assert_design_editable(_doc(site, "def-1"))  # must not raise


def test_skips_ignore_permissions_writes(guard):
    # The directive adapter and template seeding write stages with
    # ignore_permissions=True (the seed creates stages on an Active definition);
    # the backstop must not refuse them.
    module, site, _ = guard
    _definition(site, "def-1", "Active")
    _running_instance(site, "def-1")
    module.assert_design_editable(_doc(site, "def-1", ignore_permissions=True))  # must not raise


def test_skips_during_test(guard):
    module, site, frappe = guard
    _definition(site, "def-1", "Active")
    _running_instance(site, "def-1")
    site_flags = frappe.flags
    site_flags.in_test = True
    try:
        module.assert_design_editable(_doc(site, "def-1"))  # must not raise
    finally:
        site_flags.in_test = None
