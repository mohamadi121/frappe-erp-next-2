"""Privilege-escalation rules for granting roles (pure).

Rule: the system administrator may grant anything except what is protected by other
rules; everybody else may only hand out base roles they hold themselves, only with the
explicit delegate role, never the admin role, never in an office where they hold no role.
"""

from asoud_erp.services.system_admin import SYSTEM_ADMIN_ROLE

DELEGATE_ROLE = "ASOUD Role Assigner"
OFFICE_CREATOR_ROLE = "ASOUD Office Creator"
#: Roles only a system administrator may ever grant.
ADMIN_ONLY_ROLES = frozenset({SYSTEM_ADMIN_ROLE, DELEGATE_ROLE})
HR_ADMIN_ONLY_ROLES = frozenset({"HR", "HR User", "HR Manager"})


def escalation_violation(*, actor_is_admin: bool, actor_roles, granted_roles, actor_office_roles=None) -> str | None:
    """Persian refusal, or None when the grant stays within the actor's delegable authority.

    ``actor_office_roles`` is the set of roles the actor holds in the target office
    (``None`` for a site-wide grant).
    """
    if actor_is_admin:
        return None
    if set(granted_roles or ()) & HR_ADMIN_ONLY_ROLES:
        return "واگذاری نقش منابع انسانی فقط برای مدیر کل سیستم مجاز است."
    held = set(actor_roles or ())
    if DELEGATE_ROLE not in held:
        return "اجازه واگذاری نقش را ندارید."
    granted = set(granted_roles or ())
    if granted & ADMIN_ONLY_ROLES:
        return "واگذاری نقش مدیر کل یا مدیریت واگذاری نقش فقط برای مدیر کل سیستم مجاز است."
    if actor_office_roles is not None:
        held = set(actor_office_roles)
    missing = granted - held
    if missing:
        return "نمی‌توانید مجوزی را واگذار کنید که خودتان ندارید: " + "، ".join(sorted(missing))
    return None
