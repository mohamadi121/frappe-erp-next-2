from datetime import date

import pytest

from asoud_erp.services.form_execution.employee_advance import PARAMETERS, build

CTX = dict(company='شرکت', employee='EMP-1', user='user', request_name='REQ-1', today=str(date.today()))
PARAMS = dict(amount='1250.50', purpose='  هزینه سفر  ')


def test_build_native_fields():
    assert build({**PARAMS, 'posting_date': CTX['today'], 'repay_from_salary': True}, CTX) == {
        'doctype': 'Employee Advance', 'docstatus': 0, 'company': CTX['company'],
        'employee': CTX['employee'], 'advance_amount': 1250.5, 'purpose': 'هزینه سفر',
        'posting_date': CTX['today'], 'repay_unclaimed_amount_from_salary': 1, 'exchange_rate': 1,
    }
    assert set(PARAMETERS) == {'amount', 'purpose', 'posting_date', 'repay_from_salary'}
    assert [key for key, value in PARAMETERS.items() if value['required']] == ['amount', 'purpose']


@pytest.mark.parametrize('key', ['posting_date', 'repay_from_salary'])
@pytest.mark.parametrize('value', [None, '', '   '])
def test_empty_optional_values(key, value):
    result = build({**PARAMS, key: value}, CTX)
    assert result['posting_date'] == CTX['today']
    assert result['repay_unclaimed_amount_from_salary'] == 0


def test_missing_optionals():
    result = build(PARAMS, CTX)
    assert result['posting_date'] == CTX['today']
    assert result['repay_unclaimed_amount_from_salary'] == 0


@pytest.mark.parametrize('value', [None, '', ' ', 0, -1, True, 'NaN', 'Infinity', '1e999', [], {}, 'abc'])
def test_invalid_amount(value):
    with pytest.raises(ValueError, match='^مبلغ مساعده باید عددی مثبت و متناهی باشد[.]$'):
        build({**PARAMS, 'amount': value}, CTX)


@pytest.mark.parametrize('value', [None, '', ' ', 5, [], {}])
def test_invalid_purpose(value):
    with pytest.raises(ValueError, match='^شرح درخواست مساعده الزامی است[.]$'):
        build({**PARAMS, 'purpose': value}, CTX)


@pytest.mark.parametrize('key,message', [('amount', 'مبلغ مساعده باید عددی مثبت و متناهی باشد.'),
                                         ('purpose', 'شرح درخواست مساعده الزامی است.')])
def test_missing_required(key, message):
    params = dict(PARAMS)
    del params[key]
    with pytest.raises(ValueError) as error:
        build(params, CTX)
    assert str(error.value) == message


@pytest.mark.parametrize('value', ['bad', '2026-02-30', 123, [], {}, True, '20260101'])
def test_invalid_posting_date(value):
    with pytest.raises(ValueError, match='^تاریخ ثبت مساعده معتبر نیست[.]$'):
        build({**PARAMS, 'posting_date': value}, CTX)


@pytest.mark.parametrize('value', [0, 1, False, True, '0', '1'])
def test_repay_check(value):
    assert build({**PARAMS, 'repay_from_salary': value}, CTX)['repay_unclaimed_amount_from_salary'] == int(value)


@pytest.mark.parametrize('value', [2, -1, 'true', [], {}, 0.5])
def test_invalid_repay(value):
    with pytest.raises(ValueError, match='^گزینه بازپرداخت از حقوق باید بله یا خیر باشد[.]$'):
        build({**PARAMS, 'repay_from_salary': value}, CTX)


@pytest.mark.parametrize('key,message', [('company', 'شرکت درخواست مشخص نشده است.'),
                                         ('employee', 'پرونده پرسنلی درخواست‌دهنده ثبت نشده است.')])
@pytest.mark.parametrize('value', [None, '', ' '])
def test_missing_context(key, message, value):
    with pytest.raises(ValueError) as error:
        build(PARAMS, {**CTX, key: value})
    assert str(error.value) == message
