import json

import pytest

from asoud_erp.services import request_followup as followup


def test_followup_of_reads_server_written_marker_only():
    draft = json.dumps({"followup": {"kind": "confirm_receipt", "doctype": "Asset Movement", "name": "M-1"}})
    assert followup.followup_of(draft)["name"] == "M-1"
    assert followup.followup_of(None) is None
    assert followup.followup_of("") is None
    assert followup.followup_of("not json") is None
    assert followup.followup_of(json.dumps({"followup": "x"})) is None
    assert followup.followup_of(json.dumps({"followup": {"kind": "unknown"}})) is None
    assert followup.followup_of(json.dumps({"a": 1})) is None


def test_normalize_requires_known_kind_document_and_owner_as_assignee():
    raw = {"kind": "confirm_receipt", "doctype": "Asset Movement", "name": "M-1",
           "subject": " لپ‌تاپ ", "assignee": "u@example.com"}
    assert followup.normalize(raw, "u@example.com") == {
        "kind": "confirm_receipt", "doctype": "Asset Movement", "name": "M-1", "subject": "لپ‌تاپ"}
    for broken in ({**raw, "kind": "x"}, {**raw, "name": ""}, {**raw, "doctype": None},
                   {**raw, "assignee": "other@example.com"}, "text", None):
        with pytest.raises(ValueError):
            followup.normalize(broken, "u@example.com")


def test_task_title_uses_subject_with_fallback():
    assert followup.task_title({"kind": "confirm_receipt", "subject": "لپ‌تاپ"}) == "تأیید دریافت تجهیز: لپ‌تاپ"
    assert followup.task_title({"kind": "confirm_receipt", "subject": ""}) == "تأیید دریافت تجهیز"


def test_reason_is_trimmed_required_and_bounded():
    assert followup.clean_reason("  تحویل نشد ") == "تحویل نشد"
    for bad in (None, "", "   ", 5):
        with pytest.raises(ValueError, match="علت عدم دریافت را بنویسید."):
            followup.clean_reason(bad)
    with pytest.raises(ValueError, match="۵۰۰ نویسه"):
        followup.clean_reason("ب" * 501)
    assert followup.clean_reason("ب" * 500) == "ب" * 500


def test_closed_task_messages_are_persian_and_distinct():
    assert "قبلاً تأیید شده" in followup.closed_message("Completed")
    assert "عدم دریافت" in followup.closed_message("Rejected")
    assert "لغو شده" in followup.closed_message("Cancelled")
    assert followup.closed_message("Open") is None
