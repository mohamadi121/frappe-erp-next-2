import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import getdate, nowdate

from asoud_erp.services.request_templates.base import number_pattern, number_prefix


class ASOUDWorkflowRequest(Document):
    def autoname(self) -> None:
        """`PR-<jalali year>-<4 digits>` for system templates, `REQ-#####` for custom types.

        The sequence lives in the standard `tabSeries` table. `REQ-` is the key the old
        `format:REQ-{#####}` naming used, so custom request numbers continue without a gap.
        """
        key = self.template_key or (
            frappe.db.get_value("ASOUD Workflow Definition", self.workflow_definition, "template_key")
            if self.workflow_definition else None)
        self.name = make_autoname(number_pattern(number_prefix(key), getdate(nowdate())))
