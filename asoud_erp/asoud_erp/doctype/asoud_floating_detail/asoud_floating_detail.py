import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDFloatingDetail(Document):
    def validate(self):
        if self.linked_document and not self.linked_doctype:
            frappe.throw(_("Linked DocType is required when a linked document is selected"))

