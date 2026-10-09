import pytest

from asoud_erp.services.request_status import (
    compute_status_key,
    group_keys,
    status_group,
    status_label,
    tab_counts,
)


@pytest.mark.parametrize("kwargs,expected", [
    (dict(instance_status="Running"), "submitted"),
    (dict(instance_status="Running", non_form_acted=True), "in_review"),
    (dict(instance_status="Running", at_form_stage=True, form_submitted=True), "returned"),
    (dict(instance_status="Running", at_form_stage=True, form_submitted=True, non_form_acted=True), "returned"),
    # The freshly started instance waits at the form stage before the form is submitted.
    (dict(instance_status="Running", at_form_stage=True), "submitted"),
    (dict(instance_status="Failed"), "failed"),
    (dict(instance_status="Completed"), "approved"),
    (dict(instance_status="Rejected"), "rejected"),
    (dict(instance_status="Cancelled"), "cancelled"),
    (dict(instance_status=None, request_status="Draft"), "draft"),
    (dict(instance_status=None, request_status="Submitted"), "submitted"),
    (dict(instance_status=None, request_status="Cancelled"), "cancelled"),
    (dict(instance_status=None, request_status="Completed"), "approved"),
])
def test_status_key_table(kwargs, expected):
    assert compute_status_key(**kwargs) == expected


def test_finished_instance_ignores_stage_flags():
    assert compute_status_key("Completed", at_form_stage=True, form_submitted=True) == "approved"


def test_labels_and_groups():
    assert status_label("submitted") == "ارسال شده"
    assert status_label("approved") == "تأیید شده"
    assert status_label("failed") == "نیازمند بررسی"
    assert [status_group(key) for key in ("submitted", "in_review", "returned", "failed")] == ["pending"] * 4
    assert status_group("approved") == "approved"
    assert status_group("rejected") == "rejected"
    assert status_group("cancelled") == "" and status_group("draft") == ""
    assert status_group("unknown") == ""


def test_display_status_overrides_only_a_running_instance():
    assert status_label("in_review", "در انتظار مدیر مالی", "Running") == "در انتظار مدیر مالی"
    assert status_label("approved", "در انتظار مدیر مالی", "Completed") == "تأیید شده"
    assert status_label("submitted", "  ", "Running") == "ارسال شده"


def test_group_keys():
    assert group_keys("pending") == ["submitted", "in_review", "returned", "failed"]
    assert group_keys("approved") == ["approved"]
    assert group_keys("rejected") == ["rejected"]
    assert group_keys("all") == [] and group_keys(None) == []


def test_tab_counts_include_everything_under_all():
    counts = tab_counts({"submitted": 2, "in_review": 1, "approved": 4, "rejected": 2, "cancelled": 3, "draft": 1})
    assert counts == {"all": 13, "pending": 3, "approved": 4, "rejected": 2}
    assert tab_counts({}) == {"all": 0, "pending": 0, "approved": 0, "rejected": 0}
