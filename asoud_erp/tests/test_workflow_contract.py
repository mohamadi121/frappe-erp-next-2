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


def _edge(name, from_stage, to_stage, action=None, label="", seq=1, result=None, condition=None):
    if condition is None:
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


def test_structural_check_accepts_system_action_with_unlabeled_default_route():
    # Real shape (SYS-LEAVE-D2 / SYS-SUPPLY-D2 / SYS-PURCHASE-D2): a System Action
    # whose only exit is an unlabeled default route ("{}", label "Continue") to End.
    # The runtime treats a single route as the stage's main route, so this is valid.
    stages = [
        _stage("S", "Start", "شروع", {"title": "شروع"}),
        _stage("A", "System Action", "اقدام خودکار", {"title": "اقدام خودکار"}),
        _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"}),
    ]
    transitions = [_edge("e1", "S", "A"), _edge("e2", "A", "E", label="Continue")]
    assert structural_issues(stages, transitions) == []


def test_structural_check_accepts_approval_to_condition_via_unlabeled_routes():
    # Real shape (SYS-LEAVE-G): an Approval whose only exit is an unlabeled default
    # route to a Condition, and that Condition's only exit is an unlabeled route to
    # End. Both single routes are the runtime's main route, so this is valid.
    stages = [
        _stage("S", "Start", "شروع", {"title": "شروع"}),
        _stage("A", "Approval", "تأیید یا رد", {"title": "تأیید یا رد"}),
        _stage("C", "Condition", "شرط و مسیر", {"title": "شرط و مسیر"}),
        _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"}),
    ]
    transitions = [_edge("e1", "S", "A"), _edge("e2", "A", "C", label="Continue"),
                   _edge("e3", "C", "E", label="Continue")]
    assert structural_issues(stages, transitions) == []


def test_structural_check_rejects_stage_without_outgoing_route():
    # A non-End stage with no exit: _next_stage returns None and the instance stalls.
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("A", "Approval", "تأیید", {"title": "تأیید"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "S", "A")]  # the approval has no exit
    assert any("مسیر خروج ندارد" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_non_dict_route_condition():
    # A route whose condition_json is not a dict: _next_stage does json.loads(...)
    # then .get, so a non-dict would crash it.
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("U", "User Task", "ثبت", {"title": "ثبت"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "E", condition=[])]
    assert any("شرط یکی از مسیرها" in issue for issue in structural_issues(stages, transitions))


def test_structural_check_rejects_stage_with_no_path_to_end():
    # A stage reachable from Start but with no path to an End: the instance can
    # never complete once it reaches there.
    stages = [_stage("S", "Start", "شروع", {"title": "شروع"}),
              _stage("U", "User Task", "ثبت", {"title": "ثبت"}),
              _stage("L", "User Task", "حلقه", {"title": "حلقه"}),
              _stage("E", "End", "پایان", {"title": "پایان", "outcome": "Completed"})]
    transitions = [_edge("e1", "S", "U"), _edge("e2", "U", "L", action="Complete"),
                   _edge("e3", "L", "L", action="Return")]  # L loops to itself, no End
    assert any("قابل دسترس" in issue for issue in structural_issues(stages, transitions))
