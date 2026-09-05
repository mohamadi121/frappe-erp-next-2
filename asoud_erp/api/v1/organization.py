import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.organization_contract import validate_rows


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
    company = data["company"]
    _access(company, write=True)
    # Serialize both initial creation and later revision checks per company.
    frappe.db.sql("select name from tabCompany where name=%s for update", company)
    rows = validate_rows(data["rows"])
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    doc = frappe.get_doc("ASOUD Organization Chart", name) if name else frappe.new_doc("ASOUD Organization Chart")
    current = _snapshot(doc)
    if current["rows"] == rows:
        return success(current)
    if int(data.get("revision", 0)) != current["revision"]:
        frappe.throw("Organization chart changed on server; review before retrying", frappe.TimestampMismatchError)
    doc.company = company
    doc.structure_json = json.dumps(rows, ensure_ascii=False)
    doc.revision = current["revision"] + 1
    doc.save()
    return success(_snapshot(doc))

