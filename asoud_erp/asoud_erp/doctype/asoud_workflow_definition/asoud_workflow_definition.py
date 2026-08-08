import json

import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDWorkflowDefinition(Document):
    def validate(self) -> None:
        if self.status == "Active" and self.readiness_status != "Ready":
            frappe.throw(_("A workflow with incomplete prerequisites cannot be activated"))
        if self.status == "Active" and not self.frappe_workflow:
            frappe.throw(_("An active definition must be linked to a Frappe Workflow"))
        if self.frappe_workflow:
            workflow_doctype = frappe.db.get_value("Workflow", self.frappe_workflow, "document_type")
            if workflow_doctype != self.target_doctype:
                frappe.throw(_("The linked Workflow belongs to another DocType"))
        self.missing_requirements_json = json.dumps(
            _parse_requirements(self.missing_requirements_json), ensure_ascii=False
        )


def _parse_requirements(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    values = json.loads(value) if isinstance(value, str) else value
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
