"""«مدیر کل سیستم»: who the system administrator is, and the last-admin rule.

The system administrator is the existing, enabled System User that holds the native
``System Manager`` role. It is recognised by that role, never by "first login" and never
by a hard-coded user name. Scope is one Frappe site (one deployment): the role cannot
reach another site, and inside the site it is global over every office.

The pure rules (``admin_change_violation``) take plain values so they run without a
site; the ``frappe`` imports live inside the adapters.
"""

from collections.abc import Iterable

SYSTEM_ADMIN_ROLE = "System Manager"
#: Built-in accounts that Frappe itself protects; they never count as a "named" admin.
PROTECTED_USERS = frozenset({"Administrator", "Guest"})

LAST_ADMIN_MESSAGE = (
    "آخرین مدیر کل فعال سیستم را نمی‌توان حذف، غیرفعال یا از نقش مدیر کل خارج کرد؛ "
    "ابتدا مدیر کل جایگزین را تعیین کنید."
)


def holds_admin_role(roles: Iterable[str] | None) -> bool:
    return SYSTEM_ADMIN_ROLE in set(roles or ())


def is_active_admin(*, enabled, roles: Iterable[str] | None, user_type: str = "System User") -> bool:
    """An admin only counts while the account is enabled and is a real System User."""
    return bool(enabled) and user_type == "System User" and holds_admin_role(roles)


def admin_change_violation(
    *, target: str, was_admin: bool, will_be_admin: bool, other_active_admins: Iterable[str]
) -> str | None:
    """Persian refusal when a change would leave the site without a named active admin.

    ``other_active_admins`` are the enabled System Managers other than ``target``.
    ``Administrator``/``Guest`` are ignored on both sides: the built-in superuser is
    protected by Frappe and is not a replacement for a named administrator.
    """
    if target in PROTECTED_USERS:
        return None
    if not was_admin or will_be_admin:
        return None
    replacements = {name for name in other_active_admins if name not in PROTECTED_USERS and name != target}
    return None if replacements else LAST_ADMIN_MESSAGE


# --- frappe adapters -------------------------------------------------------------------


def roles_of(user: str) -> list[str]:
    import frappe

    return [role for role in frappe.get_roles(user) if role not in {"All", "Guest"}]


def is_system_admin(user: str | None = None) -> bool:
    """True for an enabled System User holding the admin role (``Administrator`` included)."""
    import frappe

    user = user or frappe.session.user
    if user == "Guest":
        return False
    if user == "Administrator":
        return True
    row = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    if not row:
        return False
    return is_active_admin(enabled=row.enabled, roles=roles_of(user), user_type=row.user_type)


def active_named_admins(exclude: str | None = None) -> list[str]:
    """Enabled System Managers (without the built-in accounts), optionally minus ``exclude``."""
    import frappe

    holders = frappe.get_all("Has Role", filters={"role": SYSTEM_ADMIN_ROLE, "parenttype": "User"},
                             pluck="parent", limit_page_length=0)
    holders = [name for name in set(holders) if name not in PROTECTED_USERS and name != exclude]
    if not holders:
        return []
    return sorted(frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1,
                                                   "user_type": "System User"},
                                 pluck="name", limit_page_length=0))


def _lock_admins() -> None:
    import frappe

    # Serialises concurrent demotions: two requests removing the last two admins at once.
    frappe.db.sql("select name from tabRole where name=%s for update", (SYSTEM_ADMIN_ROLE,))


def guard_user_change(doc, method=None) -> None:
    """``User.validate``: refuse to demote/disable the last named administrator."""
    import frappe

    if doc.is_new() or doc.name in PROTECTED_USERS:
        return
    before = doc.get_doc_before_save()
    if not before:
        return
    was_admin = is_active_admin(enabled=before.enabled, roles=[r.role for r in before.roles],
                                user_type=before.user_type)
    will_be_admin = is_active_admin(enabled=doc.enabled, roles=[r.role for r in doc.roles],
                                    user_type=doc.user_type)
    if was_admin and not will_be_admin:
        _lock_admins()
    message = admin_change_violation(target=doc.name, was_admin=was_admin, will_be_admin=will_be_admin,
                                     other_active_admins=active_named_admins(exclude=doc.name))
    if message:
        frappe.throw(message, frappe.PermissionError)


def guard_user_trash(doc, method=None) -> None:
    """``User.on_trash``: the last named administrator cannot be deleted."""
    import frappe

    if doc.name in PROTECTED_USERS:
        return
    # The standard User.on_trash disables the in-memory doc before hooks run: judge by the stored row.
    stored = frappe.db.get_value("User", doc.name, ["enabled", "user_type"], as_dict=True)
    if not stored:
        return
    stored_roles = frappe.get_all("Has Role", filters={"parent": doc.name, "parenttype": "User"},
                                  pluck="role", limit_page_length=0)
    was_admin = is_active_admin(enabled=stored.enabled, roles=stored_roles, user_type=stored.user_type)
    if was_admin:
        _lock_admins()
    message = admin_change_violation(target=doc.name, was_admin=was_admin, will_be_admin=False,
                                     other_active_admins=active_named_admins(exclude=doc.name))
    if message:
        frappe.throw(message, frappe.PermissionError)
