import pytest

from asoud_erp.services import request_execution
from asoud_erp.services import request_void as rules


def test_reason_is_trimmed_required_and_bounded():
    assert rules.clean_reason("  اشتباه بود ") == "اشتباه بود"
    for bad in ("", "  ", None, 5):
        with pytest.raises(ValueError, match="دلیل ابطال سند را بنویسید"):
            rules.clean_reason(bad)
    with pytest.raises(ValueError, match="حداکثر ۵۰۰"):
        rules.clean_reason("ا" * 501)
    assert rules.clean_reason("ا" * 500)


@pytest.mark.parametrize("doctype,docstatus,plan", [
    ("Asset Movement", 1, "cancel"), ("Employee Advance", 1, "cancel"), ("Asset Movement", 0, "mark"),
    ("Employee Checkin", 0, "mark"), ("Training Event", 1, "mark"), ("Training Event", 0, "mark"),
    ("Shift Request", 2, "already"), ("Employee Advance", None, "already")])
def test_void_plan_never_cancels_shared_or_unsubmittable_documents(doctype, docstatus, plan):
    assert rules.void_plan(doctype, docstatus) == plan


def test_unknown_doctype_is_refused():
    with pytest.raises(ValueError, match="از این مسیر ممکن نیست"):
        rules.void_plan("Leave Ledger Entry", 1)


def test_void_and_reissue_conditions():
    assert rules.can_void("Completed", "Created", "X")
    for args in (("Running", "Created", "X"), ("Completed", "Voided", "X"), ("Completed", "Created", ""),
                 ("Completed", "Needs Review", "X")):
        assert not rules.can_void(*args)
    assert rules.can_reissue("Voided", "") and not rules.can_reissue("Voided", "leave")
    assert not rules.can_reissue("Created", "")
    assert rules.already_reissued(["Voided", "Reissued"]) and not rules.already_reissued(["Voided"])
    assert not rules.already_reissued([])


def test_execution_lane_reports_a_voided_document():
    block = request_execution.build_execution("Completed", "Voided", reference="X", privileged=True)
    assert (block["state"], block["label"]) == ("voided", "سند ابطال شد")
    assert block["reference"] == "" and block["error"] == ""


def test_reissue_blockers_name_the_effect_that_stays():
    assert "تردد" in rules.reissue_blocker("Employee Checkin", "mark")
    assert "هم‌پوشانی" in rules.reissue_blocker("Shift Request", "mark")
    assert rules.reissue_blocker("Shift Request", "cancel") == ""
    assert "دوره ثبت شده" in rules.reissue_blocker("Training Event", "mark", 1)
    assert rules.reissue_blocker("Training Event", "mark", 0) == ""
    assert "مصاحبهٔ خروج" in rules.reissue_blocker("Exit Interview", "mark")
    assert "سابقهٔ" in rules.reissue_blocker("Exit Interview", "cancel", effects_missing=True)
    assert rules.reissue_blocker("Asset Movement", "mark") == ""
    assert rules.void_plan("Full and Final Statement", 1) == "cancel"
    assert not rules.can_reissue_now("Voided", "", "سبب")
    assert rules.can_reissue_now("Voided", "", "")
