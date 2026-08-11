from asoud_erp.services.workflow_history import merge_completed_responses, select_return_stage


def test_latest_correction_overrides_previous_response():
    rows = [
        {"response_json": '{"title": "old", "amount": 10}'},
        {"response_json": '{"title": "new"}'},
    ]
    assert merge_completed_responses(rows) == {"title": "new", "amount": 10}


def test_return_prefers_latest_editable_user_task():
    rows = [
        {"workflow_stage": "review", "stage_type": "User Task", "has_form_fields": False},
        {"workflow_stage": "entry", "stage_type": "User Task", "has_form_fields": True},
    ]
    assert select_return_stage(rows) == "entry"


def test_return_rejects_process_without_previous_user_task():
    try:
        select_return_stage([{"workflow_stage": "condition", "stage_type": "Condition"}])
    except ValueError as error:
        assert "previous editable" in str(error)
    else:
        raise AssertionError("missing return stage must fail")
