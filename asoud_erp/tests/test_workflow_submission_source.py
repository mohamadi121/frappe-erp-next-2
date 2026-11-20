"""route() must not take FOR UPDATE locks on definitions or stage rows (PA-001)."""
import importlib
import json
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake


@pytest.fixture
def env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    utils.cint = int
    utils.now_datetime = lambda: "now"
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate([
        "asoud_erp.services.workflow_submission_source",
        "asoud_erp.services.workflow_submission_policy",
        "asoud_erp.services.request_access",
        "asoud_erp.services.erp_documents",
        "asoud_erp.services.form_schema",
        "asoud_erp.services.workflow_condition",
        "asoud_erp.services.workflow_condition_binding",
    ])
    site.user = "Administrator"
    site.roles = ["System Manager"]
    # One bound workflow definition, Active/Ready, matching the form revision.
    site.add("ASOUD Workflow Definition", "WF-1", company="Co", status="Active",
             readiness_status="Ready", source_form="FORM-1", source_revision="REV-1",
             target_doctype="ASOUD Workflow Request")
    site.add("ASOUD Workflow Stage", "ST-1", workflow_definition="WF-1",
             stage_type="Start", config_json="{}")
    site.add("ASOUD Workflow Stage", "ST-2", workflow_definition="WF-1",
             stage_type="User Task", config_json="{}")
    # Capture every raw SQL string passed to frappe.db.sql.
    sql_calls = []

    def recording_sql(query, *args, **kwargs):
        sql_calls.append(query)
        # The definition query returns one matching row so route() proceeds to
        # read the stage rows; the stage read must not be a locked raw SQL call.
        if "ASOUD Workflow Definition" in query:
            return [fake.Dict(name="WF-1", company="Co", status="Active",
                               readiness_status="Ready", source_revision="REV-1")]
        return []

    monkeypatch.setattr(frappe.db, "sql", recording_sql, raising=False)
    module = importlib.import_module("asoud_erp.services.workflow_submission_source")
    env = types.SimpleNamespace(site=site, frappe=frappe, module=module, sql_calls=sql_calls)
    yield env
    restore()


def test_route_does_not_use_for_update(env):
    """PA-001: route() must not take FOR UPDATE locks on definitions or stage rows."""
    revision = types.SimpleNamespace(name="REV-1", schema_json=json.dumps(
        {"kind": "Request", "title": "Test", "sections": [
            {"id": "main", "title": "Info", "fields": [
                {"key": "note", "label": "Note", "type": "Text", "required": True}]}]}))
    form_doc = types.SimpleNamespace(name="FORM-1", company="Co")
    env.module.route(form_doc, revision, {"note": "hello"})
    # The stage rows must have been read (route() reached the routing decision).
    assert env.sql_calls, "route() did not read the bound definitions"
    for query in env.sql_calls:
        assert "for update" not in query.lower(), (
            f"route() used FOR UPDATE in: {query}")


def test_explicit_conditional_cannot_use_available_only_record_fallback(env):
    env.site.add('ASOUD Workflow Stage', 'ST-1', workflow_definition='WF-1', stage_type='Start',
        config_json=json.dumps({'submission_source': {'form': 'FORM-1', 'revision': 'REV-1'},
                                'source_route': 'Available'}))
    schema = {'kind': 'Request', 'workflow_mode': 'Conditional', 'sections': [
        {'id': 'main', 'fields': [{'key': 'note', 'type': 'Text', 'label': 'شرح'}]}]}
    revision = types.SimpleNamespace(name='REV-1', schema_json=json.dumps(schema))
    form = types.SimpleNamespace(name='FORM-1', company='Co')
    with pytest.raises(env.frappe.ValidationError, match='هیچ مسیر معتبر'):
        env.module.route(form, revision, {'note': 'عادی'})
