from frappe.model.document import Document


class ASOUDFormEntry(Document):
    def validate(self):
        from asoud_erp.services.form_schema import guard_storage

        guard_storage(self)
