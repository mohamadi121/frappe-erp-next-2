import importlib
import sys
import types

import pytest


@pytest.fixture
def env(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.db = types.SimpleNamespace(exists=lambda *args: True, get_value=lambda *args: None)
    frappe.session = types.SimpleNamespace(user="test@example.com")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    schema = importlib.import_module("asoud_erp.services.form_schema")
    importlib.reload(schema)
    catalog = importlib.import_module("asoud_erp.services.stage_form_catalog")
    importlib.reload(catalog)
    return types.SimpleNamespace(schema=schema, catalog=catalog)


def test_all_five_stage_presets_validate(env):
    from asoud_erp.services.stage_form_catalog import catalog

    presets = catalog()
    assert set(presets) == {
        'stage_request_checklist', 'stage_expert_opinion', 'stage_hr_review',
        'stage_finance_review', 'stage_operations_review',
    }
    for key, preset in presets.items():
        assert preset['kind'] == 'Stage'
        assert preset['usage'] == 'approval'
        env.schema.validate_schema(preset)


def test_stage_kind_is_accepted_and_others_still_valid(env):
    base = {
        "kind": "Stage", "title": "فرم مرحله",
        "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "note", "label": "توضیح", "type": "LongText"}]}],
    }
    assert env.schema.validate_schema(base)["kind"] == "Stage"
    for kind in ("Request", "Document"):
        assert env.schema.validate_schema({**base, "kind": kind})["kind"] == kind
    with pytest.raises(ValueError, match="عنوان و نوع فرم"):
        env.schema.validate_schema({**base, "kind": "Unknown"})


def test_usage_key_is_optional_and_bounded(env):
    base = {
        "kind": "Stage", "title": "فرم مرحله",
        "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "note", "label": "توضیح", "type": "LongText"}]}],
    }
    # Absent usage is fine.
    assert "usage" not in env.schema.validate_schema(base)
    # A short string is kept.
    assert env.schema.validate_schema({**base, "usage": "approval"})["usage"] == "approval"
    # Over 40 characters or a non-string is rejected.
    for bad in ("x" * 41, 5, ["approval"]):
        with pytest.raises(ValueError, match="کاربرد فرم"):
            env.schema.validate_schema({**base, "usage": bad})


def test_stage_catalog_identity_is_stable_and_scoped(env):
    from asoud_erp.services.stage_form_catalog import builtin_key, catalog, form_name

    names = {form_name('A', key) for key in catalog()}
    assert len(names) == 5
    assert names.isdisjoint({form_name('B', key) for key in catalog()})
    for key in catalog():
        assert builtin_key('A', form_name('A', key)) == key
    assert builtin_key('B', form_name('A', 'leave')) is None


def test_stage_catalog_rows_are_virtual_until_materialized(env):
    from asoud_erp.services.stage_form_catalog import catalog_rows, form_name

    rows = catalog_rows('A', [])
    assert len(rows) == 5
    assert all(row['kind'] == 'Stage' and row['builtin_pending'] and row['draft_version'] == 0 for row in rows)
    # A materialized (or disabled tombstone) identity never reappears as a virtual row.
    existing = [form_name('A', 'stage_hr_review')]
    remaining = catalog_rows('A', existing)
    assert len(remaining) == 4
    assert all(row['name'] not in existing for row in remaining)


def test_stage_names_do_not_collide_with_hr_catalog(env):
    from asoud_erp.services.hr_form_catalog import form_name as hr_name
    from asoud_erp.services.stage_form_catalog import catalog
    from asoud_erp.services.stage_form_catalog import form_name as stage_name

    hr = {hr_name('A', key) for key in ['leave', 'mission', 'overtime']}
    stage = {stage_name('A', key) for key in catalog()}
    assert hr.isdisjoint(stage)
