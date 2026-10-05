"""Central, allow-listed mapping between ASOUD personnel roles and Frappe roles."""

from collections.abc import Iterable

ASOUD_ROLE_TO_FRAPPE_ROLES: dict[str, tuple[str, ...]] = {
    "employee": ("Employee",),
    "office_manager": ("Accounts Manager",),
    "accountant": ("Accounts User",),
    "salesperson": ("Sales User",),
    "marketer": ("Sales User",),
    "cashier": ("Accounts User",),
    "petty_cash_custodian": ("Accounts User",),
}

# These labels are persisted by the current Flutter form. Keeping their mapping
# here makes the transition deterministic without treating arbitrary UI text as
# a security role.
LEGACY_PERSONNEL_ROLE_KEYS: dict[str, str] = {
    "کارمند": "employee",
    "مدیر": "office_manager",
    "حسابدار": "accountant",
    "فروشنده": "salesperson",
    "بازاریاب": "marketer",
    "صندوق": "cashier",
    "صندوق‌دار": "cashier",
    "تنخواه‌گردان": "petty_cash_custodian",
}


def normalize_asoud_roles(values: Iterable[str] | None) -> list[str]:
    """Return unique canonical keys and reject unknown security roles."""
    normalized: list[str] = []
    for raw_value in values or ():
        value = str(raw_value).strip()
        if not value or value.startswith("سیاست مانده:"):
            continue
        key = LEGACY_PERSONNEL_ROLE_KEYS.get(value, value)
        if key not in ASOUD_ROLE_TO_FRAPPE_ROLES:
            continue
        if key not in normalized:
            normalized.append(key)
    return normalized


def frappe_roles_for(values: Iterable[str] | None) -> list[str]:
    roles = {
        frappe_role
        for key in normalize_asoud_roles(values)
        for frappe_role in ASOUD_ROLE_TO_FRAPPE_ROLES[key]
    }
    return sorted(roles)


# The native roles that make an account a supervisor of a company; «سطح دسترسی»
# in the personnel file is derived from the roles the user actually holds.
MANAGER_ROLES = frozenset({
    "System Manager", "HR Manager", "Accounts Manager",
    "Sales Manager", "Purchase Manager", "Stock Manager",
})


def access_level_for(frappe_roles: Iterable[str] | None) -> str:
    """``manager`` for a supervisory role, ``user`` for any role, else ``none``."""
    roles = {str(role) for role in frappe_roles or ()}
    if roles & MANAGER_ROLES:
        return "manager"
    return "user" if roles else "none"
