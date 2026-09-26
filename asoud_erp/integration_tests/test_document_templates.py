"""Document templates and the workflow system actions that use them."""

import json
from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import document_templates, workflow, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    ITEM,
    APITestCase,
    abbr,
)


def _leaf_account(root_type: str) -> str:
    return frappe.get_all("Account", filters={"company": frappe.db.get_single_value(
        "Global Defaults", "default_company"), "root_type": root_type, "is_group": 0,
        "account_type": ["not in", ["Receivable", "Payable", "Bank", "Cash", "Stock"]]},
        pluck="name", order_by="name asc", limit=1)[0]


class TestDocumentTemplates(APITestCase):
    def setUp(self):
        super().setUp()
        self.token = uuid4().hex[:8]
        self.expense = _leaf_account("Expense")
        self.liability = _leaf_account("Liability")
        self.definition, self.stages = self._workflow()

    # --- helpers -----------------------------------------------------------------

    def _workflow(self):
        if not frappe.db.exists("Workflow State", "ASOUD Doc Draft"):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": "ASOUD Doc Draft"}).insert()
        if not frappe.db.exists("Workflow", "ASOUD Doc Request Native"):
            frappe.get_doc({"doctype": "Workflow", "workflow_name": "ASOUD Doc Request Native",
                            "document_type": "ASOUD Workflow Request", "is_active": 0,
                            "states": [{"state": "ASOUD Doc Draft", "doc_status": "0",
                                        "allow_edit": "System Manager"}]}).insert()
        definition = frappe.get_doc({
            "doctype": "ASOUD Workflow Definition", "workflow_code": "doc-" + self.token,
            "workflow_title": "درخواست هزینه " + self.token, "company": self.company,
            "module_key": "Purchase", "target_doctype": "ASOUD Workflow Request",
            "status": "Active", "readiness_status": "Ready", "allow_user_submission": 1,
            "frappe_workflow": "ASOUD Doc Request Native",
        }).insert()
        fields = [
            {"key": "amount", "label": "مبلغ", "type": "Number", "required": True},
            {"key": "items", "label": "اقلام", "type": "Item Table"},
        ]
        configs = {
            "Start": {"title": "شروع"},
            "User Task": {"title": "ثبت درخواست", "activity_type": "Data Entry",
                          "assignment_type": "Initiator", "form_fields": fields},
            "Approval": {"title": "تأیید مدیر", "assignment_type": "Direct Manager",
                         "approval_mode": "Any", "allow_reject": True, "reject_comment_required": True},
            "System Action": {"title": "ثبت سند", "action_type": "Change Status",
                              "request_status": "در حال ثبت"},
            "End": {"title": "پایان", "outcome": "Completed"},
        }
        stages = {}
        for index, (kind, config) in enumerate(configs.items()):
            stages[kind] = frappe.get_doc({
                "doctype": "ASOUD Workflow Stage", "workflow_definition": definition.name,
                "stage_key": f"{kind}-{self.token}", "stage_title": config["title"], "stage_type": kind,
                "sequence_no": index + 1, "config_json": json.dumps(config),
                "configuration_status": "Complete"}).insert()
        order = list(stages.values())
        for first, second in zip(order, order[1:]):
            frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": definition.name,
                            "from_stage": first.name, "to_stage": second.name}).insert()
        return definition, stages

    def _template(self, **mapping_changes):
        mapping = {
            "posting_date": {"source": "system", "value": "today"},
            "title": {"source": "fixed", "value": "هزینه بر اساس درخواست {{RequestNo}}"},
            "amount": {"source": "request", "value": "amount"},
            "debit_account": {"source": "fixed", "value": self.expense},
            "credit_account": {"source": "fixed", "value": self.liability},
            **mapping_changes,
        }
        return document_templates.save_document_template(
            self.company,
            {"title": "سند هزینه " + self.token, "module": "Finance", "document_type": "Journal Entry",
             "mapping": mapping},
            source_workflow=self.definition.name,
        )["data"]

    def _use_template(self, template: str, **extra):
        workflow.save_stage_settings(self.definition.name, self.stages["System Action"].name, {
            "title": "ثبت سند", "action_type": "Create Document", "document_template": template,
            "document_remark": "ایجاد خودکار بر اساس درخواست {{RequestNo}}", **extra})

    def _submit_and_approve(self, amount=1250):
        frappe.set_user(EMPLOYEE_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            request = workflow_request.create_request(
                self.company, self.definition.name, "خرید تجهیزات", "doc-req-" + self.token,
                values={"amount": amount, "items": [{"item_code": ITEM, "qty": 2}]})["data"]
            task = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": request["workflow_instance"], "status": "Open"}, "name")
            workflow_runtime.complete_workflow_task(task, "Complete")
            frappe.set_user(APPROVER_USER)
            approval = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": request["workflow_instance"], "status": "Open"},
                ["name", "assigned_to"], as_dict=True)
            self.assertEqual(approval.assigned_to, APPROVER_USER)  # the employee's direct manager
            workflow_runtime.complete_workflow_task(approval.name, "Approve")
        frappe.set_user("Administrator")
        return request

    # --- templates -----------------------------------------------------------------

    def test_options_list_modules_sources_and_request_fields(self):
        data = document_templates.document_template_options(self.company, self.definition.name)["data"]
        finance = next(module for module in data["modules"] if module["key"] == "Finance")
        self.assertTrue(next(t for t in finance["types"] if t["key"] == "Journal Entry")["enabled"])
        keys = {row["key"] for row in data["sources"]["request"]}
        self.assertTrue({"request_number", "amount", "items"} <= keys)
        self.assertIn("{{RequestNo}}", data["placeholders"])
        accounts = document_templates.document_template_link_options(self.company, "Account")["data"]
        self.assertIn(self.expense, {row["value"] for row in accounts})

    def test_save_validates_accounts_and_lists_custom_and_ready(self):
        saved = self._template()
        self.assertTrue(saved["create_as_draft"])
        custom = document_templates.list_document_templates(self.company, search=self.token)["data"]
        self.assertEqual([row["name"] for row in custom], [saved["name"]])
        ready = document_templates.list_document_templates(self.company, kind="ready", module="Finance")["data"]
        self.assertIn("purchase_expense", {row["name"] for row in ready})
        group = frappe.db.get_value("Account", {"company": self.company, "is_group": 1}, "name")
        with self.assertRaises(frappe.ValidationError):
            self._template(debit_account={"source": "fixed", "value": group})
        with self.assertRaises(frappe.ValidationError):
            self._template(amount={"source": "request", "value": "not_a_field"})

    def test_employee_cannot_manage_templates(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            document_templates.list_document_templates(self.company)

    # --- system actions --------------------------------------------------------------

    def test_approved_request_creates_draft_journal_entry_and_completes(self):
        template = self._template()
        self._use_template(template["name"])
        request = self._submit_and_approve()
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertEqual(instance.status, "Completed")
        activity = frappe.get_all("ASOUD Workflow Activity", filters={
            "workflow_instance": instance.name, "action": "System Action Succeeded"},
            fields=["reference_doctype", "reference_name"])[0]
        self.assertEqual(activity.reference_doctype, "Journal Entry")
        entry = frappe.get_doc("Journal Entry", activity.reference_name)
        self.assertEqual(entry.docstatus, 0)
        self.assertEqual(entry.title, f"هزینه بر اساس درخواست {request['name']}")
        self.assertEqual(entry.user_remark, f"ایجاد خودکار بر اساس درخواست {request['name']}")
        self.assertEqual(entry.total_debit, 1250)
        self.assertEqual({row.account for row in entry.accounts}, {self.expense, self.liability})

    def test_auto_submit_posts_the_journal_entry(self):
        template = self._template()
        frappe.db.set_value("ASOUD Document Template", template["name"],
                            {"auto_submit": 1, "create_as_draft": 0})
        self._use_template(template["name"])
        request = self._submit_and_approve(amount=900)
        name = frappe.db.get_value("ASOUD Workflow Activity", {
            "workflow_instance": request["workflow_instance"], "action": "System Action Succeeded"},
            "reference_name")
        self.assertEqual(frappe.db.get_value("Journal Entry", name, "docstatus"), 1)
        self.assertTrue(frappe.db.exists("GL Entry", {"voucher_no": name, "account": self.expense}))

    def test_failed_action_rolls_back_and_follows_the_error_route(self):
        template = self._template(amount={"source": "fixed", "value": "5"})
        self._use_template(template["name"])
        # A Receivable account needs a party, so ERPNext rejects the entry.
        receivable = frappe.db.get_value("Account", {"company": self.company, "account_type": "Receivable",
                                                     "is_group": 0}, "name")
        mapping = json.loads(frappe.db.get_value("ASOUD Document Template", template["name"], "mapping_json"))
        mapping["debit_account"]["value"] = receivable
        frappe.db.set_value("ASOUD Document Template", template["name"], "mapping_json", json.dumps(mapping))
        workflow.save_stage_routes(self.definition.name, self.stages["System Action"].name,
                                   {"Success": self.stages["End"].name, "Error": ""})
        before = frappe.db.count("Journal Entry")
        request = self._submit_and_approve()
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertEqual(instance.status, "Failed")
        self.assertEqual(frappe.db.count("Journal Entry"), before)
        self.assertTrue(frappe.db.exists("ASOUD Workflow Activity", {
            "workflow_instance": instance.name, "action": "System Action Failed"}))

    def test_change_status_action_sets_the_display_status(self):
        request = self._submit_and_approve()
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Request", request["name"], "display_status"),
                         "در حال ثبت")

    def test_inactive_or_foreign_templates_cannot_be_used(self):
        template = self._template()
        document_templates.set_document_template_status(template["name"], "Inactive")
        with self.assertRaises(frappe.ValidationError):
            self._use_template(template["name"])

    # --- routes and assignments ------------------------------------------------------------

    def test_stage_routes_replace_the_default_route(self):
        approval = self.stages["Approval"].name
        design = workflow.save_stage_routes(self.definition.name, approval, {
            "Approve": self.stages["End"].name, "Reject": self.stages["End"].name,
            "Return": self.stages["User Task"].name})["data"]
        routes = frappe.get_all("ASOUD Workflow Transition", filters={"from_stage": approval},
                                fields=["to_stage", "transition_label", "condition_json"])
        self.assertEqual(len(routes), 3)
        actions = {json.loads(row.condition_json)["action"]: row.to_stage for row in routes}
        self.assertEqual(actions["Return"], self.stages["User Task"].name)
        self.assertIn("transitions", design)
        workflow.save_stage_routes(self.definition.name, approval, {"Reject": ""})
        self.assertEqual(frappe.db.count("ASOUD Workflow Transition", {"from_stage": approval}), 2)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition.name, approval, {"Success": self.stages["End"].name})

    def test_reject_requires_a_reason_when_configured(self):
        frappe.set_user(EMPLOYEE_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            request = workflow_request.create_request(
                self.company, self.definition.name, "خرید تجهیزات", "doc-rej-" + self.token,
                values={"amount": 10})["data"]
            task = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": request["workflow_instance"], "status": "Open"}, "name")
            workflow_runtime.complete_workflow_task(task, "Complete")
            frappe.set_user(APPROVER_USER)
            approval = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": request["workflow_instance"], "status": "Open"}, "name")
            with self.assertRaises(frappe.ValidationError):
                workflow_runtime.complete_workflow_task(approval, "Reject")
            workflow_runtime.complete_workflow_task(approval, "Reject", comment="بودجه کافی نیست")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", request["workflow_instance"], "status"),
                         "Rejected")

    def test_initiator_department_assignment_reaches_colleagues(self):
        department = frappe.db.get_value("Employee", {"user_id": EMPLOYEE_USER}, "department")
        if not department:
            department = frappe.get_all("Department", filters={"company": self.company, "is_group": 0},
                                        pluck="name", limit=1)[0]
            frappe.db.set_value("Employee", {"user_id": EMPLOYEE_USER}, "department", department)
        frappe.db.set_value("Employee", {"user_id": APPROVER_USER}, "department", department)
        stage = self.stages["Approval"]
        stage.config_json = json.dumps({"title": "بررسی واحد", "assignment_type": "Initiator Department",
                                        "approval_mode": "Any"})
        stage.save()
        instance = frappe._dict(started_by=EMPLOYEE_USER, name="x",
                                workflow_definition=self.definition.name)
        with patch.object(workflow_runtime, "workflow_company", return_value=self.company):
            users = workflow_runtime._users_for_stage(stage, instance)
        self.assertIn(APPROVER_USER, users)
        self.assertIn(EMPLOYEE_USER, users)
        self.assertEqual(abbr(), frappe.get_cached_value("Company", self.company, "abbr"))

    def test_assignee_reads_the_request_but_others_do_not(self):
        frappe.set_user(EMPLOYEE_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            request = workflow_request.create_request(
                self.company, self.definition.name, "خرید تجهیزات", "doc-read-" + self.token,
                values={"amount": 10})["data"]
            task = frappe.db.get_value("ASOUD Workflow Task", {
                "workflow_instance": request["workflow_instance"], "status": "Open"}, "name")
            workflow_runtime.complete_workflow_task(task, "Complete")
        frappe.set_user(APPROVER_USER)
        self.assertEqual(workflow_request.get_request(request["name"])["data"]["subject"], "خرید تجهیزات")
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(request["name"])

    def test_material_request_template_copies_request_items(self):
        saved = document_templates.save_document_template(
            self.company,
            {"title": "درخواست کالا " + self.token, "module": "Purchase", "document_type": "Material Request",
             "mapping": {"transaction_date": {"source": "system", "value": "today"},
                         "schedule_date": {"source": "system", "value": "today"},
                         "items": {"source": "request", "value": "items"},
                         "set_warehouse": {"source": "fixed", "value": f"Stores - {abbr()}"}}},
            source_workflow=self.definition.name)["data"]
        context = {"request": {"items": [{"item_code": ITEM, "qty": 3, "uom": "Nos", "stock_uom": "Nos",
                                          "conversion_factor": 1}]},
                   "user": {}, "organization": {"company": self.company}, "system": {"today": self.future(0)}}
        doc = document_templates.create_document(saved["name"], context, self.company)
        self.assertEqual(doc.doctype, "Material Request")
        self.assertEqual(doc.material_request_type, "Purchase")
        self.assertEqual([(row.item_code, row.qty, row.warehouse) for row in doc.items],
                         [(ITEM, 3, f"Stores - {abbr()}")])
        with self.assertRaises(ValueError):
            document_templates.create_document(saved["name"], {**context, "request": {"items": []}}, self.company)

    def test_request_and_instance_expose_status_and_created_document(self):
        template = self._template()
        self._use_template(template["name"])
        request = self._submit_and_approve()
        frappe.set_user(EMPLOYEE_USER)
        instance = workflow_runtime.get_workflow_instance(request["workflow_instance"])["data"]
        created = [row for row in instance["activities"] if row["action"] == "System Action Succeeded"]
        self.assertEqual(created[0]["reference_doctype"], "Journal Entry")
        self.assertEqual(workflow_request.get_request(request["name"])["data"]["display_status"], "")
