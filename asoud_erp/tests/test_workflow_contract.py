import json

from asoud_erp.services.workflow_contract import (
    ALLOWED_WORKFLOW_STATUSES,
    serialize_workflow,
    structural_issues,
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


def _system_request_graph():
    """The shape of a seeded system request type: Start has no trigger_type or
    initiator_roles (it is started through create_request, not a Manual start)."""
    stages = [
        _stage("S", "Start", "شروع", {"title": "شروع"}),
        _stage("U", "User Task", "ثبت", {"title": "ثبت", "activity_type": "Data Entry",
                                         "assignment_type": "Initiator", "form_fields": []}),
        _stage("A", "Approval", "تأیید", {"title": "تأیید", "assignment_type": "Direct Manager",
                                          "approval_mode": "Any", "allow_reject": True,
                                          "allow_return": True}),
        _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"}),
    ]
    transitions = [
        _edge("e1", "S", "U"),
        _edge("e2", "U", "A", action="Complete", label="ادامه"),
        _edge("e3", "A", "E", action="Approve", label="تأیید"),
    ]
    return stages, transitions


def test_structural_check_accepts_a_system_request_type():
    # The regression: the designer's Start trigger/initiator rules must NOT block
    # a definition started through create_request.
    stages, transitions = _system_request_graph()
    assert structural_issues(stages, transitions) == []


def test_structural_check_rejects_missing_start():
    stages = [_stage("U", "User Task", "ثبت", {"title": "ثبت"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "U", "E", action="Complete")]
    assert any("شروع" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_route_outside_definition():
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("U", "User Task", "ثبت", {"title": "ثبت"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "GONE", action="Complete")]
    assert any("خارج از این گردش‌کار" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_unreachable_stage():
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("U", "User Task", "ثبت", {"title": "ثبت"}),
              _stage("X", "User Task", "متروک", {"title": "متروک"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", action="Complete")]
    assert any("قابل دسترس" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_approval_without_approve_route():
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("A", "Approval", "تأیید", {"title": "تأیید"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    # The approval only has a Reject route; the Approve route is missing.
    transitions = [_edge("e1", "S", "A"), _edge("e2", "A", "E", action="Reject", label="رد")]
    assert any("مسیر خروج" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_invalid_condition_routes():
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("C", "Condition", "شرط", {"title": "شرط"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    # A Condition needs exactly two routes (result True/False); one is missing.
    transitions = [_edge("e1", "S", "C"), _edge("e2", "C", "E", result=True)]
    assert any("مسیر خروج" in issue for issue in structural_issues(stages, transitions))
