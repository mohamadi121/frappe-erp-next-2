import frappe
from frappe.model.document import Document


class ASOUDOfficeRoleAssignment(Document):
    def validate(self):
        if frappe.db.get_value('ASOUD Role Definition', self.role_definition, 'template_key'):
            frappe.throw('پروفایل دسترسی را از تب دسترسی‌های حساب اعمال کنید؛ این گزینه نقش فنی نیست.')
        self.assignment_key = f"{self.user}|{self.company}|{self.role_definition}"
        other = frappe.db.exists("ASOUD Office Role Assignment",
                                 {"assignment_key": self.assignment_key, "name": ["!=", self.name]})
        if other:
            frappe.throw("این نقش پیش‌تر در همین دفتر به کاربر داده شده است.")
