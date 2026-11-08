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
    return types.SimpleNamespace(module=importlib.reload(module), frappe=frappe)


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
    """A definition with a Start and a Condition stage and four native Original fields."""
    frappe.get_doc = lambda doctype, name: _Attr(company='شرکت آزمایشی', source_revision=None,
        target_doctype='ASOUD Workflow Request')
    frappe.get_all = lambda doctype, **kw: (
        [_Attr(name='START', stage_type='Start', stage_title='شروع', config_json='{}'),
         _Attr(name='GATE', stage_type='Condition', stage_title='شرط', config_json='{}')]
        if doctype == 'ASOUD Workflow Stage'
        else [_Attr(from_stage='START', to_stage='GATE')])
    frappe.get_cached_value = lambda doctype, name, field: 'IRR'
    frappe.get_meta = lambda doctype: _Attr(fields=[
        _Field({'fieldname': 'amount', 'label': 'مبلغ', 'fieldtype': 'Currency', 'options': 'currency'}),
        _Field({'fieldname': 'employee', 'label': 'کارمند', 'fieldtype': 'Link', 'options': 'Employee'}),
        _Field({'fieldname': 'unit', 'label': 'واحد', 'fieldtype': 'Link', 'options': 'Department'}),
        _Field({'fieldname': 'note', 'label': 'یادداشت', 'fieldtype': 'Data'}),
    ])


def _by_field(rows):
    return {row['source_field']: row for row in rows}


def test_catalog_adds_picker_and_currency_metadata(binding):
    _catalog_frappe(binding.frappe)
    rows = _by_field(binding.module.catalog('DEF', 'GATE'))
    assert rows['amount']['currency'] == 'IRR'
    assert rows['amount']['field_type'] == 'Number'
    assert rows['employee']['value_source'] == 'employee'
    assert rows['employee']['link_doctype'] == 'Employee'
    assert rows['unit']['value_source'] == 'department'
    assert rows['unit']['link_doctype'] == 'Department'
    assert rows['note']['value_source'] is None
    assert rows['note']['link_doctype'] is None
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
    assert rows['status']['field_type'] == 'Select'
    assert rows['status']['options'] == ['Running', 'Completed', 'Rejected', 'Cancelled', 'Failed']
    assert rows['status']['option_labels'] == {'Running': 'در حال گردش', 'Completed': 'تکمیل‌شده',
        'Rejected': 'ردشده', 'Cancelled': 'لغوشده', 'Failed': 'ناموفق'}


def _instance(**kw):
    base = dict(name='inst-1', reference_doctype='X', reference_name=None,
        started_by='user@example.com', started_on=None, status='Running')
    base.update(kw)
    return _Attr(**base)


def _system_config(field):
    return {'conditions': [{'source_kind': 'System', 'source_field': field}]}


def test_resolver_reads_requester_unit_from_the_requester_employee(binding):
    binding.frappe.db.get_value = lambda doctype, filters, field, as_dict=False: {'department': 'HR'}
    resolve = binding.module.resolver(_instance(), _system_config('requester_unit'), [])
    assert resolve({'source_kind': 'System', 'source_field': 'requester_unit'}) == 'HR'


def test_resolver_requester_unit_without_a_department_is_an_error(binding):
    binding.frappe.db.get_value = lambda *a, **k: None
    resolve = binding.module.resolver(_instance(), _system_config('requester_unit'), [])
    with pytest.raises(ValueError, match='واحد سازمانی ثبت‌کننده قابل تعیین نیست'):
        resolve({'source_kind': 'System', 'source_field': 'requester_unit'})
    binding.frappe.db.get_value = lambda *a, **k: {'department': ''}
    with pytest.raises(ValueError, match='واحد سازمانی ثبت‌کننده قابل تعیین نیست'):
        resolve({'source_kind': 'System', 'source_field': 'requester_unit'})


def test_resolver_reads_started_by_and_status_from_the_instance(binding):
    resolve = binding.module.resolver(_instance(), _system_config('started_by'), [])
    assert resolve({'source_kind': 'System', 'source_field': 'started_by'}) == 'user@example.com'
    assert resolve({'source_kind': 'System', 'source_field': 'status'}) == 'Running'
