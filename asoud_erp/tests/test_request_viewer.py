import json

from asoud_erp.services.request_viewer import build_viewer


def _task(stage_type="Approval", **config):
    return {"name": "T-1", "stage_title": "تأیید مدیر", "stage_type": stage_type, "config_json": json.dumps(config)}


def test_no_open_task_means_no_action_card():
    assert build_viewer(True, []) == {"is_requester": True, "open_task": None}


def test_flags_follow_the_stage_config():
    viewer = build_viewer(False, [_task(allow_reject=True, reject_comment_required=True)])
    assert viewer["is_requester"] is False
    assert viewer["open_task"] == {
        "name": "T-1", "stage_title": "تأیید مدیر", "stage_type": "Approval", "approve_action": "Approve",
        "allow_reject": True, "allow_return": False, "comment_required": False,
        "reject_comment_required": True, "has_form": False}


def test_missing_flags_default_to_not_allowed():
    task = build_viewer(False, [_task()])["open_task"]
    assert (task["allow_reject"], task["allow_return"]) == (False, False)


def test_user_task_completes_and_a_form_is_reported():
    task = build_viewer(False, [_task("User Task", allow_return=True, form_fields=[{"name": "a"}])])["open_task"]
    assert (task["approve_action"], task["allow_return"], task["has_form"]) == ("Complete", True, True)


def test_first_task_wins_and_broken_config_is_tolerated():
    tasks = [{"name": "A", "stage_type": "Approval", "config_json": "{not json"}, _task()]
    assert build_viewer(False, tasks)["open_task"]["name"] == "A"
