import pytest

from asoud_erp.services.request_execution import activity_change, build_execution

DONE = "اجرا انجام شد"


def _state(instance, native, has_execution=True):
    return build_execution(instance, native, has_execution=has_execution)["state"]


@pytest.mark.parametrize("instance,native,state", [
    ("Completed", "", "not_started"),
    ("Completed", "Pending", "pending"),
    ("Completed", "Created", "succeeded"),
    ("Completed", "Failed", "failed"),
    ("Completed", "Skipped", "not_connected"),
    ("Running", "", "not_started"),
    ("Failed", "", "needs_review"),
    ("Failed", "Created", "needs_review"),
    ("Rejected", "", "not_applicable"),
    ("Rejected", "Failed", "not_applicable"),
    ("Cancelled", "", "not_applicable"),
    (None, "", "not_applicable"),
])
def test_instance_status_by_native_status_matrix(instance, native, state):
    assert _state(instance, native) == state


def test_a_template_without_execution_is_not_applicable():
    assert _state("Completed", "", has_execution=False) == "not_applicable"
    assert _state("Running", "", has_execution=False) == "not_applicable"


def test_native_result_is_kept_even_without_a_spec():
    assert _state("Completed", "Created", has_execution=False) == "succeeded"


def test_approved_alone_is_never_reported_as_done():
    block = build_execution("Completed", "", has_execution=True)
    assert block["label"] == "تأیید شده، اجرا انجام نشده"
    assert DONE not in block["label"]


def test_only_succeeded_says_done():
    labels = {state: build_execution(i, n, has_execution=True)["label"] for state, (i, n) in {
        "not_started": ("Completed", ""), "pending": ("Completed", "Pending"), "failed": ("Completed", "Failed"),
        "needs_review": ("Failed", ""), "not_connected": ("Completed", "Skipped")}.items()}
    assert all(DONE not in label for label in labels.values())
    assert DONE in build_execution("Completed", "Created", has_execution=True)["label"]


def test_failed_is_not_rejected():
    failed = build_execution("Completed", "Failed", has_execution=True)
    rejected = build_execution("Rejected", "", has_execution=True)
    assert failed["state"] == "failed" and rejected["state"] == "not_applicable"
    assert failed["label"] != rejected["label"]


def test_error_only_for_privileged_users():
    args = ("Completed", "Failed")
    assert build_execution(*args, has_execution=True, error="E1: x", privileged=False)["error"] == ""
    assert build_execution(*args, has_execution=True, error="E1: x", privileged=True)["error"] == "E1: x"
    assert build_execution("Completed", "Created", has_execution=True, error="old", privileged=True)["error"] == ""


def test_reference_and_who_when_come_from_the_result():
    block = build_execution("Completed", "Created", has_execution=True, reference="HR-LAP-1",
                            executed_on="2026-10-01 09:00:00", executed_by_name="علی رضایی")
    assert (block["reference"], block["executed_on"], block["executed_by_name"]) == (
        "HR-LAP-1", "2026-10-01 09:00:00", "علی رضایی")
    open_block = build_execution("Completed", "Pending", has_execution=True, reference="X",
                                 executed_on="2026-10-01", executed_by_name="n")
    assert (open_block["reference"], open_block["executed_on"], open_block["executed_by_name"]) == ("", "", "")


def test_activity_change_parses_before_and_after():
    assert activity_change('{"before": {"a": 1}, "after": {"a": 2}}') == {"before": {"a": 1}, "after": {"a": 2}}


@pytest.mark.parametrize("raw", [None, "", "{bad", "[1]", '{"before": 3}'])
def test_activity_change_is_empty_when_missing_or_broken(raw):
    assert activity_change(raw) == {"before": {}, "after": {}}
