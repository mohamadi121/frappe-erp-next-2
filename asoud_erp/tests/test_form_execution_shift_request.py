import pytest

from asoud_erp.services.form_execution import EXECUTORS


def test_shift_registered_and_self_open_end():
    payload = EXECUTORS['shift_request'].build(
        {'kind': 'self_change', 'from_date': '2030-01-01', 'shift_type': 'صبح'},
        {'company': 'شرکت', 'employee': 'کارمند'})
    assert payload['to_date'] is None
    assert payload['employee'] == 'کارمند'
    assert payload['status'] == 'Draft'


@pytest.mark.parametrize('key,value', [('kind', None), ('kind', []), ('from_date', None),
    ('from_date', 12), ('to_date', '2020-01-01'), ('shift_type', None), ('reason', 1)])
def test_invalid_parameter(key, value):
    params = {'kind': 'self_change', 'from_date': '2030-01-01', 'shift_type': 'صبح'}
    params[key] = value
    with pytest.raises(ValueError):
        EXECUTORS['shift_request'].build(params, {'company': 'شرکت', 'employee': 'کارمند'})


def test_swap_payload_and_missing_parameters():
    params = {'kind': 'swap_with_colleague', 'from_date': '2030-01-01',
              'shift_type': 'صبح', 'colleague': 'همکار', 'colleague_shift_type': 'عصر'}
    ctx = {'company': 'شرکت', 'employee': 'کارمند'}
    payload = EXECUTORS['shift_request'].build(params, ctx)
    assert payload['shift_type'] == 'صبح'
    assert payload['additional_requests'][0]['shift_type'] == 'عصر'
    assert payload['additional_requests'][0]['employee'] == 'همکار'
    for key in ('colleague', 'colleague_shift_type'):
        for empty in (None, '', [], 1):
            with pytest.raises(ValueError):
                EXECUTORS['shift_request'].build({**params, key: empty}, ctx)
    with pytest.raises(ValueError):
        EXECUTORS['shift_request'].build({**params, 'colleague': 'کارمند'}, ctx)


@pytest.mark.parametrize('empty', [None, '', '   '])
def test_empty_optional_parameters(empty):
    payload = EXECUTORS['shift_request'].build({'kind': 'self_change',
        'from_date': '2030-01-01', 'to_date': empty, 'reason': empty,
        'shift_type': 'صبح', 'colleague': empty, 'colleague_shift_type': empty},
        {'company': 'شرکت', 'employee': 'کارمند'})
    assert payload['to_date'] is None
    assert 'additional_requests' not in payload


@pytest.mark.parametrize('context', [{}, {'company': 'شرکت'}, {'employee': 'کارمند'}])
def test_context_required(context):
    with pytest.raises(ValueError):
        EXECUTORS['shift_request'].build({'kind': 'self_change',
            'from_date': '2030-01-01', 'shift_type': 'صبح'}, context)


def test_explicit_end_date():
    payload = EXECUTORS['shift_request'].build({'kind': 'self_change',
        'from_date': '2030-01-01', 'to_date': '2030-01-03', 'shift_type': 'صبح'},
        {'company': 'شرکت', 'employee': 'کارمند'})
    assert payload['from_date'] == '2030-01-01'
    assert payload['to_date'] == '2030-01-03'
