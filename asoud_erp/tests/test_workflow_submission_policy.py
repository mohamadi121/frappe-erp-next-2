import pytest

from asoud_erp.services.workflow_stage_policy import normalize_stage_config
from asoud_erp.services.workflow_submission_policy import normalize


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
