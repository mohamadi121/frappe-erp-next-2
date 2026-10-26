import sys
import types

import pytest


@pytest.fixture
def guard(monkeypatch):
    fake = types.ModuleType("frappe")
    fake.PermissionError = type("PermissionError", (Exception,), {})
    fake.local = types.SimpleNamespace(request=None, session=types.SimpleNamespace(user="Guest"))

    def throw(message, exc=Exception):
        raise exc(message)

    fake.throw = throw
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("asoud_erp.services.session_guard", None)
    import asoud_erp.services.session_guard as module

    yield module, fake
    sys.modules.pop("asoud_erp.services.session_guard", None)


def test_only_password_and_logout_endpoints_pass_while_a_temporary_password_is_active(guard):
    module, _ = guard
    allowed = ["/api/method/asoud_erp.api.v1.account_security.change_password",
               "/api/method/asoud_erp.api.v1.session.login_state", "/api/method/logout",
               "/api/method/asoud_erp.api.v1.session.logout"]
    for path in allowed:
        assert not module.blocked(path, True)
    for path in ["/api/method/asoud_erp.api.v1.setup.save_office", "/api/method/frappe.client.get_list",
                 "/api/method/asoud_erp.api.v1.hr.save_report"]:
        assert module.blocked(path, True)
        assert not module.blocked(path, False)


def test_login_request_itself_is_not_blocked_for_a_temporary_password_account(guard):
    # Frappe authenticates inside init_request, before before_request hooks run, so the
    # session user of the POST /api/method/login is already the flagged account. Blocking
    # it answered 403 (with a session cookie) and the forced password change never started.
    module, _ = guard
    assert not module.blocked("/api/method/login", True)


def test_non_api_paths_are_untouched(guard):
    module, _ = guard
    assert module.method_of("/app/home") is None
    assert not module.blocked("/app/home", True)


def test_method_of_strips_query(guard):
    module, _ = guard
    assert module.method_of("/api/method/a.b.c?x=1") == "a.b.c"
