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
        previous = self.get_doc_before_save()
        if previous:
            old = json.loads(previous.config_json or '{}')
            is_v1 = (config.get('action_contract_version') == 1 or old.get('action_contract_version') == 1)
            if is_v1 and frappe.db.exists('ASOUD Workflow Task', {'workflow_stage': self.name}):
                config_or_type_changed = (old != config or previous.stage_type != self.stage_type)
                if config_or_type_changed:
                    task_count = frappe.db.count('ASOUD Workflow Task', {'workflow_stage': self.name})
                    frappe.throw(f'این مرحله توسط {task_count} کار در گردش‌کار استفاده می‌شود؛ تغییر تنظیمات یا ساختار نیازمند بازطراحی روی یک کپی مستقل است.')
        if self.stage_type == 'User Task' and config.get('action_contract_version') is not None and (
                not previous or old != config or previous.configuration_status != self.configuration_status):
            from asoud_erp.services.workflow_user_action import validate_design
            from asoud_erp.services.workflow_user_action_policy import normalize_action

            try:
                if self.configuration_status == 'Complete':
                    validate_design(self.workflow_definition, config)
                else:
                    config.update(normalize_action(config))
            except ValueError as error:
                frappe.throw(str(error))
        self.config_json = json.dumps(config, ensure_ascii=False)
