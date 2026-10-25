from copy import deepcopy

import pytest

from asoud_erp.services.organization_assignments import reconcile
from asoud_erp.services.organization_contract import validate_rows


def row(**fields):
    return {"code": "P", "title": "Position", "occupants": [], "capacity": 2, **fields}


def test_legacy_conversion_preserves_unknown_start_and_does_not_mutate_old():
    old = [{"code": "P", "title": "Position", "employee": "employee:E"}]
    copy = deepcopy(old)
    result = reconcile([row(occupants=["employee:E"])], old, "2026-10-20", "manager")
    assert result[0]["assignment_history"][0]["started_at"] is None
    assert result[0]["assignment_history"][0]["legacy"]
    assert old == copy


def test_end_and_reassign_retains_both_periods():
    first = reconcile([row(occupants=["employee:E"])], [], "start", "issuer")
    ended = reconcile([row()], first, "end", "hr")
    again = reconcile([row(occupants=["employee:E"])], ended, "restart", "hr2")
    history = again[0]["assignment_history"]
    assert len(history) == 2
    assert history[0]["ended_at"] == "end"
    assert history[0]["ended_by"] == "hr"
    assert history[1]["started_at"] == "restart"
    assert history[1]["ended_at"] is None


def test_history_cannot_be_forged_or_erased_on_save():
    first = reconcile([row(occupants=["employee:E"])], [], "start", "issuer")
    same = reconcile([row(occupants=["employee:E"], assignment_history=[{"forged": True}])],
        first, "later", "other")
    assert same == first
    with pytest.raises(ValueError):
        reconcile([], first, "later", "other")
    with pytest.raises(ValueError):
        reconcile([{"code": "P", "employee": ""}], first, "later", "other")


def test_legacy_removal_requires_explicit_history_conversion():
    with pytest.raises(ValueError):
        reconcile([{"code": "P", "employee": ""}], [{"code": "P", "employee": "E"}], "now", "hr")


def test_deletion_cannot_cascade_reporting_children():
    previous = [row(), row(code="CHILD", parent="P")]
    with pytest.raises(ValueError, match="زیرمجموعه"):
        reconcile([], previous, "now", "hr")


def test_delete_review_counts_and_missing_position():
    from asoud_erp.services.organization_assignments import deletion_review

    rows = [row(occupants=["employee:E"], assignment_history=[{"employee": "employee:E"}]),
            row(code="CHILD", parent="P")]
    review = deletion_review(rows, "P")
    assert review["counts"] == {"occupants": 1, "subordinates": 1, "history": 1}
    assert not review["can_delete"]
    assert len(review["blockers"]) == 3
    assert deletion_review([row()], "P")["can_delete"]
    assert not deletion_review([row(employee="legacy:E")], "P")["can_delete"]
    with pytest.raises(ValueError):
        deletion_review(rows, "MISSING")


def test_multiple_occupants_and_stable_native_department():
    result = validate_rows([row(occupants=["employee:A", "employee:B"], department_id="DEPT-ID")])
    assert result[0]["occupants"] == ["employee:A", "employee:B"]
    assert result[0]["department_id"] == "DEPT-ID"
    assert result[0]["employee"] == ""


@pytest.mark.parametrize("fields", [
    {"capacity": 0}, {"capacity": 1.5}, {"capacity": True},
    {"capacity": 1, "occupants": ["A", "B"]}, {"occupants": ["A", "A"]},
    {"occupants": "A"}, {"occupants": [""]},
])
def test_invalid_capacity_and_duplicate_assignment(fields):
    with pytest.raises(ValueError):
        validate_rows([row(**fields)])
