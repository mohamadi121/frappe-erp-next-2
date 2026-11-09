"""Pure tests for the side-effect-free workflow walk."""
import json

from asoud_erp.services.workflow_simulation import simulate_workflow


def _stage(name, stage_type, title, config=None):
    return {"name": name, "stage_type": stage_type, "stage_title": title,
            "configuration_status": "Complete",
            "config_json": json.dumps(config or {}, ensure_ascii=False)}


def _edge(name, from_stage, to_stage, action=None, label="", seq=1, result=None):
    condition = {}
    if action:
        condition["action"] = action
    if result is not None:
        condition["result"] = result
    return {"name": name, "from_stage": from_stage, "to_stage": to_stage,
            "transition_label": label, "condition_json": json.dumps(condition),
            "sequence_no": seq}


def _leave_graph():
    stages = [
        _stage("S", "Start", "شروع", {"trigger_type": "Manual", "initiator_roles": ["Employee"]}),
        _stage("U", "User Task", "ثبت", {"title": "ثبت", "activity_type": "Task", "assignment_type": "Initiator"}),
        _stage("A", "Approval", "تأیید", {"title": "تأیید", "approval_mode": "All",
                                          "assignment_type": "Role", "approver_roles": ["Employee"]}),
        _stage("T2", "User Task", "بررسی", {"title": "بررسی", "activity_type": "Task", "assignment_type": "Initiator"}),
        _stage("ER", "End", "رد", {"title": "رد", "outcome": "Rejected"}),
        _stage("EC", "End", "تکمیل", {"title": "تکمیل", "outcome": "Completed"}),
    ]
    transitions = [
        _edge("e1", "S", "U", seq=1),
        _edge("e2", "U", "A", action="Complete", label="ادامه", seq=1),
        _edge("e3", "A", "T2", action="Approve", label="تأیید", seq=1),
        _edge("e4", "A", "ER", action="Reject", label="رد", seq=2),
        _edge("e5", "A", "U", action="Return", label="بازگشت", seq=3),
        _edge("e6", "T2", "EC", action="Complete", label="ادامه", seq=1),
    ]
    return stages, transitions


def test_approve_path_reaches_completed_end():
    stages, transitions = _leave_graph()
    result = simulate_workflow(stages, transitions, [
        {"stage": "U", "action": "Complete"},
        {"stage": "A", "action": "Approve"},
        {"stage": "T2", "action": "Complete"},
    ])
    assert [step["stage"] for step in result["steps"]] == ["S", "U", "A", "T2", "EC"]
    assert result["status"] == "finished"
    assert result["outcome"] == "Completed"
    assert result["waiting_stage"] is None
    assert result["errors"] == []


def test_reject_path_skips_task2_and_ends_rejected():
    stages, transitions = _leave_graph()
    result = simulate_workflow(stages, transitions, [
        {"stage": "U", "action": "Complete"},
        {"stage": "A", "action": "Reject"},
    ])
    walked = [step["stage"] for step in result["steps"]]
    assert walked == ["S", "U", "A", "ER"]
    assert "T2" not in walked
    assert result["status"] == "finished"
    assert result["outcome"] == "Rejected"


def test_return_path_goes_back_to_user_task_and_waits():
    stages, transitions = _leave_graph()
    result = simulate_workflow(stages, transitions, [
        {"stage": "U", "action": "Complete"},
        {"stage": "A", "action": "Return"},
    ])
    assert [step["stage"] for step in result["steps"]] == ["S", "U", "A", "U"]
    assert result["status"] == "needs_decision"
    assert result["waiting_stage"] == "U"
    assert result["allowed_actions"] == ["Complete", "Reject", "Return"]
    assert result["outcome"] is None


def test_missing_forward_route_is_an_error():
    stages = [
        _stage("S", "Start", "شروع", {"trigger_type": "Manual", "initiator_roles": ["Employee"]}),
        _stage("U", "User Task", "ثبت", {"title": "ثبت", "activity_type": "Task", "assignment_type": "Initiator"}),
    ]
    transitions = [_edge("e1", "S", "U", seq=1)]
    result = simulate_workflow(stages, transitions, [{"stage": "U", "action": "Complete"}])
    assert result["status"] == "error"
    assert result["errors"] == ["مسیر خروجی این مرحله تعریف نشده است."]


def test_condition_stage_uses_caller_true_false():
    stages = [
        _stage("S", "Start", "شروع", {"trigger_type": "Manual", "initiator_roles": ["Employee"]}),
        _stage("C", "Condition", "شرط", {"title": "شرط", "source_kind": "Document",
                                         "source_field": "amount", "operator": "Is Set"}),
        _stage("EC", "End", "تکمیل", {"title": "تکمیل", "outcome": "Completed"}),
        _stage("ER", "End", "رد", {"title": "رد", "outcome": "Rejected"}),
    ]
    transitions = [
        _edge("e1", "S", "C", seq=1),
        _edge("e2", "C", "EC", result=True, seq=1),
        _edge("e3", "C", "ER", result=False, seq=2),
    ]
    true_run = simulate_workflow(stages, transitions, [{"stage": "C", "action": "True"}])
    assert [step["stage"] for step in true_run["steps"]] == ["S", "C", "EC"]
    assert true_run["outcome"] == "Completed"
    false_run = simulate_workflow(stages, transitions, [{"stage": "C", "action": "False"}])
    assert [step["stage"] for step in false_run["steps"]] == ["S", "C", "ER"]
    assert false_run["outcome"] == "Rejected"


def test_loop_guard_stops_after_two_hundred_steps():
    stages = [
        _stage("S", "Start", "شروع", {"trigger_type": "Manual", "initiator_roles": ["Employee"]}),
        _stage("U", "User Task", "ثبت", {"title": "ثبت", "activity_type": "Task", "assignment_type": "Initiator"}),
        _stage("A", "Approval", "تأیید", {"title": "تأیید", "approval_mode": "All",
                                          "assignment_type": "Role", "approver_roles": ["Employee"]}),
    ]
    transitions = [
        _edge("e1", "S", "U", seq=1),
        _edge("e2", "U", "A", action="Complete", label="ادامه", seq=1),
        _edge("e3", "A", "U", action="Return", label="بازگشت", seq=1),
    ]
    decisions = []
    for index in range(300):
        decisions.append({"stage": "U", "action": "Complete"})
        decisions.append({"stage": "A", "action": "Return"})
    result = simulate_workflow(stages, transitions, decisions)
    assert result["status"] == "error"
    assert result["errors"] == ["مسیر بیش از ۲۰۰ مرحله طول کشید؛ احتمالاً حلقه‌ای وجود دارد."]


def test_missing_start_is_an_error():
    stages = [_stage("U", "User Task", "ثبت", {"title": "ثبت", "activity_type": "Task", "assignment_type": "Initiator"})]
    result = simulate_workflow(stages, [], [])
    assert result["status"] == "error"
    assert result["errors"] == ["گردش‌کار باید دقیقاً یک مرحلهٔ شروع داشته باشد."]
