import pytest

from asoud_erp.services.form_execution import EXECUTORS

CTX = {'company': 'شرکت', 'employee': 'کارمند', 'today': '2030-01-01'}
OK = {'last_working_day': '2030-02-01', 'reason': 'resignation', 'notes': 'یادداشت'}


def test_registered_and_payload():
    executor = EXECUTORS['exit']
    assert executor.PARAMETERS['last_working_day']['required'] is True
    payload = executor.build(OK, CTX)
    assert (payload['doctype'], payload['status'], payload['docstatus']) == ('Exit Interview', 'Pending', 0)
    assert payload['employee_update'] == {'relieving_date': '2030-02-01'}
    assert payload['statement']['doctype'] == 'Full and Final Statement'
    assert payload['statement']['relieving_date'] == '2030-02-01'
    assert payload['statement']['transaction_date'] == '2030-01-01'


def test_reason_never_copied_to_a_native_field():
    payload = EXECUTORS['exit'].build({**OK, 'reason': 'رازِ‌محرمانه'}, CTX)
    assert 'رازِ‌محرمانه' not in repr(payload)


@pytest.mark.parametrize('key,value', [('last_working_day', None), ('last_working_day', '2030-13-01'),
    ('last_working_day', 5), ('reason', 3), ('notes', ['x'])])
def test_invalid_parameters(key, value):
    with pytest.raises(ValueError):
        EXECUTORS['exit'].build({**OK, key: value}, CTX)


@pytest.mark.parametrize('empty', [None, '', '  '])
def test_optional_empty(empty):
    payload = EXECUTORS['exit'].build({'last_working_day': '2030-02-01', 'reason': empty, 'notes': empty}, CTX)
    assert payload['notes'] is None


@pytest.mark.parametrize('ctx', [{}, {'company': 'شرکت'}, {'employee': 'کارمند'}])
def test_context_required(ctx):
    with pytest.raises(ValueError):
        EXECUTORS['exit'].build(OK, ctx)
