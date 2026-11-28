import importlib
import sys
import types

from asoud_erp.api.v1.responses import failure, success


def test_success_contract():
    response = success({"name": "test"})
    assert response["ok"] is True
    assert response["meta"]["api_version"] == "v1"
    assert response["data"] == {"name": "test"}


def test_failure_contract():
    response = failure("VALIDATION_ERROR", "invalid")
    assert response["ok"] is False
    assert response["error"]["code"] == "VALIDATION_ERROR"
    assert response["error"]["message"] == "invalid"
    assert response["meta"]["api_version"] == "v1"


def test_success_accepts_empty_payload():
    response = success()
    assert response == {"ok": True, "data": None, "meta": {"api_version": "v1"}}


def test_success_merges_metadata():
    response = success([], meta={"created_count": 2})
    assert response["meta"] == {"api_version": "v1", "created_count": 2}


def test_failure_default_envelope_is_unchanged():
    # Existing callers pass only code and message: the envelope keys are exactly the old ones.
    result = failure("METHOD_NOT_ALLOWED", "این متد مجاز نیست.")
    assert result == {
        "ok": False,
        "error": {"code": "METHOD_NOT_ALLOWED", "message": "این متد مجاز نیست."},
        "meta": {"api_version": "v1"},
    }
    assert set(result["error"]) == {"code", "message"}


def test_failure_retryable_is_present_only_when_given():
    # ``retryable`` is an additive key: absent by default, present (with its value) when passed.
    assert "retryable" not in failure("X", "m")["error"]
    assert failure("X", "m", retryable=True)["error"]["retryable"] is True
    assert failure("X", "m", retryable=False)["error"]["retryable"] is False


def test_failure_field_and_hint_are_present_only_when_given():
    base = failure("X", "m")
    assert "field" not in base["error"] and "hint" not in base["error"]
    result = failure("X", "m", field="company", hint="شرکت را انتخاب کنید.")
    assert result["error"]["field"] == "company"
    assert result["error"]["hint"] == "شرکت را انتخاب کنید."
    # The base keys are still there alongside the additive ones.
    assert result["error"]["code"] == "X" and result["error"]["message"] == "m"


def test_failure_retryable_never_from_message_text():
    # The contract: retryable is a caller decision from the status class, not parsed from text.
    # A message that merely mentions "retry" must not flip the flag on its own.
    assert "retryable" not in failure("X", "please retry later")["error"]
    assert failure("X", "please retry later", retryable=True)["error"]["retryable"] is True


def _stub_frappe(monkeypatch, title_holder):
    class PermissionError(Exception):
        def __init__(self, message="", title=None):
            super().__init__(message)
            self.title = title

    frappe = types.ModuleType("frappe")
    frappe.__path__ = []  # mark it a package so ``from frappe.utils import ...`` works

    def throw(message, exc=None, title=None):
        title_holder["title"] = title
        raise (exc or PermissionError)(message, title=title)

    frappe.throw = throw
    frappe.PermissionError = PermissionError
    frappe._ = lambda text: text
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value: value
    frappe.utils = utils
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    return frappe


def test_require_roles_throws_with_stable_title(monkeypatch):
    holder = {}
    frappe = _stub_frappe(monkeypatch, holder)
    frappe.session = types.SimpleNamespace(user="someone@example.com")
    frappe.get_roles = lambda: []
    sys.modules.pop("asoud_erp.services.erp_documents", None)
    erp_documents = importlib.import_module("asoud_erp.services.erp_documents")

    try:
        erp_documents.require_roles(("HR Manager",))
    except frappe.PermissionError as error:
        assert error.title == "ROLE_REQUIRED"
    else:
        raise AssertionError("require_roles must raise without the role")
    assert holder["title"] == "ROLE_REQUIRED"


def test_require_company_throws_with_stable_title(monkeypatch):
    holder = {}
    frappe = _stub_frappe(monkeypatch, holder)
    frappe.session = types.SimpleNamespace(user="someone@example.com")
    sys.modules.pop("asoud_erp.services.request_access", None)
    request_access = importlib.import_module("asoud_erp.services.request_access")

    monkeypatch.setattr(request_access, "company_access", lambda company: False)
    try:
        request_access.require_company("Test Company")
    except frappe.PermissionError as error:
        assert error.title == "COMPANY_ACCESS_DENIED"
    else:
        raise AssertionError("require_company must raise without company access")
    assert holder["title"] == "COMPANY_ACCESS_DENIED"


def test_require_company_passes_when_access_is_granted(monkeypatch):
    holder = {"title": None}
    _stub_frappe(monkeypatch, holder)
    sys.modules.pop("asoud_erp.services.request_access", None)
    request_access = importlib.import_module("asoud_erp.services.request_access")

    monkeypatch.setattr(request_access, "company_access", lambda company: True)
    request_access.require_company("Test Company")  # no raise, no title recorded
    assert holder["title"] is None
