import pytest

from asoud_erp.services.workflow_start_policy import normalize_settings, start_decision, validate_request_id


def test_shared_form_route_modes_are_preserved():
    from asoud_erp.services.workflow_start_policy import normalize_settings

    for mode in ('Available', 'Default', 'Conditional'):
        result = normalize_settings({'trigger_type': 'Document Event', 'initiator_roles': [],
            'submission_source': {'form': 'FORM', 'revision': 'REV'}, 'source_route': mode})
        assert result['source_route'] == mode



def manual(**extra):
    return {'trigger_type': 'Manual', 'initiator_roles': ['System Manager'], **extra}


@pytest.mark.parametrize('req_id', ['short', 'toolong' + 'a'*60, 'invalid.id!', None, ''])
def test_request_id_validation(req_id):
    if req_id is None or req_id == '':
        validate_request_id(req_id)
    else:
        with pytest.raises(ValueError):
            validate_request_id(req_id)


def test_request_id_valid():
    validate_request_id('valid-req_123')


def test_start_settings_are_typed_and_manual_has_no_form_link():
    result = normalize_settings(manual())
    assert result['start_settings_version'] == 1
    assert result['require_manual_reason'] is True
    assert result['submission_source'] is None
    assert normalize_settings({'trigger_type': 'Document Event', 'submission_source':
        {'form': 'form', 'revision': 'revision'}})['submission_source']['form'] == 'form'


@pytest.mark.parametrize('value', [None, [], manual(initiator_roles=[]), manual(allow_manager_restart='true'),
    manual(submission_source={'form': 'f', 'revision': 'r'}), manual(reason='fixed reason'),
    {'trigger_type': 'Document Event'}, manual(initiator_roles=['Guest']), manual(initiator_roles=[' Guest ']),
    manual(require_manual_reason=False), manual(audit_start=False), manual(trigger_type=[]), manual(initiator_roles=[3])])
def test_invalid_or_fabricated_settings_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_settings(value)


def test_replays_reuse_existing_run_but_explicit_restart_needs_closed_run_and_authority():
    config = normalize_settings(manual(allow_manager_restart=True))
    assert start_decision(config, 'Running', False, False, '') == 'reuse'
    assert start_decision(config, 'Completed', False, False, '') == 'reuse'
    assert start_decision(config, 'Completed', True, True, 'بازبینی مستند') == 'new'
    for status, manager, reason in [('Running', True, 'علت'), ('Completed', False, 'علت'), ('Completed', True, '')]:
        with pytest.raises(ValueError):
            start_decision(config, status, True, manager, reason)


def test_manual_reason_is_supplied_by_initiator_and_no_restart_exists_by_default():
    config = normalize_settings(manual())
    with pytest.raises(ValueError):
        start_decision(config, None, False, False, '')
    assert start_decision(config, None, False, False, 'بررسی درخواست امروز') == 'new'
    with pytest.raises(ValueError):
        start_decision(config, 'Completed', True, True, 'علت')


def test_form_submission_does_not_require_a_manual_reason():
    config = normalize_settings({'trigger_type': 'Document Event', 'submission_source': {'form': 'f', 'revision': 'r'}})
    assert start_decision(config, None, False, False, '') == 'new'


def test_runtime_cannot_disable_mandatory_reason_with_a_stale_config():
    with pytest.raises(ValueError):
        start_decision({'trigger_type': 'Manual', 'require_manual_reason': False}, None, False, False, '')
