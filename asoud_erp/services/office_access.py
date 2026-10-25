"""Per-office roles for one account (multi-office access).

Native Frappe roles are global to a user. A role definition with ``scope = office`` is
therefore NOT written into ``User.roles``; it is granted per office through
``ASOUD Office Role Assignment`` and resolved here. The ASOUD gates
(``erp_documents.require_roles(..., company=)`` and ``request_access.company_access``)
use this resolver, so the same account can hold Finance in office 1, Management in
office 2 and nothing in office 3.

Limit (documented in docs/login-onboarding-audit.md): DocType-level permission checks
inside Frappe (``doc.insert()``) still see only the global roles.
"""

from collections.abc import Iterable


def merge_roles(global_roles: Iterable[str], office_roles: Iterable[str] | None) -> set[str]:
    return set(global_roles or ()) | set(office_roles or ())


def offices_of(assignments: Iterable[dict]) -> list[str]:
    """Distinct offices in assignment order."""
    return list(dict.fromkeys(row["company"] for row in assignments if row.get("company")))


def roles_by_office(assignments: Iterable[dict], base_roles_of) -> dict[str, list[str]]:
    """``{company: sorted base roles}`` from assignment rows and a ``code -> roles`` lookup."""
    result: dict[str, set[str]] = {}
    for row in assignments:
        result.setdefault(row["company"], set()).update(base_roles_of(row["role_definition"]))
    return {company: sorted(roles) for company, roles in result.items()}


# --- frappe adapters -------------------------------------------------------------------


def _assignments(user: str, company: str | None = None) -> list[dict]:
    import frappe

    if not frappe.db.table_exists("ASOUD Office Role Assignment"):
        return []
    filters = {"user": user}
    if company:
        filters["company"] = company
    return frappe.get_all("ASOUD Office Role Assignment", filters=filters,
                          fields=["company", "role_definition"], limit_page_length=0)


def _base_roles_lookup(codes):
    import frappe

    codes = list(set(codes))
    if not codes:
        return lambda code: []
    defs = frappe.get_all("ASOUD Role Definition", filters={"name": ["in", codes], "enabled": 1},
                          fields=["name", "role_profile"], limit_page_length=0)
    profiles = {d.name: d.role_profile for d in defs}
    rows = frappe.get_all("Has Role", filters={"parenttype": "Role Profile",
                                               "parent": ["in", list(profiles.values()) or [""]]},
                          fields=["parent", "role"], limit_page_length=0)
    by_profile: dict[str, list[str]] = {}
    for row in rows:
        by_profile.setdefault(row.parent, []).append(row.role)
    return lambda code: by_profile.get(profiles.get(code), [])


def office_roles(user: str, company: str) -> set[str]:
    rows = _assignments(user, company)
    lookup = _base_roles_lookup(r["role_definition"] for r in rows)
    return {role for r in rows for role in lookup(r["role_definition"])}


def effective_roles(user: str, company: str | None = None) -> set[str]:
    import frappe

    base = {r for r in frappe.get_roles(user) if r not in {"All", "Guest"}}
    return merge_roles(base, office_roles(user, company) if company else None)


def assigned_offices(user: str) -> list[str]:
    return offices_of(_assignments(user))


def office_role_map(user: str) -> dict[str, list[str]]:
    rows = _assignments(user)
    return roles_by_office(rows, _base_roles_lookup(r["role_definition"] for r in rows))
