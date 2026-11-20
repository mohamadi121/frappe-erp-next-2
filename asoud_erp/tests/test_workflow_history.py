from asoud_erp.services.workflow_history import merge_completed_responses, select_return_stage


def test_preceding_stages_excludes_correction_edges_and_handles_shared_paths():
    from asoud_erp.services.workflow_history import preceding_stages

    rows = [
        {'from_stage': 'entry', 'to_stage': 'approval'},
        {'from_stage': 'approval', 'to_stage': 'next'},
        {'from_stage': 'next', 'to_stage': 'approval', 'condition_json': '{"action":"Return"}'},
        {'from_stage': 'other', 'to_stage': 'approval', 'transition_label': 'رد'},
    ]
    assert preceding_stages('approval', rows) == {'entry'}
    assert preceding_stages('next', rows) == {'entry', 'approval'}


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


def test_return_can_target_approval_stage_with_supplementary_form():
    # PA-003: an Approval stage that collected a supplementary form is editable too.
    rows = [
        {"workflow_stage": "approval-2", "stage_type": "Approval", "has_supplementary_form": False},
        {"workflow_stage": "approval-1", "stage_type": "Approval", "has_supplementary_form": True},
    ]
    assert select_return_stage(rows) == "approval-1"


def test_return_prefers_newest_editable_among_user_tasks_and_supplementary_approvals():
    rows = [
        {"workflow_stage": "approval-1", "stage_type": "Approval", "has_supplementary_form": True},
        {"workflow_stage": "entry", "stage_type": "User Task", "has_form_fields": True},
    ]
    assert select_return_stage(rows) == "approval-1"


def test_return_ignores_plain_approval_without_supplementary_form():
    with __import__("pytest").raises(ValueError):
        select_return_stage([{"workflow_stage": "approval", "stage_type": "Approval", "has_supplementary_form": False}])


SCHEMA = {'sections': [{'fields': [
    {'key': 'note', 'type': 'Text'},
    {'key': 'secret', 'type': 'Text', 'sensitive': True},
    {'key': 'proof', 'type': 'File'},
    {'key': 'lines', 'type': 'Table', 'columns': [
        {'key': 'qty', 'type': 'Integer'}, {'key': 'scan', 'type': 'Image'}, {'key': 'pin', 'type': 'Text', 'sensitive': True}]},
]}]}


def test_returned_user_action_starts_from_the_previous_answer_of_the_same_stage():
    from asoud_erp.services.workflow_history import carried_draft

    rows = [  # newest first, like _completed_task_rows
        {'workflow_stage': 'other', 'response_json': '{"note": "wrong stage"}'},
        {'workflow_stage': 'act', 'response_json': '{"note": "new", "secret": "s", "proof": "f.pdf", '
            '"lines": [{"qty": 2, "scan": "x.png", "pin": "1"}], "unknown": 1}'},
        {'workflow_stage': 'act', 'response_json': '{"note": "old"}'},
    ]
    assert carried_draft(rows, 'act', SCHEMA) == {'note': 'new', 'lines': [{'qty': 2}]}


def test_first_visit_or_unreadable_history_gives_an_empty_draft():
    from asoud_erp.services.workflow_history import carried_draft

    assert carried_draft([], 'act', SCHEMA) == {}
    assert carried_draft([{'workflow_stage': 'act', 'response_json': 'not json'}], 'act', SCHEMA) == {}
    assert carried_draft([{'workflow_stage': 'act', 'response_json': '[1]'}], 'act', SCHEMA) == {}
    assert carried_draft([{'workflow_stage': 'act', 'response_json': '{"note": "x"}'}], 'act', None) == {}
