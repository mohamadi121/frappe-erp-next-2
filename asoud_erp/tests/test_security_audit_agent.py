"""Pure tests for the optional ``agent`` field on ASOUD Security Audit.

``build_row(agent=...)`` adds an ``agent`` key; the default path (no ``agent``)
produces a dict byte-identical to the pre-change code (no ``agent`` key at all).
``record(agent=...)`` passes the value through to ``build_row`` while ``actor``
stays the principal.
"""

import importlib
import sys
from types import ModuleType, SimpleNamespace

# Minimal fake frappe so the module imports without a bench.
fake_frappe = ModuleType("frappe")
fake_frappe._ = lambda value: value
fake_frappe.session = SimpleNamespace(user="principal@example.com")
fake_frappe.flags = SimpleNamespace(in_test=True)
fake_frappe.log_error = lambda **k: None
fake_frappe.local = SimpleNamespace(request_ip=None, form_dict={})
sys.modules.setdefault("frappe", fake_frappe)

fake_utils = ModuleType("frappe.utils")
fake_utils.now_datetime = lambda: "2026-01-01 00:00:00"
sys.modules.setdefault("frappe.utils", fake_utils)

security_audit = importlib.import_module("asoud_erp.services.security_audit")


def test_build_row_default_has_no_agent_key():
    """Default path is byte-identical: no ``agent`` key in the dict."""
    row = security_audit.build_row(
        actor="a@x", action="auth.login", result="success",
        source="1.2.3.4", target="a@x", company="C",
        details={"reason": "ok"}, occurred_on="2026-01-01 00:00:00",
    )
    assert "agent" not in row, f"default row must not carry an agent key, got {row!r}"
    assert row["actor"] == "a@x"
    assert row["action"] == "auth.login"


def test_build_row_with_agent_sets_key():
    row = security_audit.build_row(
        actor="principal@x", action="auth.login", result="success",
        source="1.2.3.4", target="a@x", company="C",
        details={}, occurred_on="2026-01-01 00:00:00",
        agent="my-agent",
    )
    assert row["agent"] == "my-agent"
    assert row["actor"] == "principal@x", "actor must stay the principal"


def test_build_row_agent_truncated_to_140():
    row = security_audit.build_row(
        actor="a", action="x", result="success",
        agent="A" * 200,
    )
    assert len(row["agent"]) == 140


def test_build_row_agent_empty_string_is_omitted():
    """An empty-string agent is treated the same as no agent (key absent)."""
    row = security_audit.build_row(
        actor="a", action="x", result="success", agent="",
    )
    assert "agent" not in row


def _install_fake_frappe(monkeypatch, captured):
    """Patch sys.modules so record()'s internal `import frappe` sees the fake."""
    def fake_get_doc(row):
        captured.update(row)
        return SimpleNamespace(insert=lambda **k: None)

    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(
        get_doc=fake_get_doc,
        session=SimpleNamespace(user="principal@x"),
        flags=SimpleNamespace(in_test=True),
        log_error=lambda **k: None,
        local=SimpleNamespace(request_ip=None, form_dict={}),
    ))
    monkeypatch.setitem(sys.modules, "frappe.utils", SimpleNamespace(
        now_datetime=lambda: "2026-01-01 00:00:00",
    ))


def test_record_default_does_not_pass_agent(monkeypatch):
    """record() without agent= must produce a row with no agent key."""
    captured = {}
    _install_fake_frappe(monkeypatch, captured)

    security_audit.record("test.action", actor="principal@x")
    assert "agent" not in captured, f"default record() must not set agent, got {captured!r}"
    assert captured["actor"] == "principal@x"


def test_record_with_agent_sets_key(monkeypatch):
    """record(agent=...) must set the agent field and keep actor as principal."""
    captured = {}
    _install_fake_frappe(monkeypatch, captured)

    security_audit.record("test.action", actor="principal@x", agent="my-agent")
    assert captured["agent"] == "my-agent"
    assert captured["actor"] == "principal@x", "actor must stay the principal"
