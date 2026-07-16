from frappe.model.document import Document


class ASOUDSettings(Document):
    def validate(self):
        self.accounting_basis = "Accrual"

