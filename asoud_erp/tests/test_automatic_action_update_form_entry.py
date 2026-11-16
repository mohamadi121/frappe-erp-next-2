"""Update Fields on an ``ASOUD Form Entry`` in `automatic_action_runtime._update`.

Form data lives in the ``values_json`` column, not in document fields. A plain
``doc.update(values)`` would silently drop every mapped field, so the automatic
action must merge the mapped values into ``values_json`` and re-validate them against
the form's published schema (the same validator the submission path uses).
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

SCHEMA = {
    "kind": "Request",
    "title": "فرم آزمایشی",
    "sections": [{"id": "main", "title": "اصلی", "fields": [
        {"key": "amount", "label": "مبلغ", "type": "Money"},
        {"key": "note", "label": "توضیح", "type": "Text"},
    ]}],
}


@pytest.fixture
def aar(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    for name in _EXTRA_UTILS:
        if not hasattr(utils, name):
            setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    restore = fake.isolate(["asoud_erp.services.automatic_action_runtime",
                           "asoud_erp.services.form_schema"])
    module = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    yield module, site
    restore()


def _entry(site):
    site.add("ASOUD Form Revision", "REV-1", schema_json=json.dumps(SCHEMA, ensure_ascii=False))
    return fake.FakeDoc(site, site.add("ASOUD Form Entry", "FE-1", form="FORM-1",
                                       revision="REV-1", company="WP",
                                       values_json=json.dumps({"amount": "10", "note": "ابتدایی"},
                                                              ensure_ascii=False)))


def test_update_form_entry_writes_values_json(aar):
    module, site = aar
    entry = _entry(site)
    module._update(entry, {"amount": "25", "note": "به‌روزرسانی"}, "WP")
    stored = json.loads(entry.values_json)
    assert stored["amount"] == "25"
    assert stored["note"] == "به‌روزرسانی"


def test_update_form_entry_merges_with_existing_values(aar):
    module, site = aar
    entry = _entry(site)
    # Only one field is mapped; the other keeps its stored value.
    module._update(entry, {"amount": "40"}, "WP")
    stored = json.loads(entry.values_json)
    assert stored["amount"] == "40"
    assert stored["note"] == "ابتدایی"


def test_update_form_entry_rejects_unknown_field(aar):
    module, site = aar
    entry = _entry(site)
    with pytest.raises(Exception):
        module._update(entry, {"not_a_field": "x"}, "WP")
