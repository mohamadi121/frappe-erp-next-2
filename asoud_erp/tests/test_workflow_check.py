"""Pure tests for the read-only workflow validity check."""
import json

from asoud_erp.services.workflow_check import validate_workflow


def _stage(name, stage_type, title, config=None, status="Complete"):
    return {"name": name, "stage_type": stage_type, "stage_title": title,
            "configuration_status": status,
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


START = {"trigger_type": "Manual", "initiator_roles": ["Employee"]}
USER_TASK = {"title": "ثبت", "activity_type": "Task", "assignment_type": "Initiator"}
APPROVAL = {"title": "تأیید", "approval_mode": "All", "assignment_type": "Role",
            "approver_roles": ["Employee"]}
END = {"title": "پایان", "outcome": "Completed"}


def _codes(result):
    return [issue["code"] for issue in result["issues"]]


def test_valid_graph_has_no_issues():
    stages = [_stage("S", "Start", "شروع", START), _stage("U", "User Task", "ثبت", USER_TASK),
              _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", action="Complete", label="ادامه")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is True
    assert result["issues"] == []


def test_missing_start_is_an_error():
    stages = [_stage("U", "User Task", "ثبت", USER_TASK), _stage("E", "End", "پایان", END)]
    transitions = [_edge("e2", "U", "E", action="Complete", label="ادامه")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is False
    assert "start_end_missing" in _codes(result)


def test_unreachable_stage_is_reported():
    stages = [_stage("S", "Start", "شروع", START), _stage("U", "User Task", "ثبت", USER_TASK),
              _stage("X", "User Task", "متروک", USER_TASK), _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", action="Complete", label="ادامه")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is False
    assert "disconnected" in _codes(result)


def test_self_loop_is_a_warning_not_an_error():
    stages = [_stage("S", "Start", "شروع", START), _stage("U", "User Task", "ثبت", USER_TASK),
              _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", action="Complete", label="ادامه"),
                   _edge("e3", "U", "U", action="Return", label="بازگشت")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is True
    assert "self_loop" in _codes(result)
    assert all(issue["severity"] != "error" for issue in result["issues"])


def test_loop_without_exit_is_an_error():
    stages = [_stage("S", "Start", "شروع", START), _stage("U", "User Task", "ثبت", USER_TASK),
              _stage("A", "Approval", "تأیید", APPROVAL), _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "A", action="Complete", label="ادامه"),
                   _edge("e3", "A", "U", action="Return", label="بازگشت")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is False
    assert "loop_no_exit" in _codes(result)


def test_disabled_decision_with_route_is_a_warning():
    stages = [_stage("S", "Start", "شروع", START),
              _stage("A", "Approval", "تأیید", {**APPROVAL, "allow_reject": False}),
              _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "A"), _edge("e2", "A", "E", action="Approve", label="تأیید"),
                   _edge("e3", "A", "E", action="Reject", label="رد")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is True
    assert "disabled_decision_route" in _codes(result)
    issue = next(issue for issue in result["issues"] if issue["code"] == "disabled_decision_route")
    assert issue["route"] == "Reject"
    assert issue["stage"] == "A"
    # The message names the action in Persian, not the English code.
    assert "رد" in issue["message"]
    assert "Reject" not in issue["message"]


def test_reference_to_missing_form_is_an_error():
    stages = [_stage("S", "Start", "شروع", START),
              _stage("U", "User Task", "ثبت", {**USER_TASK, "submission_source": {"form": "F1", "revision": "R1"}}),
              _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", action="Complete", label="ادامه")]
    result = validate_workflow(stages, transitions, existing_forms={"OTHER"})
    assert result["ok"] is False
    assert "form_missing" in _codes(result)
    # When the form exists, no form issue is raised.
    assert "form_missing" not in _codes(validate_workflow(stages, transitions, existing_forms={"F1"}))


def test_route_to_external_stage_is_an_error():
    stages = [_stage("S", "Start", "شروع", START), _stage("U", "User Task", "ثبت", USER_TASK),
              _stage("E", "End", "پایان", END)]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "GONE", action="Complete", label="ادامه")]
    result = validate_workflow(stages, transitions)
    assert result["ok"] is False
    assert "route_external" in _codes(result)
