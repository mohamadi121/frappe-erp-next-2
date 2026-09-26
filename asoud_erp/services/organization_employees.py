"""Validate explicit personnel links and update the native Employee tree.

No identity inference, Employee creation, role grant or payroll writes.
"""
import json

import frappe


def resolve_employee(value, company, *, strict=True, active=True):
    if not value:
        return None
    # New clients use a namespaced native ID. Legacy clients stored Party Profile
    # names; only the profile's explicit Employee link may migrate that identity.
    if value.startswith("employee:"):
        name = value[len("employee:"):]
    else:
        profile = frappe.db.get_value(
            "ASOUD Party Profile", value, ["company", "employee", "disabled", "roles_text"], as_dict=True
        )
        native_exists = frappe.db.exists("Employee", value)
        if profile:
            if (profile.company != company or (active and profile.disabled)
                    or not profile.employee
                    or (active and "employee" not in json.loads(profile.roles_text or "[]"))
                    or (native_exists and profile.employee != value)):
                if strict:
                    frappe.throw("Personnel link is invalid or ambiguous: " + value)
                return None
            name = profile.employee
        else:
            name = value if native_exists else None
    employee = frappe.db.get_value(
        "Employee", name, ["name", "company", "status", "reports_to"], as_dict=True
    ) if name else None
    if not employee or employee.company != company or (active and employee.status != "Active"):
        if strict:
            frappe.throw("Select an existing active Employee of this company: " + value)
        return None
    return employee


def normalize_assignments(rows, company):
    used = set()
    for row in rows:
        employee = resolve_employee(row["employee"], company)
        if not employee:
            continue
        frappe.get_doc("Employee", employee.name).check_permission("read")
        if employee.name in used:
            frappe.throw("An Employee cannot occupy more than one position: " + employee.name)
        used.add(employee.name)
        row["employee"] = "employee:" + employee.name
    return rows


def synchronize_managers(rows, previous, company):
    """Apply the direct occupied parent only; an empty parent never implies
    delegation to an ancestor. Native save validates and maintains NestedSet.
    All writes remain in the caller's transaction.
    """
    by_code = {row["code"]: row for row in rows}
    desired = {}
    for row in rows:
        if not row["employee"]:
            continue
        employee = row["employee"].removeprefix("employee:")
        parent = by_code.get(row["parent"], {})
        manager = parent.get("employee", "").removeprefix("employee:")
        desired[employee] = manager

    # Clearing an old assignment must not erase an unrelated manager set in HR.
    old_by_code = {row["code"]: row for row in previous}
    warnings = []
    for row in previous:
        value = row.get("employee", "")
        old = resolve_employee(value, company, strict=False, active=False)
        if value and old is None:
            warnings.append("Unresolved old assignment left untouched: " + value)
        if not old or old.name in desired:
            continue
        parent = old_by_code.get(row.get("parent"), {})
        former = resolve_employee(parent.get("employee", ""), company, strict=False, active=False)
        if former and (old.reports_to or "") == former.name:
            desired[old.name] = ""

    graph = {row.name: row.reports_to or "" for row in frappe.get_all(
        "Employee", fields=["name", "reports_to"], limit_page_length=0
    )}
    graph.update(desired)
    for employee in desired:
        cursor, visited = employee, set()
        while cursor:
            if cursor in visited:
                frappe.throw("The proposed manager relationship creates an Employee cycle")
            visited.add(cursor)
            cursor = graph.get(cursor, "")

    changes = {}
    for name, manager in desired.items():
        doc = frappe.get_doc("Employee", name, for_update=True)
        if (doc.reports_to or "") == manager:
            continue
        doc.check_permission("write")
        changes[name] = manager

    # Detach changing edges before reattaching: a valid swap must not encounter
    # a temporary native tree cycle. Never bypass native controller validation.
    for name in sorted(changes):
        doc = frappe.get_doc("Employee", name)
        if doc.reports_to:
            doc.reports_to = None
            doc.save()
    for name, manager in sorted(changes.items()):
        if manager:
            doc = frappe.get_doc("Employee", name)
            doc.reports_to = manager
            doc.save()
    return warnings
