"""Phase 4 (return for correction) and Phase 8 (reject/return routes) pure regressions.

The result-form loader must refuse a Stage-kind form: a Stage form is the
supplementary-stage concept (bound via `supplementary_form` on Approval stages)
and must not be reused as a task result form.
"""
import importlib
import sys
import types

import pytest


def _form(kind):
    return types.SimpleNamespace(kind=kind, name="f", company="Test Company", disabled=0,
                                 active_revision="rev-1")


@pytest.fixture
def loader(monkeypatch):
    """Patch `frappe`, `company_for` and the forms loader so `form_schema` runs without a bench."""
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.db = types.SimpleNamespace(exists=lambda *args: True, get_value=lambda *args: None)
    frappe.session = types.SimpleNamespace(user="test@example.com")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    # Stub the whole forms module: it pulls in the full frappe stack, which a pure test must not.
    forms = types.ModuleType("asoud_erp.api.v1.forms")
    forms.load = lambda name, edit=False: _form("Request")
    forms.revision = lambda doc, name=None: types.SimpleNamespace(
        schema_json='{"kind": "Request", "title": "نتیجه", "sections": []}')
    forms.migrate_schema = lambda schema: schema
    forms.allowed = lambda schema, company: True
    monkeypatch.setitem(sys.modules, "asoud_erp.api.v1.forms", forms)
    module = importlib.import_module("asoud_erp.services.workflow_user_action")
    monkeypatch.setattr(module, "company_for", lambda definition: "Test Company")
    return module, forms


def test_result_form_refuses_a_stage_kind_form(loader, monkeypatch):
    module, forms = loader
    monkeypatch.setattr(forms, "load", lambda name, edit=False: _form("Stage"))
    config = {"result_mode": "Form", "result_form": {"form": "f", "revision": "rev-1"}}
    with pytest.raises(ValueError) as error:
        module.form_schema("def", config)
    assert "فرم تکمیلی مرحله" in str(error.value)


def test_result_form_accepts_a_request_kind_form(loader):
    module, _forms = loader
    config = {"result_mode": "Form", "result_form": {"form": "f", "revision": "rev-1"}}
    schema, name, company = module.form_schema("def", config)
    assert name == "f"
    assert company == "Test Company"
    assert schema["kind"] == "Request"
