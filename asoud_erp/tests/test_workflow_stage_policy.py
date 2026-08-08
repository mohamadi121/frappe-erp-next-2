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
