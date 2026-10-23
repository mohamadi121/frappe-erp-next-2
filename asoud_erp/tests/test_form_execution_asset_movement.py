from copy import deepcopy
from datetime import date

import pytest

from asoud_erp.services.form_execution.asset_movement import PARAMETERS, build


@pytest.fixture
def ctx():
    return dict(company='Company', employee='EMP', user='user', request_name='REQ',
                today=date.today().isoformat(), asset_location='Office', asset_custodian=None)


def test_issue_mapping_and_purity(ctx):
    params = dict(asset='ASSET', direction='Issue', date='2026-10-22', note='توضیح')
    before = deepcopy((params, ctx))
    assert build(params, ctx) == dict(doctype='Asset Movement', company='Company', purpose='Issue',
        docstatus=0, transaction_date='2026-10-22 00:00:00',
        reference_doctype='ASOUD Workflow Request', reference_name='REQ',
        assets=[dict(asset='ASSET', source_location='Office', target_location='Office',
                     from_employee=None, to_employee='EMP')])
    assert (params, ctx) == before
    assert set(PARAMETERS) == {'asset', 'direction', 'date', 'note'}


def test_receipt_mapping(ctx):
    ctx['asset_custodian'] = 'EMP'
    row = build(dict(asset='ASSET', direction='Receipt'), ctx)['assets'][0]
    assert row == dict(asset='ASSET', source_location='Office', target_location='Office',
                       from_employee='EMP', to_employee=None)


@pytest.mark.parametrize('key', ['date', 'note'])
@pytest.mark.parametrize('value', [None, '', '   '])
def test_empty_optionals(ctx, key, value):
    doc = build(dict(asset='ASSET', direction='Issue', **{key: value}), ctx)
    assert doc['transaction_date'] == ctx['today'] + ' 00:00:00'


@pytest.mark.parametrize('key,value,message', [
    ('asset', None, 'تجهیز را انتخاب کنید.'), ('asset', '', 'تجهیز را انتخاب کنید.'),
    ('asset', [], 'تجهیز را انتخاب کنید.'),
    ('direction', None, 'جهت جابه‌جایی باید تحویل یا بازگشت باشد.'),
    ('direction', '', 'جهت جابه‌جایی باید تحویل یا بازگشت باشد.'),
    ('direction', 'Transfer', 'جهت جابه‌جایی باید تحویل یا بازگشت باشد.'),
    ('direction', [], 'جهت جابه‌جایی باید تحویل یا بازگشت باشد.'),
    ('date', 'bad', 'تاریخ جابه‌جایی معتبر نیست.'),
    ('date', 123, 'تاریخ جابه‌جایی معتبر نیست.'),
    ('note', {}, 'توضیحات جابه‌جایی معتبر نیست.'),
])
def test_parameter_errors(ctx, key, value, message):
    with pytest.raises(ValueError, match=message):
        build(dict(asset='ASSET', direction='Issue') | {key: value}, ctx)


@pytest.mark.parametrize('key,message', [
    ('asset', 'تجهیز را انتخاب کنید.'),
    ('direction', 'جهت جابه‌جایی باید تحویل یا بازگشت باشد.'),
])
def test_missing_required(ctx, key, message):
    params = dict(asset='ASSET', direction='Issue')
    del params[key]
    with pytest.raises(ValueError, match=message):
        build(params, ctx)


def test_wrong_custodian(ctx):
    with pytest.raises(ValueError, match='تجهیز در اختیار درخواست‌دهنده نیست و قابل بازگشت نیست.'):
        build(dict(asset='ASSET', direction='Receipt'), ctx)


def test_missing_location(ctx):
    ctx['asset_location'] = None
    with pytest.raises(ValueError, match='مکان تجهیز ثبت نشده یا معتبر نیست.'):
        build(dict(asset='ASSET', direction='Issue'), ctx)


def test_missing_employee(ctx):
    ctx['employee'] = None
    with pytest.raises(ValueError, match='پرونده پرسنلی درخواست‌دهنده ثبت نشده است.'):
        build(dict(asset='ASSET', direction='Issue'), ctx)


def test_issue_preserves_existing_custodian_as_source(ctx):
    ctx['asset_custodian'] = 'OTHER'
    row = build(dict(asset='ASSET', direction='Issue'), ctx)['assets'][0]
    assert (row['from_employee'], row['to_employee']) == ('OTHER', 'EMP')


def test_registry_and_field_types():
    from asoud_erp.services.form_execution import EXECUTORS
    assert EXECUTORS['asset_movement'].KIND == 'asset_movement'
    assert PARAMETERS == {
        'asset': dict(label='تجهیز', types=['Link'], required=True),
        'direction': dict(label='جهت جابه‌جایی', types=['Select'], required=True),
        'date': dict(label='تاریخ جابه‌جایی', types=['Date'], required=False),
        'note': dict(label='توضیحات', types=['Text', 'LongText'], required=False),
    }
