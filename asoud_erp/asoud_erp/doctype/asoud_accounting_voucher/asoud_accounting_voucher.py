import frappe
from frappe import _
from frappe.model.document import Document

from asoud_erp.services.voucher_service import validate_voucher_lines


class ASOUDAccountingVoucher(Document):
    def validate(self):
        try:
            totals = validate_voucher_lines([row.as_dict() for row in self.lines])
        except ValueError as exc:
            frappe.throw(_(str(exc)))
        self.total_debit = totals.debit
        self.total_credit = totals.credit
        if not self.workflow_status:
            self.workflow_status = "Draft"
