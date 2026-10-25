"""Audit of account changes that bypass the ASOUD APIs (Desk, imports, scripts).

Hooked on ``User.on_update``: records role grants/revocations (admin authority transfer,
create-office grant) and account deactivation, with the acting session user.
"""

from asoud_erp.services import security_audit
from asoud_erp.services.delegation import OFFICE_CREATOR_ROLE
from asoud_erp.services.system_admin import SYSTEM_ADMIN_ROLE


def role_delta(before: set[str], after: set[str]) -> tuple[list[str], list[str]]:
    managed = lambda roles: {r for r in roles if not r.startswith("ASOUD-ACCESS-")}  # noqa: E731
    return sorted(managed(after) - managed(before)), sorted(managed(before) - managed(after))


def on_user_update(doc, method=None) -> None:
    before = doc.get_doc_before_save()
    if not before or doc.name in {"Guest"}:
        return
    added, removed = role_delta({r.role for r in before.roles}, {r.role for r in doc.roles})
    if added:
        security_audit.record("role.grant", target_type="User", target=doc.name, details={"roles": added})
    if removed:
        security_audit.record("role.revoke", target_type="User", target=doc.name, details={"roles": removed})
    if SYSTEM_ADMIN_ROLE in added or SYSTEM_ADMIN_ROLE in removed:
        security_audit.record("admin.authority_transfer", target_type="User", target=doc.name,
                              details={"direction": "granted" if SYSTEM_ADMIN_ROLE in added else "revoked"})
    if OFFICE_CREATOR_ROLE in added:
        security_audit.record("office.create_permission_grant", target_type="User", target=doc.name)
    if before.enabled and not doc.enabled:
        security_audit.record("account.deactivate", target_type="User", target=doc.name)
    elif not before.enabled and doc.enabled:
        security_audit.record("account.activate", target_type="User", target=doc.name)


def on_role_definition_update(doc, method=None) -> None:
    before = doc.get_doc_before_save()
    if before and (before.scope or "global") != (doc.scope or "global"):
        security_audit.record("role.scope_change", target_type="ASOUD Role Definition", target=doc.name,
                              details={"from": before.scope, "to": doc.scope})


def mirror_activity_log(doc, method=None) -> None:
    """Login/Logout rows of Frappe's Activity Log -> security audit (success and failure, no secrets)."""
    if doc.operation not in ("Login", "Logout"):
        return
    status = (doc.status or "").lower()
    result = "success" if status == "success" else "failure"
    security_audit.record(f"auth.{doc.operation.lower()}", result=result, actor=doc.user or "",
                          source=str(doc.ip_address or ""), target_type="User", target=doc.user or "",
                          details={"status": doc.status}, commit=False)
