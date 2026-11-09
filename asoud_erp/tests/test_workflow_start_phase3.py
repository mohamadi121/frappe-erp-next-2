"""Phase 3 start-logic rules at the pure policy level.

The endpoint behaviour (draft vs final submit, duplicate suppression, start-event
traceability) is covered by the integration module; here we pin the decision
matrix that the endpoint relies on so a regression in the policy is caught fast.
"""
import pytest

from asoud_erp.services.workflow_start_policy import normalize_settings, start_decision


def _manual(**extra):
    return normalize_settings({'trigger_type': 'Manual', 'initiator_roles': ['System Manager'], **extra})


def _document_event():
    return normalize_settings({'trigger_type': 'Document Event',
                               'submission_source': {'form': 'f', 'revision': 'r'}})


def test_prevent_duplicate_is_always_on():
    # The policy never exposes a way to turn duplicate prevention off.
    assert _manual()['prevent_duplicate'] is True
    assert _document_event()['prevent_duplicate'] is True


def test_prevent_restart_is_default_and_manager_restart_is_opt_in():
    assert _manual()['prevent_restart'] is True
    assert _manual()['allow_manager_restart'] is False
    assert _manual(allow_manager_restart=True)['allow_manager_restart'] is True


def test_replay_of_a_running_or_closed_run_reuses_not_duplicates():
    config = _manual()
    # A second submit / retry / second tab for the same record must not create a new run.
    assert start_decision(config, 'Running', False, False, '') == 'reuse'
    assert start_decision(config, 'Completed', False, False, '') == 'reuse'
    assert start_decision(config, 'Rejected', False, False, '') == 'reuse'


def test_first_start_is_new():
    assert start_decision(_manual(), None, False, False, 'علت شروع') == 'new'
    # A form-submission start needs no manual reason.
    assert start_decision(_document_event(), None, False, False, '') == 'new'


def test_restart_requires_a_closed_run():
    config = _manual(allow_manager_restart=True)
    with pytest.raises(ValueError):
        start_decision(config, 'Running', True, True, 'علت')
    with pytest.raises(ValueError):
        start_decision(config, None, True, True, 'علت')


def test_restart_requires_manager_authority_and_reason():
    config = _manual(allow_manager_restart=True)
    with pytest.raises(ValueError):
        start_decision(config, 'Completed', True, False, 'علت')  # not a manager
    with pytest.raises(ValueError):
        start_decision(config, 'Completed', True, True, '')  # no reason
    assert start_decision(config, 'Completed', True, True, 'بازبینی') == 'new'


def test_restart_refused_when_manager_restart_not_enabled():
    config = _manual()  # allow_manager_restart defaults to False
    with pytest.raises(ValueError):
        start_decision(config, 'Completed', True, True, 'علت')
