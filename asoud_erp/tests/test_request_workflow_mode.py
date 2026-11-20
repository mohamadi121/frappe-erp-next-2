import pytest

from asoud_erp.services.workflow_submission_policy import request_mode, require_record_only_policy


@pytest.mark.parametrize('mode', [None, ''])
def test_old_empty_modes_keep_legacy_behavior(mode):
    assert request_mode({'kind': 'Request', 'workflow_mode': mode}) is None
    assert request_mode({'kind': 'Request', 'workflow': ''}) is None


@pytest.mark.parametrize('mode', ['Fixed', 'Conditional', 'RecordOnly'])
def test_explicit_modes_are_retained(mode):
    assert request_mode({'kind': 'Request', 'workflow_mode': mode, 'workflow': 'chosen'}) == mode


@pytest.mark.parametrize('mode', [False, 0, [], {}, 'Other'])
def test_invalid_explicit_mode_is_not_a_legacy_fallback(mode):
    with pytest.raises(ValueError, match='روش اتصال'):
        request_mode({'kind': 'Request', 'workflow_mode': mode})


@pytest.mark.parametrize('workflow', [None, '', [], ' '])
def test_fixed_requires_a_real_identifier(workflow):
    with pytest.raises(ValueError, match='گردش'):
        request_mode({'kind': 'Request', 'workflow_mode': 'Fixed', 'workflow': workflow})


def test_document_and_stage_contracts_are_unchanged():
    for kind in ('Document', 'Stage'):
        assert request_mode({'kind': kind, 'workflow_mode': 'anything'}) is None


def test_record_only_cannot_invent_an_approval_exemption():
    with pytest.raises(ValueError, match='سیاست معتبر'):
        require_record_only_policy('RecordOnly')
    for mode in (None, 'Fixed', 'Conditional'):
        require_record_only_policy(mode)
