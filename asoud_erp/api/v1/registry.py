"""Single classification registry for every whitelisted ``asoud_erp.api.v1`` method.

This module is the one place that decides, for each public method, whether it is a
read or a write, and whether the offline outbox (``sync.execute_mutation``) is
allowed to queue it. It is pure (no ``frappe`` import) so it runs in the lightweight
CI and can be read by the Flutter app's generated registry.

Two questions are answered separately, because they currently disagree for a few
methods and must not be conflated:

* ``classify(method)`` — the *semantic* kind: ``"read"`` or ``"write"``. This is what
  the AST test (``test_every_whitelisted_method_is_classified``) and the future
  Flutter read-only set consume.
* ``is_queued_mutation(method)`` — whether ``sync.execute_mutation`` accepts the
  method into the offline outbox. This reproduces the previous ``sync.py``
  allow-list *exactly*, so routing behaviour does not change (except the F-1
  ``void_native_document`` / ``reissue_native_document`` fix, which is now an
  explicit entry here).

The known mismatch: ``hr.save_report`` is a write (``save_`` prefix, queued by sync)
but the Flutter client still treats it as read-only (``_report`` suffix). It is
classified ``"write"`` here so the sync behaviour is preserved; the Flutter side is
fixed separately and the mismatch is listed in the delivery report, not silently
changed.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Write verbs — moved verbatim from the old ``sync._MUTATION_PREFIXES``.
# --------------------------------------------------------------------------- #
WRITE_PREFIXES: tuple[str, ...] = (
    "add_",
    "apply_",
    "approve_",
    "archive_",
    "cancel_",
    "complete_",
    "connect_",
    "create_",
    "delete_",
    "disable_",
    "import_",
    "insert_",
    "link_",
    "mark_",
    "publish_",
    "reject_",
    "return_",
    "save_",
    "seed_",
    "start_",
    "submit_",
    "update_",
    "upload_",
)

# Writes whose name carries no write verb and that the offline outbox must queue.
# These are the exact names the old ``sync._MUTATION_METHODS`` accepted.
QUEUED_EXACT: frozenset[str] = frozenset(
    [f"asoud_erp.api.v1.directives.{action}" for action in ("issue", "start", "report", "review", "transfer", "close")]
    # The app queues the active-office choice; `set_` is not a general write verb.
    + ["asoud_erp.api.v1.setup.set_default_office"]
    # F-1: the app queues void/reissue of an executed native document; neither verb
    # carries a write prefix, so both are listed by exact name.
    + ["asoud_erp.api.v1.workflow_request.void_native_document",
       "asoud_erp.api.v1.workflow_request.reissue_native_document"]
)


def is_queued_mutation(method: str) -> bool:
    """Whether ``sync.execute_mutation`` accepts ``method`` into the offline outbox.

    This is the exact behaviour of the previous ``sync._is_mutation``: a write-verb
    prefix, or one of the exact names in :data:`QUEUED_EXACT`.
    """
    action = method.rsplit(".", 1)[-1]
    return method in QUEUED_EXACT or action.startswith(WRITE_PREFIXES)


# --------------------------------------------------------------------------- #
# Read rules — ported from the Flutter client's ``isReadOnlyMethod`` so the two
# lists stay in agreement. A method is a read if it matches any of these.
# --------------------------------------------------------------------------- #
READ_EXACT: frozenset[str] = frozenset(
    {
        "asoud_erp.api.v1.first_office_setup.status",
        "asoud_erp.api.v1.employment_contracts.prepare_contract",
        # Read-only graph check; must never be queued as an offline write.
        "asoud_erp.api.v1.workflow.validate_workflow",
        # Side-effect-free simulation; must fail offline, never be queued.
        "asoud_erp.api.v1.workflow.simulate_workflow",
    }
)
READ_ACTION_EXACT: frozenset[str] = frozenset(
    {
        "execution_kinds",
        "options",
        "catalog",
        "organization_tree",
        "permission_preview",
        "directory",
        "editor",
        "stock_balance",
        "components",
        "run_financial_report",
        "tree",
        # Directive reads whose names do not start with a read verb.
        "reports",
        "history",
        "download_attachment",
    }
)
READ_ACTION_PREFIXES: tuple[str, ...] = ("print_",)
READ_ACTION_SUFFIXES: tuple[str, ...] = ("_options", "_fields", "_tree", "_report", "_summary", "_preview")
READ_PREFIXES: tuple[str, ...] = (
    "current_",
    "get_",
    "list_",
    "preview_",
    "trial_balance",
    "general_ledger",
    "purchase_request_options",
)


def _matches_read_rule(method: str) -> bool:
    if method in READ_EXACT:
        return True
    action = method.rsplit(".", 1)[-1]
    if action in READ_ACTION_EXACT:
        return True
    if action.startswith(READ_ACTION_PREFIXES):
        return True
    if action.endswith(READ_ACTION_SUFFIXES):
        return True
    return action.startswith(READ_PREFIXES)


# --------------------------------------------------------------------------- #
# Explicit classification for every method that matches neither a write prefix
# nor a read rule. Each entry is the *semantic* kind, with a one-line reason.
# --------------------------------------------------------------------------- #
EXACT: dict[str, str] = {
    # --- writes that carry no write verb (queued by the offline outbox) ---
    "asoud_erp.api.v1.directives.issue": "write",
    "asoud_erp.api.v1.directives.start": "write",
    "asoud_erp.api.v1.directives.report": "write",
    "asoud_erp.api.v1.directives.review": "write",
    "asoud_erp.api.v1.directives.transfer": "write",
    "asoud_erp.api.v1.directives.close": "write",
    "asoud_erp.api.v1.setup.set_default_office": "write",
    "asoud_erp.api.v1.workflow_request.void_native_document": "write",
    "asoud_erp.api.v1.workflow_request.reissue_native_document": "write",
    # The documented mismatch: a write (save_ prefix, queued) that the Flutter
    # client still treats as read-only via the _report suffix. Kept "write" so the
    # sync behaviour is unchanged; the Flutter side is fixed separately.
    "asoud_erp.api.v1.hr.save_report": "write",
    # --- writes that carry no write verb and are NOT queued by the outbox ---
    "asoud_erp.api.v1.access_profiles.invite_account": "write",
    "asoud_erp.api.v1.account_security.activate_account": "write",
    "asoud_erp.api.v1.account_security.change_password": "write",
    "asoud_erp.api.v1.account_security.confirm_password_reset": "write",
    "asoud_erp.api.v1.account_security.request_password_reset": "write",
    "asoud_erp.api.v1.auth.send_employee_invitation": "write",
    "asoud_erp.api.v1.auth.set_account_enabled": "write",
    "asoud_erp.api.v1.auth.sync_employee_access": "write",
    "asoud_erp.api.v1.automatic_actions.save": "write",
    # Marks a Notification Log read; a write despite the "read_" name.
    "asoud_erp.api.v1.calendar.read_alert": "write",
    "asoud_erp.api.v1.document_templates.set_document_template_status": "write",
    "asoud_erp.api.v1.employment_certificates.finalize_certificate": "write",
    "asoud_erp.api.v1.employment_contracts.finalize_contract": "write",
    "asoud_erp.api.v1.employment_contracts.send_contract_for_review": "write",
    "asoud_erp.api.v1.first_office_setup.complete": "write",
    "asoud_erp.api.v1.forms.copy_form": "write",
    "asoud_erp.api.v1.forms.open_builtin": "write",
    "asoud_erp.api.v1.forms.remove_builtin": "write",
    "asoud_erp.api.v1.forms.transition": "write",
    "asoud_erp.api.v1.hiring_orders.send_hiring_order_for_review": "write",
    "asoud_erp.api.v1.hr_onboarding.bootstrap_hr_lead": "write",
    "asoud_erp.api.v1.hr_onboarding.issue_temporary_password": "write",
    "asoud_erp.api.v1.hr_onboarding.register_personnel": "write",
    "asoud_erp.api.v1.organization.reset_chart": "write",
    "asoud_erp.api.v1.personnel_introduction_letters.finalize_letter": "write",
    "asoud_erp.api.v1.pos.close_pos_session": "write",
    "asoud_erp.api.v1.request_followup.confirm_receipt": "write",
    "asoud_erp.api.v1.role_access.assign_role": "write",
    "asoud_erp.api.v1.role_access.unassign_role": "write",
    "asoud_erp.api.v1.salary_change_orders.send_salary_change_order_for_review": "write",
    "asoud_erp.api.v1.session.logout": "write",
    "asoud_erp.api.v1.session.select_office": "write",
    "asoud_erp.api.v1.setup_reset.perform": "write",
    # The mutation protocol itself; sync rejects a recursive call via its own guard.
    "asoud_erp.api.v1.sync.execute_mutation": "write",
    "asoud_erp.api.v1.user_access.apply": "write",
    "asoud_erp.api.v1.workflow.set_workflow_status": "write",
    "asoud_erp.api.v1.workflow_paths.discard_inserted_stage": "write",
    "asoud_erp.api.v1.workflow_paths.remove_path": "write",
    # --- reads that carry no read rule ---
    "asoud_erp.api.v1.account_security.recovery_status": "read",
    "asoud_erp.api.v1.forms.employee_schedule": "read",
    "asoud_erp.api.v1.organization.employee_photo": "read",
    "asoud_erp.api.v1.role_management.system_admin_permissions": "read",
    "asoud_erp.api.v1.session.login_state": "read",
    "asoud_erp.api.v1.setup_reset.preview": "read",
    "asoud_erp.api.v1.setup_reset.status": "read",
    # Evaluates a condition on caller-supplied samples; it never writes anything.
    "asoud_erp.api.v1.workflow.test_workflow_condition": "read",
}


class UnregisteredMethod(KeyError):
    """Raised by :func:`classify` for a method that no rule and no EXACT entry covers."""

    def __init__(self, method: str) -> None:
        super().__init__(method)
        self.method = method


def classify(method: str) -> str:
    """Return the semantic kind of ``method``: ``"read"`` or ``"write"``.

    Resolution order: an explicit :data:`EXACT` entry, then a write-verb prefix,
    then the read rules. A method matching none raises :class:`UnregisteredMethod`,
    which the AST test turns into a CI failure so a new method can never ship
    unclassified.
    """
    if method in EXACT:
        return EXACT[method]
    action = method.rsplit(".", 1)[-1]
    if action.startswith(WRITE_PREFIXES):
        return "write"
    if _matches_read_rule(method):
        return "read"
    raise UnregisteredMethod(method)


# --------------------------------------------------------------------------- #
# Effectful writes — the subset of writes that change submitted / financial / HR
# state. This is the input for the future dry-run / confirmation gate; this plan
# only defines and tests the set, it does not enforce anything yet.
# --------------------------------------------------------------------------- #
_EFFECTFUL_PREFIXES: tuple[str, ...] = ("submit_", "cancel_", "void_", "approve_", "reject_", "delete_")
_EFFECTFUL_EXACT: frozenset[str] = frozenset(
    {
        "asoud_erp.api.v1.organization.reset_chart",
        "asoud_erp.api.v1.setup_reset.perform",
        "asoud_erp.api.v1.pos.close_pos_session",
        "asoud_erp.api.v1.workflow_request.void_native_document",
        "asoud_erp.api.v1.workflow_request.reissue_native_document",
        "asoud_erp.api.v1.workflow.set_workflow_status",
        "asoud_erp.api.v1.document_templates.set_document_template_status",
        "asoud_erp.api.v1.auth.set_account_enabled",
        "asoud_erp.api.v1.role_access.assign_role",
        "asoud_erp.api.v1.role_access.unassign_role",
        "asoud_erp.api.v1.employment_certificates.finalize_certificate",
        "asoud_erp.api.v1.employment_contracts.finalize_contract",
        "asoud_erp.api.v1.personnel_introduction_letters.finalize_letter",
        "asoud_erp.api.v1.request_followup.confirm_receipt",
    }
)


def is_impactful(method: str) -> bool:
    """Whether ``method`` is a write that changes submitted / financial / HR state."""
    if classify(method) != "write":
        return False
    action = method.rsplit(".", 1)[-1]
    return action.startswith(_EFFECTFUL_PREFIXES) or method in _EFFECTFUL_EXACT
