import pytest

from asoud_erp.services.certificate_access import can_download
from asoud_erp.services.form_execution import EXECUTORS

FACTS = {'employee_name': 'علی رضایی', 'designation': 'کارشناس مالی', 'date_of_joining': '2020-03-20',
         'status': 'Active', 'relieving_date': None, 'company_name': 'شرکت آزمون',
         'letterhead_html': '<div class="lh">سربرگ</div>', 'salary': None}
CTX = {'company': 'C', 'employee': 'EMP-1', 'user': 'u@x', 'request_name': 'R-1', 'today': '2030-01-01',
       'number': 'CERT-2030-00007', 'facts': FACTS}
OK = {'recipient': 'بانک ملی', 'purpose': 'bank'}
SALARY = {'base': 25000000.0, 'currency': 'IRR'}


def build(params=None, **facts):
    ctx = {**CTX, 'facts': {**FACTS, **facts}}
    return EXECUTORS['certificate_issue'].build({**OK, **(params or {})}, ctx)


def test_registered_with_parameters():
    executor = EXECUTORS['certificate_issue']
    assert executor.LABEL == 'صدور گواهی اشتغال به کار'
    assert executor.PARAMETERS['recipient']['required'] is True
    assert executor.PARAMETERS['purpose']['required'] is True
    assert executor.PARAMETERS['include_compensation']['required'] is False
    assert executor.ALLOW_INACTIVE is True


def test_persian_certificate_uses_real_facts_only():
    result = build()
    html = result['html']
    assert result['number'] == 'CERT-2030-00007'
    assert result['filename'] == 'CERT-2030-00007.pdf'
    for text in ('علی رضایی', 'کارشناس مالی', 'شرکت آزمون', 'بانک ملی', 'CERT-2030-00007', 'سربرگ',
                 '۱۳۹۹/۰۱/۰۱', 'ارائه به بانک'):
        assert text in html
    assert 'حقوق' not in html
    assert 'dir="rtl"' in html


def test_missing_designation_is_left_out_not_invented():
    html = build(designation=None)['html']
    assert 'در سمت' not in html and 'None' not in html


def test_user_text_is_escaped():
    html = build({'recipient': '<script>alert(1)</script>'})['html']
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_other_purpose_needs_details_and_others_ignore_them():
    with pytest.raises(ValueError, match='شرح هدف'):
        build({'purpose': 'other'})
    assert 'برای ویزا' in build({'purpose': 'other', 'purpose_details': 'برای ویزا'})['html']
    assert 'برای ویزا' not in build({'purpose': 'bank', 'purpose_details': 'برای ویزا'})['html']


def test_salary_only_when_asked_and_from_the_record():
    assert '۲۵٬۰۰۰٬۰۰۰' not in build(salary=SALARY)['html']
    asked = build({'include_compensation': 'yes'}, salary=SALARY)['html']
    assert '۲۵٬۰۰۰٬۰۰۰' in asked and 'IRR' in asked
    assert '۲۵٬۰۰۰٬۰۰۰' in build({'include_compensation': True}, salary=SALARY)['html']
    assert 'حقوق' not in build({'include_compensation': 'no'}, salary=SALARY)['html']


@pytest.mark.parametrize('salary', [None, {'base': None, 'currency': 'IRR'}, {'base': 0, 'currency': 'IRR'}])
def test_missing_salary_is_needs_review_never_a_number(salary):
    result = build({'include_compensation': 'yes'}, salary=salary)
    assert result == {'needs_review': 'نیاز به اقدام HR؛ برای درج حقوق، تخصیص ساختار حقوق ثبت‌شده و معتبر برای کارمند وجود ندارد.'}


@pytest.mark.parametrize('facts', [{'status': 'Inactive'}, {'status': 'Left'},
                                   {'relieving_date': '2029-12-31'}, {'relieving_date': '2030-01-01'}])
def test_not_employed_is_needs_review(facts):
    assert build(**facts) == {'needs_review': 'نیاز به اقدام HR؛ کارمند در حال حاضر شاغل نیست و گواهی اشتغال خودکار صادر نمی‌شود.'}


def test_future_relieving_date_still_employed():
    assert 'html' in build(relieving_date='2030-06-01')


def test_english_and_missing_letterhead_need_review():
    assert 'قالب انگلیسی' in build({'language': 'english'})['needs_review']
    assert 'سربرگ' in build(letterhead_html=None)['needs_review']


@pytest.mark.parametrize('params, message', [
    ({'recipient': ''}, 'مرجع دریافت‌کننده'), ({'recipient': None}, 'مرجع دریافت‌کننده'),
    ({'recipient': 'x' * 251}, 'مرجع دریافت‌کننده'),
    ({'purpose': 'weird'}, 'هدف از دریافت'), ({'purpose': None}, 'هدف از دریافت'),
    ({'language': 'klingon'}, 'زبان گواهی'), ({'include_compensation': 'maybe'}, 'درج حقوق')])
def test_invalid_parameters(params, message):
    with pytest.raises(ValueError, match=message):
        build(params)


def test_non_dict_inputs_and_missing_context():
    executor = EXECUTORS['certificate_issue']
    with pytest.raises(ValueError):
        executor.build('x', CTX)
    with pytest.raises(ValueError, match='پرونده پرسنلی'):
        executor.build(OK, {**CTX, 'employee': None})
    with pytest.raises(ValueError, match='شرکت'):
        executor.build(OK, {**CTX, 'company': ''})


def test_download_rule():
    owner = dict(owner='a@x', company_ok=True)
    assert can_download(user='a@x', roles={'Employee'}, **owner)
    assert can_download(user='b@x', roles={'HR Manager'}, **owner)
    assert can_download(user='b@x', roles={'System Manager'}, **owner)
    assert not can_download(user='b@x', roles={'Employee'}, **owner)
    assert not can_download(user='b@x', roles={'Accounts Manager', 'Purchase Manager'}, **owner)
    assert not can_download(user='a@x', roles={'HR Manager'}, owner='a@x', company_ok=False)
    assert not can_download(user='Guest', roles=set(), **owner)
