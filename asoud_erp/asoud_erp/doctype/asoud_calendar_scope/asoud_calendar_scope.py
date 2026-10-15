from frappe.model.document import Document

from asoud_erp.api.v1.calendar import guard


class ASOUDCalendarScope(Document):
    def validate(self):
        guard(self)

    def on_trash(self):
        guard(self)

