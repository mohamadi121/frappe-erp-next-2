import pytest

from asoud_erp.services import workflow_task_assignment as policy


def test_approval_never_assigns_to_the_initiator_when_others_exist():
    assert policy.approval_assignees(['a', 'sara'], 'sara', lambda: ['esc']) == ['a']


def test_approval_falls_back_to_escalation_users_without_the_initiator():
    assert policy.approval_assignees(['sara'], 'sara', lambda: ['sara', 'boss']) == ['boss']


def test_approval_with_only_the_initiator_fails_with_a_persian_reason_instead_of_a_stuck_task():
    # PA-008: the old code created an Open task the initiator can never complete.
    with pytest.raises(ValueError, match='تأییدکننده'):
        policy.approval_assignees(['sara'], 'sara', lambda: [])


def test_approval_without_initiator_in_list_is_unchanged_and_skips_escalation_lookup():
    def fail():
        raise AssertionError('escalation must not be looked up')

    assert policy.approval_assignees(['a', 'b'], 'sara', fail) == ['a', 'b']


def test_cap_counts_only_the_final_authorised_list_and_defaults_above_200():
    # PA-031: 250 holders of a common role used to be rejected before any filter ran.
    policy.check_assignee_cap(['u'] * 250, {})
    policy.check_assignee_cap(['u'] * policy.DEFAULT_MAX_ASSIGNEES, {})
    with pytest.raises(ValueError, match='بیش از حد مجاز'):
        policy.check_assignee_cap(['u'] * (policy.DEFAULT_MAX_ASSIGNEES + 1), {})


def test_cap_is_configurable_and_bad_values_fall_back_to_default():
    with pytest.raises(ValueError):
        policy.check_assignee_cap(['u'] * 3, {'asoud_workflow_max_assignees': 2})
    policy.check_assignee_cap(['u'] * 3, {'asoud_workflow_max_assignees': 3})
    for bad in ('x', 0, -1, True, None, 1.5):
        policy.check_assignee_cap(['u'] * 250, {'asoud_workflow_max_assignees': bad})
