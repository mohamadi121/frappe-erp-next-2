import frappe
from frappe.model.document import Document


class ASOUDOfficeRoleAssignment(Document):
    def validate(self):
        self.assignment_key = f"{self.user}|{self.company}|{self.role_definition}"
        other = frappe.db.exists("ASOUD Office Role Assignment",
                                 {"assignment_key": self.assignment_key, "name": ["!=", self.name]})
        if other:
            frappe.throw("این نقش پیش‌تر در همین دفتر به کاربر داده شده است.")
