"""The classification registry must cover every whitelisted ``api/v1`` method.

These tests are pure (no ``frappe`` import) and run in the lightweight CI. The
central one, :func:`test_every_whitelisted_method_is_classified`, AST-walks every
``api/v1`` module and asserts that ``registry.classify`` resolves each whitelisted
method. It fails the moment a new method is added with a name that matches no rule
and no explicit entry, so a method can never ship unclassified.
"""

import ast
import sys
import types
from pathlib import Path

from asoud_erp.api.v1 import registry

_API_DIR = Path(__file__).resolve().parent.parent / "api" / "v1"


def _whitelisted_methods() -> list[str]:
    """Every ``@frappe.whitelist``-decorated function in ``api/v1`` as a full method name."""
    methods: list[str] = []
    for path in sorted(_API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", None) == "whitelist":
                    methods.append(f"asoud_erp.api.v1.{path.stem}.{node.name}")
    return methods


def test_every_whitelisted_method_is_classified():
    methods = _whitelisted_methods()
    assert methods, "no whitelisted methods found; the AST walk is broken"
    unclassified = []
    for method in methods:
        try:
            registry.classify(method)
        except registry.UnregisteredMethod:
            unclassified.append(method)
    assert not unclassified, (
        "whitelisted methods with no classification (add an EXACT entry or a rule): "
        + ", ".join(sorted(unclassified))
    )


def test_classify_returns_only_read_or_write():
    for method in _whitelisted_methods():
        assert registry.classify(method) in ("read", "write"), method


def test_sync_allow_list_matches_the_registry(monkeypatch):
    # The offline outbox must accept exactly the methods the registry marks as
    # queued mutations; a drift between the two would silently change routing.
    frappe = types.ModuleType("frappe")
    frappe.whitelist = lambda **_kwargs: lambda function: function
    frappe.throw = lambda message: (_ for _ in ()).throw(ValueError(message))
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("asoud_erp.api.v1.sync", None)
    from asoud_erp.api.v1 import sync

    for method in _whitelisted_methods():
        assert sync._is_mutation(method) == registry.is_queued_mutation(method), method


def test_void_and_reissue_are_classified_and_queued():
    # F-1: the app queues these two; they must be writes and accepted by the outbox.
    for method in (
        "asoud_erp.api.v1.workflow_request.void_native_document",
        "asoud_erp.api.v1.workflow_request.reissue_native_document",
    ):
        assert registry.classify(method) == "write", method
        assert registry.is_queued_mutation(method), method


def test_hr_save_report_is_a_write():
    # The documented mismatch: a write (save_ prefix, queued) that the Flutter client
    # still treats as read-only via the _report suffix. Kept "write" so the sync
    # behaviour is unchanged; the Flutter side is fixed separately.
    assert registry.classify("asoud_erp.api.v1.hr.save_report") == "write"
    assert registry.is_queued_mutation("asoud_erp.api.v1.hr.save_report")


def test_read_rules_and_exact_entries_agree_with_the_flutter_client():
    # Spot-check the ported read rules so a future edit cannot silently flip a read.
    assert registry.classify("asoud_erp.api.v1.workflow.validate_workflow") == "read"
    assert registry.classify("asoud_erp.api.v1.workflow.simulate_workflow") == "read"
    assert registry.classify("asoud_erp.api.v1.first_office_setup.status") == "read"
    assert registry.classify("asoud_erp.api.v1.employment_contracts.prepare_contract") == "read"
    assert registry.classify("asoud_erp.api.v1.session.login_state") == "read"
    assert registry.classify("asoud_erp.api.v1.setup_reset.status") == "read"
    assert registry.classify("asoud_erp.api.v1.setup_reset.preview") == "read"
    assert registry.classify("asoud_erp.api.v1.workflow.test_workflow_condition") == "read"
    assert registry.classify("asoud_erp.api.v1.organization.employee_photo") == "read"
    assert registry.classify("asoud_erp.api.v1.forms.employee_schedule") == "read"
    # A write that carries no write verb and is not queued.
    assert registry.classify("asoud_erp.api.v1.calendar.read_alert") == "write"
    assert not registry.is_queued_mutation("asoud_erp.api.v1.calendar.read_alert")


def test_unknown_method_is_rejected_by_the_outbox():
    # The allow-list stays closed: a name matching no rule and no exact entry is not queued.
    assert not registry.is_queued_mutation("asoud_erp.api.v1.workflow_request.void")
    assert not registry.is_queued_mutation("asoud_erp.api.v1.setup.set_something_else")
    assert not registry.is_queued_mutation("asoud_erp.api.v1.other.void_native_document")


def test_impactful_set_is_a_subset_of_writes():
    # Every impactful method must be a write; the gate only ever narrows, never widens.
    for method in _whitelisted_methods():
        if registry.is_impactful(method):
            assert registry.classify(method) == "write", method
    # A few known effectful writes are flagged.
    assert registry.is_impactful("asoud_erp.api.v1.workflow_request.void_native_document")
    assert registry.is_impactful("asoud_erp.api.v1.organization.reset_chart")
    assert registry.is_impactful("asoud_erp.api.v1.setup_reset.perform")
    # A plain read is never impactful.
    assert not registry.is_impactful("asoud_erp.api.v1.session.login_state")
