import json

import frappe
from frappe.model.document import Document

from asoud_erp.services.organization_contract import validate_rows


class ASOUDOrganizationChart(Document):
    def validate(self):
        frappe.get_doc("Company", self.company).check_permission("read")
        rows = validate_rows(json.loads(self.structure_json or "[]"))
        for row in rows:
            if row["employee"]:
                profile = frappe.get_doc("ASOUD Party Profile", row["employee"])
                profile.check_permission("read")
                if profile.company != self.company or profile.disabled:
                    frappe.throw("Employee is not active in this company")
                if "employee" not in json.loads(profile.roles_text or "[]"):
                    frappe.throw("Person must have the employee role")
        self.structure_json = json.dumps(rows, ensure_ascii=False)

