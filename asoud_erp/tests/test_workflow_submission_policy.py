import pytest

from asoud_erp.services.workflow_stage_policy import normalize_stage_config
from asoud_erp.services.workflow_submission_policy import choose_route, normalize


def candidate(name, mode='Default', **values):
    return dict(name=name, mode=mode, status='Active', readiness_status='Ready', **values)


def test_shared_form_default_and_conditional_selection():
    default = candidate('ordinary')
    other = candidate('special', 'Conditional', matched=True)
    assert choose_route([default, other]) == 'special'
    other['matched'] = False
    assert choose_route([other, default, candidate('draft', 'Available')]) == 'ordinary'


def test_shared_form_never_chooses_random_ambiguous_match_or_default():
    with pytest.raises(ValueError, match='بیش از یک گردش'):
        choose_route([candidate('one', 'Conditional', matched=True), candidate('two', 'Conditional', matched=True)])
    with pytest.raises(ValueError, match='پیش‌فرض'):
        choose_route([candidate('one'), candidate('two')])
    assert choose_route([candidate('available', 'Available')], legacy_default=True) is None


def test_shared_form_unready_default_is_not_silently_bypassed():
    pending = candidate('pending')
    pending['status'] = 'Inactive'
    with pytest.raises(ValueError, match='آماده'):
        choose_route([pending, candidate('reserved', 'Available')])


@pytest.mark.parametrize('value', [False, [], '', {}, {'form': 'x'},
    {'form': 'x', 'revision': None}, {'form': 'x' * 141, 'revision': 'r'}])
def test_invalid_sources_are_rejected(value):
    with pytest.raises(ValueError):
        normalize(value)


def test_source_is_identity_only_not_client_schema():
    assert normalize({'form': ' form ', 'revision': ' rev ', 'schema': {'untrusted': True}}) == {
        'form': 'form', 'revision': 'rev'}


def test_source_never_configures_a_new_business_output():
    config = normalize_stage_config('User Task', {'title': 'بررسی ثبت اصلی',
        'activity_type': 'Review', 'assignment_type': 'Initiator',
        'submission_source': {'form': 'form', 'revision': 'rev'},
        'task_purpose': 'Create Request', 'request_definition': 'another-workflow'})
    assert config['task_purpose'] == 'Existing'
    assert 'request_definition' not in config
    assert 'bound_form_schema' not in config
    assert config['form_fields'] == []


def test_old_stage_without_source_keeps_its_output():
    config = normalize_stage_config('User Task', {'title': 'خروجی قبلی',
        'activity_type': 'Task', 'assignment_type': 'Initiator',
        'task_purpose': 'Create Request', 'request_definition': 'existing'})
    assert config['task_purpose'] == 'Create Request'
    assert 'submission_source' not in config
