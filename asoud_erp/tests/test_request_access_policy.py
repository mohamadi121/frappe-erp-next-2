"""Pure regression for the approved confidential-data policy (PA-055).

``request_access_policy.classify`` maps (owner, privileged, task rows, activity) to
FULL / MASKED / NONE. Each case below is one of the approved policy points P1-P6.
"""

from asoud_erp.services import request_access_policy as policy


def test_p1_owner_is_full():
    assert policy.classify(True, False, [], False) == policy.FULL


def test_p2_current_assignee_with_open_task_is_full():
    assert policy.classify(False, False, [{"status": "Open"}], False) == policy.FULL


def test_p2_unclaimed_shared_claim_while_open_is_full():
    # A shared-claim task is Open for every candidate until someone claims it.
    assert policy.classify(False, False, [{"status": "Open"}], False) == policy.FULL


def test_p3_previous_assignee_who_completed_is_masked():
    assert policy.classify(False, False, [{"status": "Completed", "acted": True}], False) == policy.MASKED


def test_p3_previous_assignee_via_activity_is_masked():
    # Reassigned away: the reassign rewrote assigned_to, so there is no task row for
    # them; they are known only from their activity.
    assert policy.classify(False, False, [], True) == policy.MASKED


def test_p4_cancelled_without_acting_is_none():
    # Lost a shared claim (or superseded): the task is Cancelled and they never acted.
    assert policy.classify(False, False, [{"status": "Cancelled"}], False) == policy.NONE


def test_p5_reassigned_away_who_never_acted_is_none():
    # No open task (reassign rewrote it), no completed task, no activity.
    assert policy.classify(False, False, [], False) == policy.NONE


def test_p5_reassigned_away_who_acted_is_masked():
    assert policy.classify(False, False, [], True) == policy.MASKED


def test_p6_privileged_with_company_is_full():
    assert policy.classify(False, True, [], False) == policy.FULL


def test_open_and_cancelled_is_full():
    # An Open task dominates a Cancelled one (they are the current assignee).
    assert policy.classify(False, False, [{"status": "Open"}, {"status": "Cancelled"}], False) == policy.FULL


def test_completed_and_cancelled_is_masked():
    assert policy.classify(False, False, [{"status": "Completed", "acted": True},
                                          {"status": "Cancelled", "acted": False}], False) == policy.MASKED


def test_cancelled_and_activity_is_masked():
    # A Cancelled task plus an activity (they acted before the task was cancelled).
    assert policy.classify(False, False, [{"status": "Cancelled"}], True) == policy.MASKED


def test_no_tasks_no_activity_is_none():
    assert policy.classify(False, False, [], False) == policy.NONE


def test_owner_with_no_instance_is_full():
    assert policy.classify(True, False, None, False) == policy.FULL


def test_empty_task_rows_treated_as_none():
    assert policy.classify(False, False, None, False) == policy.NONE


# --- The requester's own form submission is not "acting" (PA-055 P1 vs P3) ---

def test_submitter_completing_the_form_stage_is_a_submission():
    # The submitter completing the request's own form stage is the submission, not acting.
    assert policy.is_submission("sara@example.com", "sara@example.com", "FORM", "FORM") is True


def test_assignee_deciding_on_the_form_stage_is_not_a_submission():
    # A different user deciding on the first stage after Start (the form stage) is acting,
    # not the requester's submission: it must count as MASKED.
    assert policy.is_submission("approver@example.com", "sara@example.com", "FORM", "FORM") is False


def test_submitter_deciding_on_a_non_form_stage_is_not_a_submission():
    # The submitter acting on a later stage (e.g. an approval) is acting, not a submission.
    assert policy.is_submission("sara@example.com", "sara@example.com", "APPROVAL", "FORM") is False


def test_no_form_stage_is_never_a_submission():
    assert policy.is_submission("sara@example.com", "sara@example.com", "APPROVAL", None) is False


def test_assignee_deciding_on_the_first_stage_after_start_is_masked():
    # An assignee who decided on the first stage after Start (the form stage) is a previous
    # assignee who acted -> MASKED, even though that stage is the request's form stage.
    assert policy.classify(False, False, [], True) == policy.MASKED


def test_requester_own_submission_is_none():
    # The requester's own form submission is excluded from "acting": with no other task or
    # activity they are NONE, not a masked previous assignee.
    assert policy.classify(False, False, [], False) == policy.NONE
