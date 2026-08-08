import pytest

from asoud_erp.services.workflow_stage_policy import normalize_stage_config


def test_user_task_requires_assignee_role() -> None:
    with pytest.raises(ValueError):
        normalize_stage_config("User Task", {"title": "بررسی", "activity_type": "Review"})


def test_user_task_form_fields_are_normalized() -> None:
    result = normalize_stage_config(
        "User Task",
        {
            "title": "دریافت درخواست",
            "activity_type": "Data Entry",
            "assignee_roles": ["Employee"],
            "form_fields": [
                {"key": "request_title", "label": "عنوان درخواست", "type": "Short Text", "required": True},
                {"key": "priority", "label": "اولویت", "type": "Choice", "options": ["عادی", "فوری"]},
            ],
        },
    )
    assert result["form_fields"][0]["position"] == 1
    assert result["form_fields"][1]["options"] == ["عادی", "فوری"]


def test_form_field_rejects_unsafe_or_duplicate_keys() -> None:
    with pytest.raises(ValueError):
        normalize_stage_config(
            "User Task",
            {
                "title": "دریافت درخواست",
                "activity_type": "Data Entry",
                "assignee_roles": ["Employee"],
                "form_fields": [
                    {"key": "bad-key", "label": "عنوان درخواست", "type": "Short Text"},
                ],
            },
        )


def test_approval_contract_is_normalized() -> None:
    result = normalize_stage_config(
        "Approval",
        {"title": "تأیید مدیر", "approver_roles": ["Accounts Manager"], "approval_mode": "Any"},
    )
    assert result["allow_reject"] is True
    assert result["approver_roles"] == ["Accounts Manager"]


def test_user_task_can_target_a_specific_employee() -> None:
    result = normalize_stage_config(
        "User Task",
        {
            "title": "بررسی درخواست",
            "activity_type": "Review",
            "assignment_type": "Employee",
            "assignee_employees": ["HR-EMP-0001", "HR-EMP-0001"],
        },
    )
    assert result["assignment_type"] == "Employee"
    assert result["assignee_employees"] == ["HR-EMP-0001"]
    assert result["assignee_roles"] == []


def test_approval_can_target_a_department() -> None:
    result = normalize_stage_config(
        "Approval",
        {
            "title": "تأیید واحد مالی",
            "assignment_type": "Department",
            "approver_departments": ["Accounts - ASOUD"],
            "approval_mode": "Any",
        },
    )
    assert result["approver_departments"] == ["Accounts - ASOUD"]


def test_assignment_requires_target_for_selected_type() -> None:
    with pytest.raises(ValueError):
        normalize_stage_config(
            "User Task",
            {
                "title": "بررسی درخواست",
                "activity_type": "Review",
                "assignment_type": "Employee",
                "assignee_roles": ["Employee"],
            },
        )


def test_arbitrary_system_action_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_stage_config(
            "System Action",
            {"title": "اجرا", "action_type": "Arbitrary API", "target_roles": ["System Manager"]},
        )


def test_condition_field_name_is_safe() -> None:
    with pytest.raises(ValueError):
        normalize_stage_config(
            "Condition",
            {"title": "شرط", "source_field": "__import__('os')", "operator": "Is Set"},
        )
