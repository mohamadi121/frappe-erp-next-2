import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_employees import normalize_assignments


def _access(company, write=False):
    frappe.get_doc("Company", company).check_permission("read")
    allowed = {"System Manager", "HR Manager"} if write else {"System Manager", "HR Manager", "HR User"}
    if not allowed.intersection(frappe.get_roles()):
        frappe.throw("Not permitted", frappe.PermissionError)


def _snapshot(doc):
    return {"rows": json.loads(doc.structure_json or "[]"), "revision": doc.revision or 0}


@frappe.whitelist()
def get_chart(company):
    _access(company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    return success(_snapshot(frappe.get_doc("ASOUD Organization Chart", name)) if name else {"rows": [], "revision": 0})


@frappe.whitelist(methods=["POST"])
def save_chart(payload):
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or not data.get("company"):
        frappe.throw("Company and organization payload are required")
    company = data["company"]
    _access(company, write=True)
    # Serialize both initial creation and later revision checks per company.
    frappe.db.sql("select name from tabCompany where name=%s for update", company)
    # Lock the company's native employees in a stable order before checking
    # status, assignments and manager changes.
    frappe.db.sql("select name from tabEmployee where company=%s order by name for update", company)
    try:
        rows = validate_rows(data.get("rows"))
        revision = int(data.get("revision", 0))
    except (ValueError, TypeError) as error:
        frappe.throw(str(error))
    rows = normalize_assignments(rows, company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    doc = frappe.get_doc("ASOUD Organization Chart", name) if name else frappe.new_doc("ASOUD Organization Chart")
    current = _snapshot(doc)
    if current["rows"] == rows and revision != current["revision"]:
        return success(current)
    if current["rows"] != rows and revision != current["revision"]:
        frappe.throw("Organization chart changed on server; review before retrying", frappe.TimestampMismatchError)
    frappe.db.savepoint("organization_save")
    try:
        doc.company = company
        doc.structure_json = json.dumps(rows, ensure_ascii=False)
        doc.save()
        result = _snapshot(doc)
        result["warnings"] = doc.flags.organization_warnings or []
        return success(result)
    except Exception:
        frappe.db.rollback(save_point="organization_save")
        raise


@frappe.whitelist()
def list_employees(company):
    _access(company)
    employees = frappe.get_list(
        "Employee", filters={"company": company, "status": "Active"},
        fields=["name", "employee_name"], order_by="employee_name", limit_page_length=0,
    )
    return success({"employees": [
        {"id": "employee:" + row.name, "display_name": row.employee_name or row.name}
        for row in employees
    ]})

