from frappe.model.document import Document


class ASOUDFormRevision(Document):
    def validate(self):
        from asoud_erp.services.form_schema import guard_storage

        guard_storage(self)
