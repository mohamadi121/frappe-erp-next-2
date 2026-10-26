import frappe
from frappe.model.document import Document


class ASOUDCompanySetup(Document):
    def validate(self):
        if self.flags.first_office_bootstrap:
            return
        before = self.get_doc_before_save()
        for field in ("first_hr_user", "bootstrap_completed"):
            old = before.get(field) if before else None
            new = self.get(field)
            if field == "bootstrap_completed":
                old, new = frappe.utils.cint(old), frappe.utils.cint(new)
            if (new or None) != (old or None):
                frappe.throw("این تنظیم فقط از مسیر راه‌اندازی دفتر قابل تغییر است.", frappe.PermissionError)
