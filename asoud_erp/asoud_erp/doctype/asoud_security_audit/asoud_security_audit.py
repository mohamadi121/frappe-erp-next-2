import frappe
from frappe.model.document import Document


class ASOUDSecurityAudit(Document):
    """Append-only security trail: rows can be inserted by the service, never edited or deleted."""

    def validate(self):
        if not self.is_new():
            frappe.throw("سوابق امنیتی قابل ویرایش نیستند.", frappe.PermissionError)

    def on_trash(self):
        if frappe.flags.in_install or frappe.flags.in_test or frappe.flags.in_uninstall:
            return
        frappe.throw("سوابق امنیتی قابل حذف نیستند.", frappe.PermissionError)
