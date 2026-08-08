import pytest

from asoud_erp.services.workflow_assignment import assignment_values


def test_specific_employee_assignment_is_read_from_stage_config() -> None:
    kind, values = assignment_values(
        {"assignment_type": "Employee", "assignee_employees": ["EMP-1", "EMP-1"]},
        "User Task",
    )
    assert kind == "Employee"
    assert values == ["EMP-1"]


def test_approval_uses_approver_department() -> None:
    assert assignment_values(
        {"assignment_type": "Department", "approver_departments": ["Finance"]},
        "Approval",
    ) == ("Department", ["Finance"])


def test_unknown_assignment_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        assignment_values({"assignment_type": "Script"}, "User Task")
