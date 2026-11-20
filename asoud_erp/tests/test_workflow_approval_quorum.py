"""Decision counting for multi-approver Approval stages (PA-067)."""
from datetime import datetime, timedelta

import pytest

from asoud_erp.services.workflow_approval_quorum import (
    MODES,
    current_round,
    decision_counts,
    normalize_mode,
    required_approvals,
    stage_reached_quorum,
)
from asoud_erp.services.workflow_stage_policy import normalize_stage_config


def test_modes_are_any_all_majority() -> None:
    assert MODES == {"Any", "All", "Majority"}


def test_legacy_configs_keep_their_behaviour() -> None:
    # A missing or unknown mode keeps the old All semantics; only an explicit
    # Any or Majority changes the counting.
    assert normalize_mode({}) == "All"
    assert normalize_mode({"approval_mode": None}) == "All"
    assert normalize_mode({"approval_mode": "Whatever"}) == "All"
    assert normalize_mode({"approval_mode": "Any"}) == "Any"
    assert normalize_mode({"approval_mode": "All"}) == "All"
    assert normalize_mode({"approval_mode": "Majority"}) == "Majority"
    assert normalize_mode(None) == "All"


def test_required_approvals_per_mode() -> None:
    assert required_approvals("Any", 1) == 1
    assert required_approvals("Any", 5) == 1
    assert required_approvals("All", 1) == 1
    assert required_approvals("All", 5) == 5
    # More than half: 2 of 3, 3 of 5, 1 of 1.
    assert required_approvals("Majority", 1) == 1
    assert required_approvals("Majority", 2) == 2
    assert required_approvals("Majority", 3) == 2
    assert required_approvals("Majority", 4) == 3
    assert required_approvals("Majority", 5) == 3


def test_stage_reached_quorum() -> None:
    assert stage_reached_quorum("Any", 3, 1) is True
    assert stage_reached_quorum("All", 3, 2) is False
    assert stage_reached_quorum("All", 3, 3) is True
    assert stage_reached_quorum("Majority", 3, 1) is False
    assert stage_reached_quorum("Majority", 3, 2) is True
    assert stage_reached_quorum("Majority", 5, 2) is False
    assert stage_reached_quorum("Majority", 5, 3) is True


def test_invalid_inputs_raise_persian_errors() -> None:
    with pytest.raises(ValueError, match="تعداد تأییدکنندگان"):
        required_approvals("All", 0)
    with pytest.raises(ValueError, match="تعداد تأییدکنندگان"):
        required_approvals("Majority", -1)
    with pytest.raises(ValueError, match="حالت رأی‌گیری"):
        required_approvals("Quorum", 3)


def test_current_round_keeps_only_the_newest_activation() -> None:
    base = datetime(2026, 11, 16, 10, 0, 0)
    first_round = [
        {"status": "Completed", "action": "Approve", "assigned_on": base,
         "completed_on": base + timedelta(minutes=5)},
        {"status": "Completed", "action": "Approve", "assigned_on": base + timedelta(milliseconds=40),
         "completed_on": base + timedelta(minutes=6)},
    ]
    second_round = [
        {"status": "Open", "action": None, "assigned_on": base + timedelta(hours=2), "completed_on": None},
        {"status": "Open", "action": None, "assigned_on": base + timedelta(hours=2, seconds=1), "completed_on": None},
    ]
    tasks = first_round + second_round
    deciding = base + timedelta(hours=2)
    # The earlier round's approvals must not count toward the new round.
    assert len(current_round(tasks, deciding)) == 2
    assert decision_counts(tasks, deciding) == (2, 0)
    # A single round: all tasks count.
    assert decision_counts(first_round, base) == (2, 2)
    assert decision_counts([], deciding) == (0, 0)


def test_two_rounds_one_second_apart_are_kept_separate() -> None:
    # A fast return + resubmit re-activates the stage within a second; the exact
    # boundary (the earlier round's completed_on) must still separate the rounds.
    base = datetime(2026, 11, 16, 10, 0, 0)
    first_round = [
        {"status": "Completed", "action": "Approve", "assigned_on": base,
         "completed_on": base + timedelta(milliseconds=200)},
    ]
    second_round = [
        {"status": "Open", "action": None, "assigned_on": base + timedelta(seconds=1), "completed_on": None},
        {"status": "Open", "action": None, "assigned_on": base + timedelta(seconds=1, milliseconds=50),
         "completed_on": None},
    ]
    tasks = first_round + second_round
    deciding = base + timedelta(seconds=1)
    assert decision_counts(tasks, deciding) == (2, 0)


def test_no_completed_tasks_counts_everything() -> None:
    base = datetime(2026, 11, 16, 10, 0, 0)
    tasks = [
        {"status": "Open", "action": None, "assigned_on": base, "completed_on": None},
        {"status": "Open", "action": None, "assigned_on": base + timedelta(seconds=1), "completed_on": None},
    ]
    assert decision_counts(tasks, base) == (2, 0)


def test_majority_counts_with_three_and_four_approvers() -> None:
    base = datetime(2026, 11, 16, 10, 0, 0)

    def round_of(count, approved):
        return [
            {"status": "Completed" if i < approved else "Open",
             "action": "Approve" if i < approved else None,
             "assigned_on": base + timedelta(seconds=i),
             "completed_on": base + timedelta(seconds=i, minutes=1) if i < approved else None}
            for i in range(count)
        ]

    # 3 approvers: 1 approve is not a majority, 2 is.
    assert decision_counts(round_of(3, 1), base) == (3, 1)
    assert stage_reached_quorum("Majority", 3, 1) is False
    assert stage_reached_quorum("Majority", 3, 2) is True
    # 4 approvers: 2 is not a majority, 3 is.
    assert decision_counts(round_of(4, 2), base) == (4, 2)
    assert stage_reached_quorum("Majority", 4, 2) is False
    assert stage_reached_quorum("Majority", 4, 3) is True


def test_stage_policy_accepts_majority_mode() -> None:
    result = normalize_stage_config(
        "Approval",
        {"title": "تأیید هیئت", "approver_roles": ["Accounts Manager"], "approval_mode": "Majority"},
    )
    assert result["approval_mode"] == "Majority"


def test_stage_policy_rejects_unknown_mode_with_persian_error() -> None:
    with pytest.raises(ValueError, match="حالت رأی‌گیری مرحلهٔ تأیید نامعتبر است"):
        normalize_stage_config(
            "Approval",
            {"title": "تأیید هیئت", "approver_roles": ["Accounts Manager"], "approval_mode": "Quorum"},
        )
