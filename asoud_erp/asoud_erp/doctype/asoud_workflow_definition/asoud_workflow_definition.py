import json

import frappe
from frappe import _
from frappe.model.document import Document


class ASOUDWorkflowDefinition(Document):
    def validate(self) -> None:
        before = self.get_doc_before_save()
        changed_source = (before and (before.get('source_form'), before.get('source_revision')) !=
            (self.get('source_form'), self.get('source_revision'))) or (
                not before and bool(self.get('source_form') or self.get('source_revision')))
        if changed_source and not self.flags.submission_source_service:
            frappe.throw('اتصال درخواست یا سند فقط از تنظیمات مرحله قابل تغییر است.')
        if changed_source and before and frappe.db.sql('select name from `tabASOUD Workflow Instance` '
                'where workflow_definition=%s and status=%s limit 1 for update', (self.name, 'Running')):
            frappe.throw('تا پایان گردش‌های در حال اجرا، تغییر منبع این گردش‌کار مجاز نیست.')
        activating = bool(before and before.status != 'Active' and self.status == 'Active')
        if self.get('source_form') and self.status != 'Archived' and (changed_source or activating):
            form = frappe.get_doc('ASOUD Form', self.source_form, for_update=True)
            if form.company != self.company or form.disabled or form.active_revision != self.source_revision:
                frappe.throw('منبع گردش‌کار باید فعال و نسخهٔ منتشرشدهٔ همین دفتر باشد.')
            if frappe.db.exists('ASOUD Workflow Definition', {'source_form': form.name,
                    'name': ['!=', self.name], 'status': ['!=', 'Archived']}):
                frappe.throw('این فرم قبلاً به گردش‌کار دیگری متصل شده است.')
        if self.status == "Active" and self.readiness_status != "Ready":
            frappe.throw(_("A workflow with incomplete prerequisites cannot be activated"))
        if self.status == "Active" and not self.frappe_workflow:
            frappe.throw(_("An active definition must be linked to a Frappe Workflow"))
        if self.template_key and frappe.db.exists("ASOUD Workflow Definition", {
                "company": self.company, "template_key": self.template_key, "name": ["!=", self.name]}):
            frappe.throw(_("This company already has a request type for template {0}").format(self.template_key))
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
