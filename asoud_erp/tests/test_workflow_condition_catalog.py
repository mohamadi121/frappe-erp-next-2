"""Catalog metadata and System-field resolution for the condition field catalog."""
import importlib
import sys
import types

import pytest


def _fake_frappe():
    frappe = types.ModuleType("frappe")
    frappe.throw = lambda message, *args: (_ for _ in ()).throw(ValueError(message))
    frappe.db = types.SimpleNamespace(
        get_value=lambda *args, **kwargs: None,
        get_all=lambda *args, **kwargs: [],
        exists=lambda *args, **kwargs: False,
        sql=lambda *args, **kwargs: [],
    )
    frappe.get_doc = lambda *args, **kwargs: None
    frappe.get_all = lambda *args, **kwargs: []
    frappe.get_cached_value = lambda *args, **kwargs: None
    frappe.get_meta = lambda *args, **kwargs: None
    frappe.session = types.SimpleNamespace(user="test@example.com")
    return frappe


@pytest.fixture
def binding(monkeypatch):
    frappe = _fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    module = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    module = importlib.reload(module)
    monkeypatch.setattr(module, 'original_request_fields', lambda definition: [])
    return types.SimpleNamespace(module=module, frappe=frappe)


class _Attr:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def __getitem__(self, key):
        return self.__dict__[key]


class _Field:
    def __init__(self, data):
        self._data = data

    def as_dict(self):
        return self._data


def _catalog_frappe(frappe):
    """Start -> form User Task -> Condition, with native Original fields and a Money stage field."""
    frappe.get_doc = lambda doctype, name: _Attr(company='شرکت آزمایشی', source_revision=None,
        target_doctype='ASOUD Workflow Request')
    frappe.get_all = lambda doctype, **kw: (
        [_Attr(name='START', stage_type='Start', stage_title='شروع', config_json='{}'),
         _Attr(name='FORM', stage_type='User Task', stage_title='فرم',
               config_json='{"form_fields": [{"key": "money_amount", "label": "مبلغ", "type": "Money"}]}'),
         _Attr(name='GATE', stage_type='Condition', stage_title='شرط', config_json='{}')]
        if doctype == 'ASOUD Workflow Stage'
        else [_Attr(from_stage='START', to_stage='FORM'), _Attr(from_stage='FORM', to_stage='GATE')])
    frappe.get_cached_value = lambda doctype, name, field: 'IRR'
    frappe.get_meta = lambda doctype: _Attr(fields=[
        _Field({'fieldname': 'native_amount', 'label': 'مبلغ اصلی', 'fieldtype': 'Currency', 'options': 'currency'}),
        _Field({'fieldname': 'employee', 'label': 'کارمند', 'fieldtype': 'Link', 'options': 'Employee'}),
        _Field({'fieldname': 'unit', 'label': 'واحد', 'fieldtype': 'Link', 'options': 'Department'}),
        _Field({'fieldname': 'note', 'label': 'یادداشت', 'fieldtype': 'Data'}),
    ])


def _by_field(rows):
    return {row['source_field']: row for row in rows}


def test_catalog_adds_picker_metadata(binding):
    _catalog_frappe(binding.frappe)
    rows = _by_field(binding.module.catalog('DEF', 'GATE'))
    assert rows['employee']['value_source'] == 'employee'
    assert rows['employee']['link_doctype'] == 'Employee'
    assert rows['unit']['value_source'] == 'department'
    assert rows['unit']['link_doctype'] == 'Department'
    assert rows['note']['value_source'] is None
    assert rows['note']['link_doctype'] is None


def test_catalog_currency_is_company_default_for_money_only(binding):
    _catalog_frappe(binding.frappe)
    rows = _by_field(binding.module.catalog('DEF', 'GATE'))
    # A form-builder Money field reports the company default currency.
    assert rows['money_amount']['currency'] == 'IRR'
    assert rows['money_amount']['field_type'] == 'Number'
    # A native Currency field's currency is per document, so it stays unknown.
    assert rows['native_amount']['currency'] is None
    assert rows['native_amount']['field_type'] == 'Number'
    assert rows['note']['currency'] is None


def test_catalog_system_fields_carry_stable_metadata(binding):
    _catalog_frappe(binding.frappe)
    rows = _by_field(binding.module.catalog('DEF', 'GATE'))
    assert rows['started_by']['value_source'] == 'user'
    assert rows['started_by']['link_doctype'] == 'User'
    assert rows['started_by']['field_type'] == 'Text'
    assert rows['started_on']['value_source'] is None
    assert rows['started_on']['link_doctype'] is None
    assert rows['requester_unit']['value_source'] == 'department'
    assert rows['requester_unit']['link_doctype'] == 'Department'
    assert rows['requester_unit']['field_type'] == 'Text'
    # The instance status is always Running while a condition evaluates, so it is not offered.
    assert 'status' not in rows


def test_options_and_scalar_metadata_follow_the_real_schema(binding):
    rows = _by_field(binding.module._fields([
        {'key': 'choice', 'type': 'Select', 'options': [{'id': 'sick', 'label': 'استعلاجی'}]},
        {'key': 'old_choice', 'type': 'Choice', 'options': ['one'], 'option_labels': {'one': 'یک'}},
        {'key': 'leave', 'type': 'Link', 'source': 'Leave Type'},
        {'key': 'flag', 'type': 'Boolean'}, {'key': 'when', 'type': 'DateTime'},
        {'key': 'tags', 'type': 'MultiSelect', 'options': ['a', 'b']},
        {'key': 'private', 'type': 'Text', 'sensitive': True},
        {'key': 'table', 'type': 'Table'},
    ], 'Original'))
    assert rows['choice']['options'] == ['sick']
    assert rows['choice']['option_labels'] == {'sick': 'استعلاجی'}
    assert rows['old_choice']['option_labels'] == {'one': 'یک'}
    assert rows['leave']['link_doctype'] == 'Leave Type'
    assert rows['flag']['field_type'] == 'Boolean'
    assert rows['when']['field_type'] == 'DateTime'
    assert rows['tags']['field_type'] == 'MultiSelect'
    assert 'private' not in rows and 'table' not in rows


def _instance(**kw):
    base = dict(name='inst-1', reference_doctype='X', reference_name=None,
        started_by='user@example.com', started_on=None, status='Running')
    base.update(kw)
    return _Attr(**base)


def _system_config(field):
    return {'conditions': [{'source_kind': 'System', 'source_field': field}]}


def test_resolver_reads_requester_unit_from_the_requester_employee(binding):
    def employee(doctype, filters, field, as_dict=False):
        assert filters == {'user_id': 'user@example.com', 'company': 'company-a', 'status': 'Active'}
        return {'department': 'HR'}
    binding.frappe.db.get_value = employee
    available = [{'source_kind': 'System', 'source_field': 'requester_unit', 'company': 'company-a'}]
    resolve = binding.module.resolver(_instance(), _system_config('requester_unit'), available)
    assert resolve({'source_kind': 'System', 'source_field': 'requester_unit'}) == 'HR'


def test_resolver_requester_unit_without_a_department_is_an_error(binding):
    binding.frappe.db.get_value = lambda *a, **k: None
    resolve = binding.module.resolver(_instance(), _system_config('requester_unit'),
        [{'source_kind': 'System', 'source_field': 'requester_unit', 'company': 'company-a'}])
    with pytest.raises(ValueError, match='واحد سازمانی ثبت‌کننده قابل تعیین نیست'):
        resolve({'source_kind': 'System', 'source_field': 'requester_unit'})
    binding.frappe.db.get_value = lambda *a, **k: {'department': ''}
    with pytest.raises(ValueError, match='واحد سازمانی ثبت‌کننده قابل تعیین نیست'):
        resolve({'source_kind': 'System', 'source_field': 'requester_unit'})


def test_resolver_reads_started_by_from_the_instance(binding):
    resolve = binding.module.resolver(_instance(), _system_config('started_by'), [])
    assert resolve({'source_kind': 'System', 'source_field': 'started_by'}) == 'user@example.com'
