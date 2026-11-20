import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDWorkflowTransition(Document):
    def validate(self) -> None:
        # Backstop for design writes that bypass the guarded whitelisted functions
        # (raw /api/resource, frappe.client, Desk, import, bulk edit): a running
        # instance reads its routes from these rows, so editing them while an
        # instance is Running (or the definition is Active) must be refused (PA-015).
        from asoud_erp.services.workflow_condition_binding import assert_design_editable

        assert_design_editable(self)
        if self.from_stage == self.to_stage:
            frappe.throw(_("A stage cannot transition to itself"))
        for field in ("from_stage", "to_stage"):
            stage_definition = frappe.db.get_value("ASOUD Workflow Stage", self.get(field), "workflow_definition")
            if stage_definition != self.workflow_definition:
                frappe.throw(_("Transition stages must belong to the same workflow"))

    def on_trash(self) -> None:
        from asoud_erp.services.workflow_condition_binding import assert_design_editable

        assert_design_editable(self)
