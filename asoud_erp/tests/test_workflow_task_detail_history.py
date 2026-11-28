"""Pure regression: the task-detail history is additive-equal to the instance history.

``get_workflow_task``'s ``history`` rows must carry ``actor_name`` (the actor's full
name, never the raw email as the only identity) and the parsed change lines
(``before``/``after``/``labels`` through ``activity_change``), and a MASKED viewer
must not see another actor's comment or change lines (PA-055 close-out, the same
policy the instance endpoint applies). Runs the real ``get_workflow_task`` against
the in-memory fake site.
"""

import json

import pytest

from asoud_erp.tests._workflow_access_world import make_world

COMPANY = "Test Company"
REQUESTER = "requester@example.com"
APPROVER = "approver@example.com"
OTHER = "other@example.com"
SECRET = "درمان بیماری خاص"


def _seed(site, *, task_status="Open", with_change=True):
    """A request instance with one task for APPROVER and two activity rows.

    ``task_status`` decides the viewer's level: an Open task makes the assignee
    FULL; a Completed task (they acted) makes them MASKED.
    """
    site.add("Company", COMPANY, owner=APPROVER)
    site.add("User", REQUESTER, full_name="درخواست‌کنندهٔ آزمایشی")
    site.add("User", APPROVER, full_name="تأییدکنندهٔ آزمایشی")
    site.add("User", OTHER, full_name="شرکت‌کنندهٔ دیگر")
    site.add("ASOUD Workflow Request", "REQ-1", company=COMPANY, owner=REQUESTER,
             workflow_instance="WFI-1", workflow_definition="DEF-1",
             values_json=json.dumps({"reason": SECRET}, ensure_ascii=False))
    site.add("ASOUD Workflow Instance", "WFI-1", status="Running", started_by=REQUESTER,
             reference_doctype="ASOUD Workflow Request", reference_name="REQ-1")
    site.add("ASOUD Workflow Stage", "STG-1", stage_type="User Task", stage_title="ثبت درخواست")
    site.add("ASOUD Workflow Task", "TASK-1", workflow_instance="WFI-1", workflow_stage="STG-1",
             assigned_to=APPROVER, status=task_status, task_title="بررسی",
             draft_json="{}", response_json="{}")
    site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance="WFI-1", workflow_task="TASK-1",
             workflow_stage="STG-1", actor=APPROVER, action="Approve",
             comment="تأیید شد با توضیح محرمانه", created_on="2026-01-01 00:00:00",
             change_json=json.dumps({"before": {"reason": "ابتدایی"}, "after": {"reason": SECRET},
                                     "labels": {"reason": "دلیل"}}, ensure_ascii=False)
             if with_change else None)
    site.add("ASOUD Workflow Activity", "ACT-2", workflow_instance="WFI-1", workflow_task="TASK-1",
             workflow_stage="STG-1", actor=OTHER, action="Follow Up",
             comment="نظر شرکت‌کنندهٔ دیگر", created_on="2026-01-02 00:00:00",
             change_json=json.dumps({"before": {}, "after": {"note": "یادداشت محرمانه"},
                                     "labels": {"note": "یادداشت"}}, ensure_ascii=False)
             if with_change else None)


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def _task(world, user):
    site = world.site
    site.user = user
    return world.runtime.get_workflow_task("TASK-1")["data"]


def test_full_viewer_sees_actor_names_and_change_lines(world):
    site = world.site
    _seed(site)  # Open task: the assignee is a FULL viewer.
    data = _task(world, APPROVER)
    by_actor = {row["actor"]: row for row in data["history"]}
    assert set(by_actor) == {APPROVER, OTHER}
    # The readable actor name comes from the User table, not the raw email.
    assert by_actor[APPROVER]["actor_name"] == "تأییدکنندهٔ آزمایشی"
    assert by_actor[OTHER]["actor_name"] == "شرکت‌کنندهٔ دیگر"
    # The change lines are parsed through the same helper the instance endpoint uses.
    assert by_actor[APPROVER]["before"] == {"reason": "ابتدایی"}
    assert by_actor[APPROVER]["after"] == {"reason": SECRET}
    assert by_actor[APPROVER]["labels"] == {"reason": "دلیل"}
    assert by_actor[OTHER]["after"] == {"note": "یادداشت محرمانه"}
    # The raw column is not leaked; existing keys are unchanged.
    assert "change_json" not in by_actor[APPROVER]
    for row in data["history"]:
        for key in ("name", "workflow_task", "workflow_stage", "actor", "action", "comment", "created_on"):
            assert key in row


def test_masked_viewer_does_not_see_another_actor_comment_or_change(world):
    site = world.site
    _seed(site, task_status="Completed")  # they acted: MASKED.
    data = _task(world, APPROVER)
    # A MASKED previous assignee sees only their own rows: the other actor's comment
    # and change lines are not part of their authorized history.
    assert [row["actor"] for row in data["history"]] == [APPROVER]
    blob = json.dumps(data["history"], ensure_ascii=False)
    assert "نظر شرکت‌کنندهٔ دیگر" not in blob
    assert "یادداشت محرمانه" not in blob
    # Their own row keeps the readable name and their own change lines.
    assert data["history"][0]["actor_name"] == "تأییدکنندهٔ آزمایشی"
    assert data["history"][0]["after"] == {"reason": SECRET}


def test_masked_viewer_without_change_column_sees_only_their_own_rows(world):
    site = world.site
    _seed(site, task_status="Completed", with_change=False)
    data = _task(world, APPROVER)
    assert [row["actor"] for row in data["history"]] == [APPROVER]
    assert data["history"][0]["comment"] == "تأیید شد با توضیح محرمانه"
    assert data["history"][0]["actor_name"] == "تأییدکنندهٔ آزمایشی"


def test_unknown_actor_falls_back_to_the_actor_value(world):
    site = world.site
    _seed(site)
    # An actor with no User row must not crash and must not be presented as a full
    # name; the raw actor value is the fallback.
    site.add("ASOUD Workflow Activity", "ACT-3", workflow_instance="WFI-1", workflow_task="TASK-1",
             workflow_stage="STG-1", actor="ghost@example.com", action="Note",
             comment="", created_on="2026-01-03 00:00:00")
    data = _task(world, APPROVER)
    by_actor = {row["actor"]: row for row in data["history"]}
    assert by_actor["ghost@example.com"]["actor_name"] == "ghost@example.com"


def test_history_is_bounded_like_the_instance_path(world):
    site = world.site
    _seed(site)
    for i in range(250):
        site.add("ASOUD Workflow Activity", f"ACT-X{i:03d}", workflow_instance="WFI-1",
                 workflow_task="TASK-1", workflow_stage="STG-1", actor=OTHER, action="Note",
                 comment="", created_on=f"2026-02-01 00:{i // 60:02d}:{i % 60:02d}")
    data = _task(world, APPROVER)
    assert len(data["history"]) == 200
