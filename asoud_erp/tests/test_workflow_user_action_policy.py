"""Pure contract regressions. Intentionally not executed at the owner's request."""
import pytest

from asoud_erp.services.workflow_user_action_policy import condition_fields, normalize_action, simple_schema


def config(**changes):
    return {'action_contract_version': 1, 'assignment_rule': {'basis': 'Subject'}, **changes}


def test_legacy_config_is_not_converted():
    assert normalize_action({'assignment_type': 'Initiator'}) == {}


@pytest.mark.parametrize('version', [True, '1', 0, 2, []])
def test_unknown_version_fails_closed(version):
    with pytest.raises(ValueError):
        normalize_action(config(action_contract_version=version))


def test_simple_default_has_no_business_document_or_form_selection():
    result = normalize_action(config(result_form={'form': 'ignored', 'revision': 'ignored'}))
    assert result['result_mode'] == 'Simple'
    assert result['result_form'] is None
    assert result['assignment_rule'] == {'basis': 'Subject', 'subject': 'Initiator', 'delivery': 'Direct'}
    fields = simple_schema(False)['sections'][0]['fields']
    assert [field['key'] for field in fields] == ['action_result', 'action_note']
    assert [item['id'] for item in fields[0]['options']] == ['done', 'follow_up', 'blocked']
    assert simple_schema(True)['sections'][0]['fields'][-1]['type'] == 'File'


@pytest.mark.parametrize('rule', [
    {'basis': 'Unit', 'department': 'dept', 'delivery': 'Direct'},
    {'basis': 'Subject', 'subject': 'Form Employee'},
    {'basis': 'Role', 'role': 'Guest'},
    {'basis': 'Role', 'role': 'All'},
    {'basis': 'Role', 'role': 'Employee', 'scope': 'Department'},
    {'basis': 'Role', 'role': 'Employee', 'scope': 'Other'},
    {'basis': 'Missing'},
])
def test_incomplete_or_unsafe_assignment_is_rejected(rule):
    with pytest.raises(ValueError):
        normalize_action(config(assignment_rule=rule))


@pytest.mark.parametrize('rule,expected', [
    ({'basis': 'Role', 'role': 'Employee', 'person': 'stale'},
     {'basis': 'Role', 'role': 'Employee', 'scope': 'Company', 'delivery': 'Shared'}),
    ({'basis': 'Unit', 'department': 'dept', 'person': 'stale'},
     {'basis': 'Unit', 'department': 'dept', 'delivery': 'Shared'}),
    ({'basis': 'Manager', 'subject': 'Form Employee', 'employee_field': 'employee', 'department': 'stale'},
     {'basis': 'Manager', 'subject': 'Form Employee', 'employee_field': 'employee', 'delivery': 'Direct'}),
])
def test_only_relevant_assignment_fields_survive(rule, expected):
    assert normalize_action(config(assignment_rule=rule))['assignment_rule'] == expected


@pytest.mark.parametrize('source', [None, {}, {'form': 'form'}, {'form': 'form', 'revision': 1}])
def test_form_mode_requires_a_pinned_revision(source):
    with pytest.raises(ValueError):
        normalize_action(config(result_mode='Form', result_form=source))


def test_valid_form_and_attachment_policy_are_explicit():
    result = normalize_action(config(result_mode='Form', result_form={'form': 'form', 'revision': 'rev'},
        allow_add_attachments=True))
    assert result['result_form'] == {'form': 'form', 'revision': 'rev'}
    assert result['allow_add_attachments'] is True
    with pytest.raises(ValueError):
        normalize_action(config(allow_add_attachments='false'))


def test_canvas_reuses_scalar_result_fields_but_never_exposes_private_values():
    value = config(result_schema={'sections': [{'fields': [
        {'key': 'total', 'label': 'جمع', 'type': 'Formula'},
        {'key': 'salary', 'label': 'محرمانه', 'type': 'Money', 'sensitive': True},
        {'key': 'proof', 'label': 'پیوست', 'type': 'File'},
        {'key': 'rows', 'label': 'ردیف‌ها', 'type': 'Table'},
    ]}]})
    assert condition_fields(value) == [{'fieldname': 'total', 'label': 'جمع', 'fieldtype': 'Float', 'source': 'Form'}]
    assert condition_fields({}) == []
