"""Side-effect-free condition dry-run (`test_workflow_condition`) on the in-memory fake site.

It exercises the real endpoint logic (normalize, binding validation, per-row and final
evaluation) with a fake field catalog, and proves the endpoint never writes. The real
database behavior is covered by `integration_tests/test_workflow_condition_dryrun.py`.
"""

import importlib
import json
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake

RELOADED = [
    "asoud_erp.api.v1.workflow", "asoud_erp.services.request_access",
    "asoud_erp.services.erp_documents", "asoud_erp.services.workflow_condition_binding",
]

CATALOG = [
    dict(source_kind="Original", source_stage="", source_field="amount", field_type="Number", options=[]),
    dict(source_kind="Original", source_stage="", source_field="note", field_type="Text", options=[]),
]


def config(*conditions, combine="All"):
    return dict(title="شرط و مسیر", condition_version=2, combine=combine, conditions=list(conditions))


def amount_row(operator="Greater Than", value="50", **values):
    return dict(id="c1", source_kind="Original", source_stage="", source_field="amount",
                field_type="Number", operator=operator, value=value, **values)


def note_row(operator="Contains", value="فوری"):
    return dict(id="c2", source_kind="Original", source_stage="", source_field="note",
                field_type="Text", operator=operator, value=value)


class Env:
    pass


@pytest.fixture
def env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    runtime = types.ModuleType("asoud_erp.api.v1.workflow_runtime")
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    utils.cint = int
    utils.now_datetime = lambda: "now"
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming, "asoud_erp.api.v1.workflow_runtime": runtime}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED)
    site.user = "Administrator"
    site.add("ASOUD Workflow Definition", "DEF", workflow_code="DEF", company=None,
             target_doctype="ASOUD Workflow Request")
    site.add("ASOUD Workflow Stage", "GATE", workflow_definition="DEF", stage_type="Condition", config_json="{}")
    binding = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    monkeypatch.setattr(binding, "catalog", lambda definition, stage: CATALOG)
    module = importlib.import_module("asoud_erp.api.v1.workflow")
    env = Env()
    env.site, env.frappe, env.module = site, frappe, module

    def run(cfg, samples):
        return module.test_workflow_condition("DEF", "GATE", cfg, samples)

    env.run = run
    yield env
    restore()


def test_true_result(env):
    out = env.run(config(amount_row()), {"c1": "100"})
    assert out["ok"] is True
    assert out["data"]["result"] is True
    assert out["data"]["rows"] == [{"id": "c1", "result": True, "error": None}]


def test_false_result(env):
    out = env.run(config(amount_row()), {"c1": "10"})
    assert out["data"]["result"] is False
    assert out["data"]["rows"] == [{"id": "c1", "result": False, "error": None}]


@pytest.mark.parametrize("combine,expected", [("All", False), ("Any", True)])
def test_combination(env, combine, expected):
    out = env.run(config(amount_row(), note_row(), combine=combine), {"c1": "100", "c2": "عادی"})
    assert out["data"]["result"] is expected
    by_id = {row["id"]: row["result"] for row in out["data"]["rows"]}
    assert by_id == {"c1": True, "c2": False}


def test_missing_sample_marks_row_error_and_null_result(env):
    out = env.run(config(amount_row(), note_row()), {"c1": "100"})
    assert out["data"]["result"] is None
    by_id = {row["id"]: row for row in out["data"]["rows"]}
    assert by_id["c1"] == {"id": "c1", "result": True, "error": None}
    assert by_id["c2"]["result"] is None
    assert by_id["c2"]["error"] == "برای این شرط مقدار نمونه وارد نشده است."


def test_blank_text_sample_is_a_missing_error(env):
    out = env.run(config(note_row(operator="Equals")), {"c2": ""})
    assert out["data"]["result"] is None
    assert out["data"]["rows"] == [{"id": "c2", "result": None, "error": "برای این شرط مقدار نمونه وارد نشده است."}]


def test_whitespace_text_sample_is_a_missing_error(env):
    out = env.run(config(note_row(operator="Equals")), {"c2": "   "})
    assert out["data"]["result"] is None
    assert out["data"]["rows"] == [{"id": "c2", "result": None, "error": "برای این شرط مقدار نمونه وارد نشده است."}]


def test_is_empty_with_blank_sample_is_true(env):
    out = env.run(config(note_row(operator="Is Empty")), {"c2": ""})
    assert out["data"]["result"] is True
    assert out["data"]["rows"] == [{"id": "c2", "result": True, "error": None}]


def test_non_dict_config_is_a_persian_error(env):
    with pytest.raises(fake.ValidationError) as excinfo:
        env.run([1, 2], {"c1": "100"})
    assert str(excinfo.value) == "تنظیمات شرط معتبر نیست."


def test_invalid_range_is_a_validation_error(env):
    with pytest.raises(fake.ValidationError):
        env.run(config(amount_row(operator="Between", value="10", value_to="5")), {"c1": "3"})


def test_empty_operator_needs_no_sample(env):
    out = env.run(config(amount_row(operator="Is Empty")), {})
    assert out["data"]["result"] is True
    assert out["data"]["rows"] == [{"id": "c1", "result": True, "error": None}]


def test_endpoint_writes_nothing(env, monkeypatch):
    def no_write(*args, **kwargs):
        raise AssertionError("condition test must not write")

    monkeypatch.setattr(env.site, "add", no_write)
    out = env.run(config(amount_row(), note_row(), combine="Any"), {"c1": "100", "c2": "فوری"})
    assert out["data"]["result"] is True


# The runtime test below imports the real `workflow_runtime` (not the stub the dry-run
# fixture installs) so it exercises the actual `frappe.log_error` call in `_activate_stage`.
RELOADED_RT = [
    "asoud_erp.api.v1.workflow_runtime", "asoud_erp.services.workflow_condition_binding",
    "asoud_erp.services.request_access", "asoud_erp.services.erp_documents",
    "asoud_erp.services.request_link_values", "asoud_erp.api.v1.document_templates",
]


@pytest.fixture
def runtime_env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    utils.add_to_date = lambda *args, **kwargs: "now"
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED_RT)
    site.user = "Administrator"
    runtime = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    binding = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    env = Env()
    env.site, env.frappe, env.runtime, env.binding = site, frappe, runtime, binding
    yield env
    restore()


def test_failing_v2_condition_logs_with_defer_insert_and_instance_reference(runtime_env, monkeypatch):
    env = runtime_env
    config = dict(title="شرط و مسیر", condition_version=2, combine="All", conditions=[
        dict(id="c1", source_kind="Original", source_stage="", source_field="amount",
             field_type="Number", operator="Greater Than", value="50")])
    instance = types.SimpleNamespace(name="WFI-0001", workflow_definition="DEF", status='Running',
                                     reference_doctype=None, reference_name=None,
                                     current_stage=None, save=lambda **kwargs: None)
    stage = types.SimpleNamespace(name="GATE", stage_type="Condition", config_json=json.dumps(config))
    monkeypatch.setattr(env.binding, "catalog", lambda definition, stage: [])

    def boom(cfg, available):
        raise ValueError("شرط ۱: منبع یا فیلد حذف شده یا در این مسیر معتبر نیست.")

    monkeypatch.setattr(env.binding, "validate_bindings", boom)
    calls = []
    monkeypatch.setattr(env.frappe, "log_error", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(fake.ValidationError):
        env.runtime._activate_stage(instance, stage)
    assert len(calls) == 1
    call = calls[0]
    assert call["defer_insert"] is True
    assert call["reference_doctype"] == "ASOUD Workflow Instance"
    assert call["reference_name"] == "WFI-0001"
    assert call["title"] == "خطا در ارزیابی شرط گردش کار"
    assert "شرط ۱" in call["message"]
