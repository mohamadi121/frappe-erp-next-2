import json

import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDWorkflowStage(Document):
    def validate(self) -> None:
        if self.stage_type == "Start" and frappe.db.exists(
            "ASOUD Workflow Stage",
            {"workflow_definition": self.workflow_definition, "stage_type": "Start", "name": ["!=", self.name]},
        ):
            frappe.throw(_("A workflow can only have one start stage"))
        try:
            config = json.loads(self.config_json or "{}")
        except (TypeError, json.JSONDecodeError):
            frappe.throw(_("Stage configuration must be valid JSON"))
        if not isinstance(config, dict):
            frappe.throw(_("Stage configuration must be a JSON object"))
        self.config_json = json.dumps(config, ensure_ascii=False)
