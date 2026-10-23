from asoud_erp.services.request_timeline import build_stages

STAGES = [
    {"name": "S3", "stage_type": "Approval", "stage_title": "مدیر مالی", "sequence_no": 3},
    {"name": "S1", "stage_type": "User Task", "stage_title": "ثبت درخواست", "sequence_no": 1},
    {"name": "SC", "stage_type": "Condition", "stage_title": "شرط", "sequence_no": 2},
    {"name": "S2", "stage_type": "Approval", "stage_title": "مدیر مستقیم", "sequence_no": 2},
]


def task(stage, status, action="", assigned="2026-01-01 09:00:00", completed="", user="a@x.com", comment=""):
    return {"workflow_stage": stage, "status": status, "action": action, "assigned_on": assigned,
            "completed_on": completed, "assigned_to": user, "comment": comment}


def by_name(rows):
    return {row["name"]: row for row in rows}


def test_orders_by_sequence_and_skips_non_human_stages():
    assert [row["name"] for row in build_stages(STAGES, [])] == ["S1", "S2", "S3"]


def test_no_tasks_is_pending_and_empty():
    row = by_name(build_stages(STAGES, []))["S2"]
    assert (row["status"], row["assignee_names"], row["assigned_on"], row["completed_on"]) == ("pending", [], "", "")


def test_four_statuses():
    tasks = [
        task("S1", "Completed", "Complete", completed="2026-01-01 10:00:00"),
        task("S2", "Open"),
        task("S3", "Rejected", "Reject", completed="2026-01-02 10:00:00", comment="کافی نیست"),
    ]
    rows = by_name(build_stages(STAGES, tasks))
    assert rows["S1"]["status"] == "done" and rows["S1"]["completed_on"] == "2026-01-01 10:00:00"
    assert rows["S2"]["status"] == "active" and rows["S2"]["completed_on"] == ""
    assert rows["S3"]["status"] == "rejected" and rows["S3"]["comment"] == "کافی نیست"
    assert by_name(build_stages(STAGES, [task("S2", "Completed", "Return", completed="2026-01-03 10:00:00")]))["S2"]["status"] == "returned"


def test_parallel_tasks_stay_active_until_all_closed_and_show_full_names():
    tasks = [
        task("S2", "Completed", "Approve", completed="2026-01-01 11:00:00", user="a@x.com"),
        task("S2", "Open", assigned="2026-01-01 09:05:00", user="b@x.com"),
    ]
    row = by_name(build_stages(STAGES, tasks, {"a@x.com": "علی رضایی"}))["S2"]
    assert row["status"] == "active"
    assert row["assignee_names"] == ["علی رضایی", "b@x.com"]
    assert row["assigned_on"] == "2026-01-01 09:00:00"
