"""Validate explicit personnel links without changing the native Employee tree.

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
        if "occupants" in row:
            normalized = []
            for value in row["occupants"]:
                employee = resolve_employee(value, company)
                frappe.get_doc("Employee", employee.name).check_permission("read")
                key = "employee:" + employee.name
                if key in normalized:
                    frappe.throw("انتساب تکراری یک پرسنل به همان جایگاه مجاز نیست.")
                normalized.append(key)
            row["occupants"] = normalized
            continue
        employee = resolve_employee(row["employee"], company)
        if not employee:
            continue
        frappe.get_doc("Employee", employee.name).check_permission("read")
        if employee.name in used:
            frappe.throw("An Employee cannot occupy more than one position: " + employee.name)
        used.add(employee.name)
        row["employee"] = "employee:" + employee.name
    return rows
