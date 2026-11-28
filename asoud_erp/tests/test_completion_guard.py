"""Pure tests for the shared completion guard (F-4): the savepoint/rollback/Failed protection
that the native request path and the five specialised HR modules now share."""

import sys
import types

import pytest


def _fake_frappe(monkeypatch):
    calls = {"savepoint": [], "rollback": [], "log_error": [], "clear_messages": 0}

    class QueryDeadlockError(Exception):
        pass

    class QueryTimeoutError(Exception):
        pass

    db = types.SimpleNamespace(
        savepoint=lambda name: calls["savepoint"].append(name),
        rollback=lambda save_point=None: calls["rollback"].append(save_point),
    )
    frappe = types.ModuleType("frappe")
    frappe.db = db
    frappe.clear_messages = lambda: calls.__setitem__("clear_messages", calls["clear_messages"] + 1)
    frappe.log_error = lambda **kwargs: calls["log_error"].append(kwargs)
    frappe.get_traceback = lambda: "traceback"
    frappe.QueryDeadlockError = QueryDeadlockError
    frappe.QueryTimeoutError = QueryTimeoutError
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe, calls


@pytest.fixture
def guard(monkeypatch):
    frappe, calls = _fake_frappe(monkeypatch)
    # Re-import against the stubbed frappe so the module binds the fake db/exceptions.
    import importlib

    sys.modules.pop("asoud_erp.services.completion_guard", None)
    completion_guard = importlib.import_module("asoud_erp.services.completion_guard")
    yield completion_guard, calls
    sys.modules.pop("asoud_erp.services.completion_guard", None)


def test_success_runs_action_and_never_reports_failure(guard):
    completion_guard, calls = guard
    ran = []
    completion_guard.run_guarded(lambda: ran.append(1), lambda reason: ran.append("fail"),
                                 savepoint="sp", log_title="t")
    assert ran == [1]
    assert calls["savepoint"] == ["sp"]
    assert calls["rollback"] == [] and calls["log_error"] == []


def test_failure_rolls_back_logs_and_reports_the_reason(guard):
    completion_guard, calls = guard
    reported = []

    def boom():
        raise KeyError("missing_field")

    completion_guard.run_guarded(boom, lambda reason: reported.append(reason),
                                 savepoint="sp", log_title="Native document creation failed")
    assert calls["rollback"] == ["sp"]
    assert calls["log_error"] == [{"title": "Native document creation failed", "message": "traceback"}]
    assert calls["clear_messages"] == 1
    assert reported == ["'missing_field'"]  # the error is handed to on_failure, not swallowed


def test_deadlock_and_timeout_are_re_raised_not_swallowed(guard):
    completion_guard, calls = guard
    frappe = sys.modules["frappe"]

    def raise_deadlock():
        raise frappe.QueryDeadlockError()

    def raise_timeout():
        raise frappe.QueryTimeoutError()

    for boom in (raise_deadlock, raise_timeout):
        with pytest.raises(Exception):
            completion_guard.run_guarded(boom, lambda reason: None, savepoint="sp", log_title="t")
    # a re-raised transaction error must not be recorded as a business failure
    assert calls["rollback"] == [] and calls["log_error"] == []


def test_persian_reason_keeps_persian_and_falls_back_for_english(guard):
    completion_guard = guard[0]
    fallback = "ثبت نتیجه ناموفق بود."
    assert completion_guard.persian_reason("مشکل در ایجاد سند", fallback) == "مشکل در ایجاد سند"
    assert completion_guard.persian_reason("KeyError: 'x'", fallback) == fallback
    assert completion_guard.persian_reason("", fallback) == fallback
    assert completion_guard.persian_reason(None, fallback) == fallback
