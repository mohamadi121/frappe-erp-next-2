import json

import frappe
from frappe.model.document import Document

from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_employees import normalize_assignments, synchronize_managers


class ASOUDOrganizationChart(Document):
    def validate(self):
        frappe.get_doc("Company", self.company).check_permission("read")
        previous = self.get_doc_before_save()
        if previous and previous.company != self.company:
            frappe.throw("An organization chart cannot be moved to another company")
        frappe.db.sql("select name from tabCompany where name=%s for update", self.company)
        frappe.db.sql("select name from tabEmployee where company=%s order by name for update", self.company)
        rows = validate_rows(json.loads(self.structure_json or "[]"))
        rows = normalize_assignments(rows, self.company)
        old_rows = json.loads(previous.structure_json or "[]") if previous else []
        self.revision = ((previous.revision or 0) if previous else 0) + int(rows != old_rows)
        self.structure_json = json.dumps(rows, ensure_ascii=False)

    def before_save(self):
        previous = self.get_doc_before_save()
        old_rows = json.loads(previous.structure_json or "[]") if previous else []
        self.flags.organization_warnings = synchronize_managers(
            json.loads(self.structure_json), old_rows, self.company
        )

