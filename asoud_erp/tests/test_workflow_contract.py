from asoud_erp.services.workflow_contract import (
    ALLOWED_WORKFLOW_STATUSES,
    serialize_workflow,
)


def test_workflow_status_contract_is_explicit() -> None:
    assert ALLOWED_WORKFLOW_STATUSES == {"Active", "Inactive", "Archived"}


def test_pending_workflow_is_serialized_as_locked() -> None:
    result = serialize_workflow(
        {
            "readiness_status": "Pending",
            "missing_requirements_json": '["HRMS", "Workflow states"]',
        }
    )
    assert result["is_locked"] is True
    assert result["missing_requirements"] == ["HRMS", "Workflow states"]
