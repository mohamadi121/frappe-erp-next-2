import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from asoud_erp.api.v1 import auth, workflow, workflow_request, workflow_runtime
from asoud_erp.asoud_erp.doctype.asoud_personnel_record import test_asoud_personnel_record as fixtures


class TestASOUDWorkflowRequest(FrappeTestCase):
    rollback_test = fixtures.TestASOUDPersonnelNative.rollback_test

    def setUp(self):
        self.token = uuid4().hex[:10]
        fixtures.TestASOUDPersonnelNative.setUp(self)
        self.user = frappe.get_doc({"doctype": "User", "email": "audit-" + self.token + "@example.invalid",
            "first_name": "Audit", "send_welcome_email": 0,
            "roles": [{"role": "Employee"}]}).insert().name
        self.employee.user_id = self.user
        self.employee.create_user_permission = 0
        self.employee.save()
        if not frappe.db.exists("Workflow State", "Audit Draft"):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": "Audit Draft"}).insert()
        native_workflow = frappe.get_doc("Workflow", "Audit Request Native") if frappe.db.exists("Workflow", "Audit Request Native") else frappe.get_doc({"doctype": "Workflow", "workflow_name": "Audit Request Native",
            "document_type": "ASOUD Workflow Request", "is_active": 0,
            "states": [{"state": "Audit Draft", "doc_status": "0", "allow_edit": "System Manager"}]}).insert()
        self.definition = frappe.get_doc({"doctype": "ASOUD Workflow Definition",
            "workflow_code": "audit-" + self.token, "workflow_title": "Audit request", "company": self.company,
            "module_key": "Support", "target_doctype": "ASOUD Workflow Request",
            "status": "Active", "readiness_status": "Ready", "frappe_workflow": native_workflow.name}).insert()
        self.fields = [{"key": "amount", "label": "Amount", "type": "Number", "required": True}]
        self.stages = []
        for index, kind in enumerate(["Start", "User Task", "End"]):
            config = {"title": "Audit stage", "activity_type": "Data Entry",
                "assignment_type": "Initiator", "assignee_type": "Initiator", "form_fields": self.fields}
            self.stages.append(frappe.get_doc({"doctype": "ASOUD Workflow Stage",
                "workflow_definition": self.definition.name, "stage_key": "audit-stage-" + self.token + str(index),
                "stage_title": kind, "stage_type": kind, "sequence_no": index + 1,
                "config_json": json.dumps(config), "configuration_status": "Complete"}).insert())
        for first, second in zip(self.stages, self.stages[1:]):
            frappe.get_doc({"doctype": "ASOUD Workflow Transition",
                "workflow_definition": self.definition.name, "from_stage": first.name,
                "to_stage": second.name}).insert()
        frappe.set_user(self.user)

    def create(self, **changes):
        data = dict(company=self.company, workflow_definition=self.definition.name,
            subject="Audit request", request_id="audit-request-" + self.token, values={"amount": 123})
        data.update(changes)
        return workflow_request.create_request(**data)["data"]

    def test_employee_create_persists_values_and_retries_without_duplicate(self):
        with patch.object(workflow_runtime, "_notify_user"):
            first = self.create()
            self.assertEqual(self.create()["name"], first["name"])
            repeated = workflow_runtime.start_workflow_instance(self.definition.name, "Audit request",
                "ASOUD Workflow Request", first["name"])["data"]
        self.assertEqual(repeated["name"], first["workflow_instance"])
        self.assertEqual(frappe.db.count("ASOUD Workflow Instance", {"reference_name": first["name"]}), 1)
        draft = frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": first["workflow_instance"]}, "draft_json")
        self.assertEqual(json.loads(draft)["amount"], 123)
        with self.assertRaises(frappe.ValidationError):
            self.create(subject="Changed request")

    def test_standard_rest_cannot_read_another_request_or_write_own(self):
        from frappe.client import get, get_list
        with patch.object(workflow_runtime, "_notify_user"):
            first = self.create()
        doc = frappe.get_doc("ASOUD Workflow Request", first["name"])
        self.assertFalse(frappe.has_permission(doc.doctype, "write", doc))
        self.assertEqual(get(doc.doctype, doc.name)["subject"], "Audit request")
        frappe.db.set_value(doc.doctype, doc.name, "owner", "Administrator")
        # Stage assignees may read the request they act on; hand the task over too.
        frappe.db.set_value("ASOUD Workflow Task", {"workflow_instance": doc.workflow_instance},
            "assigned_to", "Administrator")
        with self.assertRaises(frappe.PermissionError):
            get(doc.doctype, doc.name)
        self.assertEqual(get_list(doc.doctype, fields=["name"]), [])
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(doc.name)

    def test_salary_hidden_from_standard_accounting_rest(self):
        from frappe.client import get

        from asoud_erp.services.personnel_contract import FINANCIAL_FIELDS
        frappe.set_user("Administrator")
        self.person.update({key: 12345 for key in FINANCIAL_FIELDS})
        self.person.save()
        user = frappe.get_doc({"doctype": "User", "email": "accounts-" + self.token + "@example.invalid",
            "first_name": "Accounts", "send_welcome_email": 0,
            "roles": [{"role": "Accounts User"}]}).insert()
        frappe.set_user(user.name)
        data = get(self.person.doctype, self.person.name)
        self.assertFalse(any(data.get(key) for key in FINANCIAL_FIELDS))

    def test_access_management_denies_employee_and_unsupported_permissions(self):
        with self.assertRaises(frappe.PermissionError):
            auth.get_employee_access(self.person.name)
        frappe.set_user("Administrator")
        with self.assertRaises(frappe.ValidationError):
            auth.sync_employee_access(self.person.name, self.user, ["employee"], {"salary": True})
        with self.assertRaises(frappe.PermissionError):
            auth.sync_employee_access(self.person.name, "administrator", ["employee"])
        with self.assertRaises(frappe.ValidationError):
            auth.send_employee_invitation(self.person.name, self.user, ["employee"], "audit-invite-123", method="SMS")

    def test_stage_form_fields_survive_save_and_reload(self):
        frappe.set_user("Administrator")
        workflow.save_stage_settings(self.definition.name, self.stages[1].name,
            {"title": "Audit form", "activity_type": "Data Entry", "assignment_type": "Initiator",
             "assignee_type": "Initiator", "form_fields": self.fields})
        stored = json.loads(frappe.get_doc("ASOUD Workflow Stage", self.stages[1].name).config_json)
        self.assertEqual(stored["form_fields"][0]["key"], "amount")
        self.assertTrue(stored["form_fields"][0]["required"])
        design = workflow.get_workflow_design(self.definition.name)["data"]
        self.assertIn("amount", json.dumps(design, default=str))


    def test_private_attachments_are_saved_and_owner_only(self):
        import base64
        from io import BytesIO

        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = BytesIO()
        writer.write(stream)
        encoded = base64.b64encode(stream.getvalue()).decode()
        with patch.object(workflow_runtime, "_notify_user"):
            request = self.create(attachments=[{"filename": "proof.pdf", "content_base64": encoded}])
        attachment = request["attachments"][0]
        self.assertTrue(attachment["file_url"].startswith("/private/files/"))
        self.assertEqual(workflow_request.get_attachment(attachment["name"])["data"]["content_base64"], encoded)
        frappe.db.set_value("ASOUD Workflow Request", request["name"], "owner", "Administrator")
        frappe.db.set_value("ASOUD Workflow Task", {"workflow_instance": request["workflow_instance"]},
            "assigned_to", "Administrator")
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_attachment(attachment["name"])
        file = frappe.get_doc("File", attachment["name"])
        self.assertFalse(frappe.has_permission("File", "read", file))
        self.assertFalse(file.is_downloadable())
        from frappe.core.doctype.file.utils import find_file_by_url
        self.assertIsNone(find_file_by_url(file.file_url, name=file.name))

    def test_email_is_queued_once_and_not_marked_sent(self):
        frappe.set_user("Administrator")
        original_exists = frappe.db.exists
        def exists(doctype, *args, **kwargs):
            return "audit-outgoing" if doctype == "Email Account" else original_exists(doctype, *args, **kwargs)
        with patch.object(frappe.db, "exists", side_effect=exists), patch("frappe.sendmail") as send:
            first = auth.send_employee_invitation(self.person.name, self.user, ["employee"], "invite-" + self.token)["data"]
            second = auth.send_employee_invitation(self.person.name, self.user, ["employee"], "invite-" + self.token)["data"]
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "Queued")
        send.assert_called_once()
        self.assertFalse(frappe.db.get_value("ASOUD Employee Invitation", first["name"], "sent_at"))
        self.assertEqual(frappe.db.get_value("Employee", self.employee.name, "user_id"), self.user)
        auth.delete_employee_access(self.person.name)
        self.assertTrue(frappe.db.get_value("User", self.user, "enabled"))
        self.assertFalse(frappe.db.get_value("Employee", self.employee.name, "user_id"))


    def test_request_status_tracks_completed_workflow_and_company_revocation(self):
        from frappe.client import get_list
        with patch.object(workflow_runtime, "_notify_user"):
            request = self.create()
            task = frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": request["workflow_instance"]}, "name")
            workflow_runtime.complete_workflow_task(task, "Complete", response={"amount": 321})
        self.assertEqual(workflow_request.get_request(request["name"])["data"]["status"], "Completed")
        frappe.db.set_value("Employee", self.employee.name, "status", "Left")
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(request["name"])
        self.assertEqual(get_list("ASOUD Workflow Request", fields=["name"]), [])

    def test_accounting_cannot_read_other_request_through_workflow_records(self):
        from frappe.client import get, get_list
        with patch.object(workflow_runtime, "_notify_user"):
            request = self.create()
        task = frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": request["workflow_instance"]}, "name")
        frappe.set_user("Administrator")
        account = frappe.get_doc({"doctype": "User", "email": "manager-" + self.token + "@example.invalid",
            "first_name": "Accounts", "send_welcome_email": 0, "roles": [{"role": "Accounts Manager"}]}).insert()
        frappe.set_user(account.name)
        for doctype, name in [("ASOUD Workflow Instance", request["workflow_instance"]), ("ASOUD Workflow Task", task)]:
            with self.assertRaises(frappe.PermissionError):
                get(doctype, name)
            self.assertEqual(get_list(doctype, filters={"name": name}, fields=["name"]), [])
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime.get_workflow_instance(request["workflow_instance"])
        with self.assertRaises(frappe.PermissionError):
            workflow_runtime._validate_response_attachments([{"key": "proof", "type": "Attachment"}],
                {"proof": "/private/files/unknown.pdf"})


    def test_home_self_service_uses_current_employee_and_native_status(self):
        from asoud_erp.api.v1 import hr, personnel
        home = hr.get_my_profile()["data"]
        self.assertEqual(home["party_profile"], self.person.name)
        detail = personnel.get_personnel(self.person.name)["data"]
        self.assertFalse(detail["can_edit"])
        self.assertFalse(detail["profile"]["disabled"])
        from asoud_erp.services.personnel_contract import FINANCIAL_FIELDS
        self.assertFalse(FINANCIAL_FIELDS.intersection(detail["profile"]))
        with self.assertRaises(frappe.PermissionError):
            personnel.update_personnel(self.person.name, {"display_name": "Unauthorized"}, detail["revision"], "denied-" + self.token)
        frappe.set_user("Administrator")
        frappe.db.set_value("Employee", self.employee.name, "status", "Left")
        self.assertTrue(personnel.get_personnel(self.person.name)["data"]["profile"]["disabled"])

    def test_request_type_settings_limit_who_can_submit(self):
        frappe.set_user("Administrator")
        self.definition.db_set("allow_user_submission", 0)
        frappe.set_user(self.user)
        options = workflow_request.request_options(self.company)["data"]
        self.assertNotIn(self.definition.name, [row["name"] for row in options])
        with self.assertRaises(frappe.PermissionError):
            self.create()
        frappe.set_user("Administrator")
        self.definition.db_set("allow_user_submission", 1)
        self.stages[0].db_set("config_json", json.dumps(
            {"trigger_type": "Manual", "initiator_roles": ["Accounts Manager"]}))
        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError):
            self.create()

    def test_item_table_rows_use_erpnext_item_and_uom(self):
        frappe.set_user("Administrator")
        if not frappe.db.exists("UOM", "Box"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Box"}).insert()
        item = frappe.get_doc({"doctype": "Item", "item_code": "AUDIT-" + self.token,
            "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 0,
            "uoms": [{"uom": "Box", "conversion_factor": 10}]}).insert()
        fields = [{"key": "items", "label": "Items", "type": "Item Table", "required": True}]
        self.stages[1].db_set("config_json", json.dumps({"title": "Audit stage",
            "activity_type": "Data Entry", "assignment_type": "Initiator", "form_fields": fields}))
        frappe.set_user(self.user)
        with patch.object(workflow_runtime, "_notify_user"):
            with self.assertRaises(frappe.ValidationError):
                self.create(values={"items": [{"item_code": item.name, "qty": 2, "uom": "Kg"}]},
                            request_id="audit-bad-uom-" + self.token)
            created = self.create(values={"items": [{"item_code": item.name, "qty": 2, "uom": "Box"}]})
        row = created["values"]["items"][0]
        self.assertEqual((row["stock_uom"], row["conversion_factor"], row["stock_qty"]), ("Nos", 10, 20))
