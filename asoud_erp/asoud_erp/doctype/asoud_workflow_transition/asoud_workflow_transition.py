import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDWorkflowTransition(Document):
    def validate(self) -> None:
        if self.from_stage == self.to_stage:
            frappe.throw(_("A stage cannot transition to itself"))
        for field in ("from_stage", "to_stage"):
            stage_definition = frappe.db.get_value("ASOUD Workflow Stage", self.get(field), "workflow_definition")
            if stage_definition != self.workflow_definition:
                frappe.throw(_("Transition stages must belong to the same workflow"))
