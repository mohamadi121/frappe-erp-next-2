import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from asoud_erp.services.organization_assignments import reconcile
from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_employees import normalize_assignments
from asoud_erp.services.organization_units import validate_position_units


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
        validate_position_units(rows, self.company)
        old_rows = json.loads(previous.structure_json or "[]") if previous else []
        try:
            rows = reconcile(rows, old_rows, str(now_datetime()), frappe.session.user)
        except ValueError as error:
            frappe.throw(str(error))
        self.revision = ((previous.revision or 0) if previous else 0) + int(rows != old_rows)
        self.structure_json = json.dumps(rows, ensure_ascii=False)

    def before_save(self):
        # HR explicitly owns Employee.reports_to; never infer it from positions.
        self.flags.organization_warnings = []

