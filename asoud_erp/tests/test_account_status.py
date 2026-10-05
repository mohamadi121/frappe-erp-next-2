"""Pure rules for the employee account operations (the ⋮ menu of a personnel file)."""

import re

import pytest

from asoud_erp.services.access_policy import access_level_for
from asoud_erp.services.account_status import (
    account_status,
    allowed_modules,
    history_limit,
    login_events,
    login_history,
    resend_blocked_message,
    session_rows,
)

FRESH = {
    "user": "new.employee@example.com",
    "enabled": 1,
    "last_login": None,
    "last_ip": None,
    "roles": ["employee"],
    "modules": ["Accounts", "HR"],
    "data_scope": [{"allow": "Company", "value": "Tabaan", "apply_to_all_doctypes": 1}],
}
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")


def test_account_status_of_an_invited_account_that_never_logged_in() -> None:
    status = account_status(**FRESH)
    assert status == {
        "user": "new.employee@example.com",
        "enabled": 1,
        "has_logged_in": False,
        "last_login": "",
        "last_ip": "",
        "can_resend_invitation": True,
        "roles": ["employee"],
        "modules": ["Accounts", "HR"],
        "data_scope": [{"allow": "Company", "value": "Tabaan", "apply_to_all_doctypes": 1}],
    }


def test_account_status_hides_resend_after_the_first_login() -> None:
    status = account_status(**{**FRESH, "last_login": "2026-02-03 09:15:00", "last_ip": "5.62.9.10"})
    assert status["has_logged_in"] is True
    assert status["can_resend_invitation"] is False
    assert status["last_login"] == "2026-02-03 09:15:00"
    assert status["last_ip"] == "5.62.9.10"
    assert status["enabled"] == 1


def test_account_status_without_a_user_offers_no_resend() -> None:
    status = account_status(**{**FRESH, "user": "", "enabled": 0})
    assert status["user"] == ""
    assert status["enabled"] == 0
    assert status["can_resend_invitation"] is False


def test_disabled_account_with_a_login_history_is_still_resend_free() -> None:
    status = account_status(**{**FRESH, "enabled": 0, "last_login": "2026-01-01 00:00:00"})
    assert (status["enabled"], status["can_resend_invitation"]) == (0, False)


def test_resend_is_refused_only_after_a_recorded_login() -> None:
    assert resend_blocked_message(False) == ""
    message = resend_blocked_message(True)
    assert "ارسال مجدد دعوت" in message
    assert not LATIN_WORD.search(message)


def test_allowed_modules_drops_blocked_and_blank_entries() -> None:
    installed = ["Accounts", "HR", "Stock", "Accounts", ""]
    assert allowed_modules(installed, ["HR"]) == ["Accounts", "Stock"]
    assert allowed_modules(installed, None) == ["Accounts", "HR", "Stock"]
    assert allowed_modules([], ["HR"]) == []
    assert allowed_modules(None, ["HR"]) == []


def test_login_events_keep_the_native_order_and_ip() -> None:
    rows = [
        {"creation": "2026-02-03 09:15:00", "operation": "Login", "status": "Success", "ip_address": "5.62.9.10"},
        {"creation": "2026-02-02 08:00:00", "operation": "Logout", "status": "Success", "ip_address": "5.62.9.11"},
        {"creation": "2026-02-01 07:00:00", "operation": "Login", "status": "Failed", "ip_address": None},
    ]
    assert login_events(rows) == [
        {"datetime": "2026-02-03 09:15:00", "operation": "Login", "status": "Success", "ip": "5.62.9.10"},
        {"datetime": "2026-02-02 08:00:00", "operation": "Logout", "status": "Success", "ip": "5.62.9.11"},
        {"datetime": "2026-02-01 07:00:00", "operation": "Login", "status": "Failed", "ip": ""},
    ]


def test_login_events_are_sorted_newest_first_whatever_the_query_returns() -> None:
    rows = [
        {"creation": "2026-01-04 07:00:00", "operation": "Login", "status": "Success", "ip_address": "1.1.1.1"},
        {"creation": "2026-01-09 07:00:00", "operation": "Login", "status": "Success", "ip_address": "1.1.1.9"},
        {"creation": "2026-01-06 07:00:00", "operation": "Logout", "status": "Success", "ip_address": "1.1.1.6"},
    ]
    assert [event["datetime"] for event in login_events(rows)] == [
        "2026-01-09 07:00:00", "2026-01-06 07:00:00", "2026-01-04 07:00:00",
    ]


def test_login_events_never_expose_session_or_secret_columns() -> None:
    events = login_events([{
        "creation": "2026-02-03 09:15:00", "operation": "Login", "status": "Success", "ip_address": "5.62.9.10",
        "sid": "bXk9session", "password": "hunter2", "api_secret": "abc", "subject": "logged in",
    }])
    assert set(events[0]) == {"datetime", "operation", "status", "ip"}
    assert "bXk9session" not in str(events)


def test_session_rows_read_the_native_ip_and_never_the_sid() -> None:
    rows = [{
        "lastupdate": "2026-02-03 09:20:00", "status": "Active", "ipaddress": None, "sid": "bXk9session",
        "sessiondata": "{'data': {'user': 'a@b.com', 'session_ip': '5.62.9.10', 'device': 'Chrome / Android'},"
                       " 'user': 'a@b.com', 'sid': 'bXk9session', 'csrf_token': 'tok3n'}",
    }]
    assert session_rows(rows) == [{
        "device": "Chrome / Android",
        "ip": "5.62.9.10",
        "last_active": "2026-02-03 09:20:00",
        "status": "Active",
    }]
    assert "bXk9session" not in str(session_rows(rows))
    assert "tok3n" not in str(session_rows(rows))


def test_session_rows_fall_back_to_the_ip_column_and_survive_broken_data() -> None:
    rows = [
        {"lastupdate": "2026-02-03 09:20:00", "status": "Active", "ipaddress": "10.0.0.5",
         "sessiondata": None},
        {"lastupdate": None, "status": None, "ipaddress": None, "sessiondata": "{not a dict"},
    ]
    assert session_rows(rows) == [
        {"device": "", "ip": "10.0.0.5", "last_active": "2026-02-03 09:20:00", "status": "Active"},
        {"device": "", "ip": "", "last_active": "", "status": ""},
    ]


def test_login_history_reports_last_login_even_without_events() -> None:
    history = login_history("2026-02-03 09:15:00", "5.62.9.10", [], [])
    assert history == {
        "last_login": "2026-02-03 09:15:00",
        "last_ip": "5.62.9.10",
        "events": [],
        "sessions": [],
    }


@pytest.mark.parametrize("value, expected", [
    (None, 20), ("", 20), ("abc", 20), (5, 5), ("35", 35), (0, 1), (-3, 1), (999, 50),
])
def test_history_limit(value, expected) -> None:
    assert history_limit(value) == expected