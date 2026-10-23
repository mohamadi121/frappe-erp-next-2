import pytest

from asoud_erp.services.form_execution import EXECUTORS

CTX = {'company': 'شرکت', 'employee': 'EMP-1', 'today': '2030-01-01'}
OK = {'training_event': 'ایمنی', 'notes': 'تمایل دارم'}


def event(**values):
    return {'docstatus': 0, 'company': 'شرکت', 'event_status': 'Scheduled', **values}


def test_registered_and_parameters():
    executor = EXECUTORS['training_enrollment']
    assert executor.PARAMETERS['training_event'] == {
        'label': 'دوره آموزشی', 'types': ['Link'], 'required': True}
    assert executor.PARAMETERS['notes']['required'] is False


def test_build_returns_participant_row():
    payload = EXECUTORS['training_enrollment'].build(OK, CTX)
    assert payload == {'training_event': 'ایمنی', 'employee': 'EMP-1', 'notes': 'تمایل دارم'}
    assert EXECUTORS['training_enrollment'].build({'training_event': ' ایمنی '}, CTX)['notes'] is None


@pytest.mark.parametrize('params', [{}, {'training_event': ''}, {'training_event': 5},
                                    {**OK, 'notes': 3}, 'x'])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        EXECUTORS['training_enrollment'].build(params, CTX)


def test_build_requires_employee_and_company():
    with pytest.raises(ValueError, match='پرونده پرسنلی'):
        EXECUTORS['training_enrollment'].build(OK, {**CTX, 'employee': None})
    with pytest.raises(ValueError, match='شرکت'):
        EXECUTORS['training_enrollment'].build(OK, {**CTX, 'company': ''})


def test_plan_draft_adds_and_submitted_needs_review():
    from asoud_erp.services.form_execution import training_enrollment as module

    assert module.plan(event(), [], 'EMP-1', 'شرکت') == ('add', None)
    action, reason = module.plan(event(docstatus=1), ['EMP-2'], 'EMP-1', 'شرکت')
    assert (action, reason) == ('review', module.SUBMITTED_REVIEW)
    assert 'نیاز به اقدام HR' in reason


@pytest.mark.parametrize('values,participants,message', [
    ({'docstatus': 2}, [], 'لغو'), ({'event_status': 'Cancelled'}, [], 'لغو'),
    ({'event_status': 'Completed'}, [], 'برگزار شده'),
    ({'company': 'دیگر'}, [], 'شرکت'), ({}, ['EMP-1'], 'قبلاً'),
    ({'docstatus': 1}, ['EMP-1'], 'قبلاً'), (None, [], 'وجود ندارد')])
def test_plan_refusals(values, participants, message):
    from asoud_erp.services.form_execution import training_enrollment as module

    with pytest.raises(ValueError, match=message):
        module.plan(None if values is None else event(**values), participants, 'EMP-1', 'شرکت')


def test_event_without_company_is_accepted():
    from asoud_erp.services.form_execution import training_enrollment as module

    assert module.plan(event(company=None), [], 'EMP-1', 'شرکت')[0] == 'add'
