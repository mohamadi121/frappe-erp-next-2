"""Document templates and the workflow system actions that use them."""

import base64
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

PROOF_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")


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
                         "approval_mode": "Any", "allow_reject": True, "allow_return": True,
                         "reject_comment_required": True},
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

    def test_failed_action_without_error_route_stops_the_instance(self):
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

    def test_partial_write_rolls_back_and_activates_error_task(self):
        template = self._template()
        self._use_template(template["name"])
        error_stage = frappe.get_doc({
            "doctype": "ASOUD Workflow Stage", "workflow_definition": self.definition.name,
            "stage_key": "error-" + self.token, "stage_title": "بررسی خطا", "stage_type": "User Task",
            "sequence_no": 6, "configuration_status": "Complete",
            "config_json": json.dumps({"title": "بررسی خطا", "assignment_type": "Initiator"}),
        }).insert()
        workflow.save_stage_routes(self.definition.name, self.stages["System Action"].name,
                                   {"Success": self.stages["End"].name, "Error": error_stage.name})
        created = []
        create_document = document_templates.create_document

        def fail_after_insert(*args, **kwargs):
            doc = create_document(*args, **kwargs)
            self.assertTrue(frappe.db.exists("Journal Entry", doc.name))
            self.assertEqual(doc.total_debit, 1250)
            created.append(doc.name)
            raise frappe.ValidationError("failure after journal insert")

        before = frappe.db.count("Journal Entry")
        with patch.object(document_templates, "create_document", side_effect=fail_after_insert):
            request = self._submit_and_approve()
        self.assertEqual(len(created), 1)
        self.assertFalse(frappe.db.exists("Journal Entry", created[0]))
        self.assertEqual(frappe.db.count("Journal Entry"), before)
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertEqual((instance.status, instance.current_stage), ("Running", error_stage.name))
        tasks = frappe.get_all("ASOUD Workflow Task", filters={
            "workflow_instance": instance.name, "status": "Open"}, fields=["workflow_stage", "assigned_to"])
        self.assertEqual([(row.workflow_stage, row.assigned_to) for row in tasks],
                         [(error_stage.name, EMPLOYEE_USER)])
        activities = frappe.get_all("ASOUD Workflow Activity", filters={
            "workflow_instance": instance.name, "action": ["in", ["System Action Failed", "System Action Succeeded"]]},
            fields=["action", "comment", "reference_name"])
        self.assertEqual([(row.action, row.comment, row.reference_name or "") for row in activities],
                         [("System Action Failed", "failure after journal insert", "")])

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
        frappe.set_user(APPROVER_USER)
        self.assertEqual(workflow_request.get_request(request["name"])["data"]["subject"], "خرید تجهیزات")
        frappe.set_user(ACCOUNTANT_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.get_request(request["name"])

    def test_query_hooks_scope_requests_attachments_and_workflow_records(self):
        from frappe.client import get, get_list

        frappe.set_user(EMPLOYEE_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            request = workflow_request.create_request(
                self.company, self.definition.name, "خرید تجهیزات", "doc-hooks-" + self.token,
                values={"amount": 10},
                attachments=[{"filename": "proof.png",
                              "content_base64": base64.b64encode(PROOF_PNG).decode()}])["data"]
        instance = request["workflow_instance"]
        task = frappe.db.get_value("ASOUD Workflow Task",
                                   {"workflow_instance": instance, "status": "Open"}, "name")
        activity = frappe.db.get_value("ASOUD Workflow Activity", {"workflow_instance": instance},
                                       "name", order_by="creation asc")
        attachment = request["attachments"][0]["name"]
        self.assertTrue(all([task, activity, attachment]))
        records = [("ASOUD Workflow Request", request["name"]), ("ASOUD Workflow Instance", instance),
                   ("ASOUD Workflow Task", task), ("ASOUD Workflow Activity", activity)]
        assignee = self._user_with_roles("assignee", ["Accounts User"])
        frappe.db.set_value("ASOUD Workflow Task", task, "assigned_to", assignee)
        self._foreign_company()
        restricted = self._restricted_accounts("restricted")
        unrelated = self._unrelated_employee("other")
        foreign = self._foreign_request(EMPLOYEE_USER, restricted)

        def request_files(name: str) -> list:
            return [row.name for row in get_list("File", fields=["name"], filters={
                "attached_to_doctype": "ASOUD Workflow Request", "attached_to_name": name})]

        # The requester lists their own request and downloads their private attachment.
        frappe.set_user(EMPLOYEE_USER)
        self.assertEqual([row.name for row in get_list("ASOUD Workflow Request",
                                                        filters={"name": request["name"]},
                                                        fields=["name"])], [request["name"]])
        self.assertEqual(request_files(request["name"]), [attachment])
        self.assertEqual(get("ASOUD Workflow Request", request["name"])["subject"], "خرید تجهیزات")
        own_file = frappe.get_doc("File", attachment)
        self.assertTrue(frappe.has_permission("File", "read", own_file))
        self.assertTrue(own_file.is_downloadable())

        # Another employee of the same company neither lists nor downloads it.
        frappe.set_user(unrelated)
        self.assertEqual(get_list("ASOUD Workflow Request", filters={"name": request["name"]},
                                  fields=["name"]), [])
        self.assertEqual(request_files(request["name"]), [])
        with self.assertRaises(frappe.PermissionError):
            get("ASOUD Workflow Request", request["name"])
        self.assertFalse(frappe.has_permission("File", "read", own_file))
        self.assertFalse(own_file.is_downloadable())

        # The assignee sees the records; another privileged role does not.
        for user, visible in [(assignee, True), (ACCOUNTANT_USER, False)]:
            frappe.set_user(user)
            for doctype, name in records:
                listed = [row.name for row in get_list(doctype, filters={"name": name}, fields=["name"])]
                self.assertEqual(listed, [name] if visible else [], user)
                if not visible:
                    with self.assertRaises(frappe.PermissionError):
                        get(doctype, name)
            self.assertEqual(request_files(request["name"]), [attachment] if visible else [], user)

        # The records of another company stay hidden even from their own owner or assignee.
        for user in (EMPLOYEE_USER, restricted):
            frappe.set_user(user)
            self.assertEqual(get_list("ASOUD Workflow Request", filters={"name": foreign["request"]},
                                      fields=["name"]), [], user)
            self.assertEqual(request_files(foreign["request"]), [], user)
            with self.assertRaises(frappe.PermissionError):
                get("ASOUD Workflow Request", foreign["request"])
            foreign_file = frappe.get_doc("File", foreign["file"])
            self.assertFalse(frappe.has_permission("File", "read", foreign_file), user)
            self.assertFalse(foreign_file.is_downloadable(), user)
            self.assertFalse(frappe.has_permission("File", "read", frappe.get_doc(
                "File", foreign["public_file"])), user)
            if user == restricted:
                # The privileged assignee only loses access because of the company boundary.
                for doctype, name in [("ASOUD Workflow Instance", foreign["instance"]),
                                      ("ASOUD Workflow Task", foreign["task"])]:
                    self.assertEqual(get_list(doctype, filters={"name": name}, fields=["name"]), [], user)
                    with self.assertRaises(frappe.PermissionError):
                        get(doctype, name)

        frappe.set_user("Administrator")
        for doctype, name in records:
            self.assertEqual([row.name for row in get_list(doctype, filters={"name": name}, fields=["name"])],
                             [name])
        self.assertEqual(get("ASOUD Workflow Request", request["name"])["subject"], "خرید تجهیزات")
        self.assertTrue(frappe.get_doc("File", attachment).is_downloadable())
        self.assertEqual(get("ASOUD Workflow Request", foreign["request"])["subject"],
                         "درخواست خارجی " + self.token)
        self.assertTrue(frappe.get_doc("File", foreign["file"]).is_downloadable())
        self.assertFalse(frappe.get_doc("File", foreign["public_file"]).is_downloadable())

    def _user_with_roles(self, prefix: str, roles: list[str]) -> str:
        frappe.set_user("Administrator")
        return frappe.get_doc({"doctype": "User", "email": f"doc.{prefix}-{self.token}@example.com",
                               "first_name": prefix, "send_welcome_email": 0,
                               "roles": [{"role": role} for role in roles]}).insert().name

    def _restricted_accounts(self, prefix: str) -> str:
        user = self._user_with_roles(prefix, ["Accounts Manager"])
        frappe.get_doc({"doctype": "User Permission", "user": user, "allow": "Company",
                        "for_value": "ASOUD Foreign Request Co", "apply_to_all_doctypes": 1}).insert()
        return user

    def _unrelated_employee(self, prefix: str) -> str:
        user = self._user_with_roles(prefix, ["Employee"])
        frappe.get_doc({"doctype": "Employee", "first_name": prefix, "gender": "Male",
                        "date_of_birth": "1993-03-03", "date_of_joining": "2022-01-01",
                        "company": self.company, "status": "Active", "user_id": user,
                        "create_user_permission": 0}).insert(ignore_permissions=True)
        return user

    def _foreign_company(self) -> str:
        frappe.set_user("Administrator")
        if not frappe.db.exists("Company", "ASOUD Foreign Request Co"):
            frappe.get_doc({"doctype": "Company", "company_name": "ASOUD Foreign Request Co",
                            "abbr": "AFRC", "default_currency": "USD", "country": "United States",
                            "chart_of_accounts": "Standard"}).insert()
        return "ASOUD Foreign Request Co"

    def _foreign_request(self, owner: str, assignee: str) -> dict:
        """A request, instance, task and attachments that belong to another company."""
        frappe.set_user("Administrator")
        company = self._foreign_company()
        request = frappe.get_doc({"doctype": "ASOUD Workflow Request", "company": company,
                                  "workflow_definition": self.definition.name,
                                  "request_type": self.definition.workflow_title,
                                  "subject": "درخواست خارجی " + self.token, "priority": "Normal",
                                  "status": "Submitted", "owner": owner,
                                  "request_id": "doc-foreign-" + self.token,
                                  "values_json": json.dumps({"amount": 5}),
                                  "attachments_json": "[]"}).insert()
        frappe.db.set_value("ASOUD Workflow Request", request.name, "owner", owner)
        instance = frappe.get_doc({"doctype": "ASOUD Workflow Instance",
                                   "workflow_definition": self.definition.name,
                                   "subject": request.subject, "status": "Running",
                                   "reference_doctype": "ASOUD Workflow Request",
                                   "reference_name": request.name, "started_by": owner,
                                   "started_on": frappe.utils.now()}).insert()
        task = frappe.get_doc({"doctype": "ASOUD Workflow Task", "workflow_instance": instance.name,
                               "workflow_stage": self.stages["Approval"].name,
                               "task_title": "تأیید خارجی", "assigned_to": assignee,
                               "status": "Open"}).insert()
        file_doc = frappe.get_doc({"doctype": "File", "file_name": "foreign.png",
                                   "content": PROOF_PNG, "is_private": 1, "owner": owner,
                                   "attached_to_doctype": "ASOUD Workflow Request",
                                   "attached_to_name": request.name}).insert(ignore_permissions=True)
        frappe.db.set_value("File", file_doc.name, "owner", owner)
        public_file = frappe.get_doc({"doctype": "File", "file_name": "foreign-public.png",
                                      "content": PROOF_PNG, "owner": owner,
                                      "attached_to_doctype": "ASOUD Workflow Request",
                                      "attached_to_name": request.name}).insert(ignore_permissions=True)
        frappe.db.set_value("File", public_file.name, "owner", owner)
        return {"request": request.name, "instance": instance.name, "task": task.name,
                "file": file_doc.name, "public_file": public_file.name}

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

    # --- requester actions -------------------------------------------------------------------

    def _submit(self, suffix: str, amount=10):
        frappe.set_user(EMPLOYEE_USER)
        with patch.object(workflow_runtime, "_notify_user"):
            return workflow_request.create_request(
                self.company, self.definition.name, "خرید تجهیزات", "doc-" + suffix + "-" + self.token,
                values={"amount": amount})["data"]

    def test_submitting_fills_the_form_stage_and_reaches_the_manager(self):
        request = self._submit("auto")
        tasks = frappe.get_all("ASOUD Workflow Task", filters={"workflow_instance": request["workflow_instance"]},
                               fields=["assigned_to", "status"], order_by="creation asc")
        self.assertEqual([(t.assigned_to, t.status) for t in tasks],
                         [(EMPLOYEE_USER, "Completed"), (APPROVER_USER, "Open")])
        self.assertEqual(request["requester_name"], frappe.db.get_value(
            "Employee", {"user_id": EMPLOYEE_USER}, "employee_name"))
        self.assertTrue(request["creation"])

    def test_requester_edits_until_reviewed_then_cancels(self):
        request = self._submit("edit")
        updated = workflow_request.update_request(request["name"], "خرید لپ‌تاپ", {"amount": 55})["data"]
        self.assertEqual((updated["subject"], updated["values"]["amount"]), ("خرید لپ‌تاپ", 55))
        response = frappe.db.get_value("ASOUD Workflow Task", {
            "workflow_instance": request["workflow_instance"], "status": "Completed"}, "response_json")
        self.assertEqual(json.loads(response)["amount"], 55)
        with self.assertRaises(frappe.ValidationError):
            workflow_request.update_request(request["name"], "خرید لپ‌تاپ", {"amount": "زیاد"})
        frappe.set_user(APPROVER_USER)
        with self.assertRaises(frappe.PermissionError):
            workflow_request.cancel_request(request["name"])
        frappe.set_user(EMPLOYEE_USER)
        cancelled = workflow_request.cancel_request(request["name"], "دیگر لازم نیست")["data"]
        self.assertEqual(cancelled["status"], "Cancelled")
        self.assertFalse(frappe.db.exists("ASOUD Workflow Task", {
            "workflow_instance": request["workflow_instance"], "status": "Open"}))
        with self.assertRaises(frappe.ValidationError):
            workflow_request.cancel_request(request["name"])

    def test_edit_is_refused_after_the_manager_acted(self):
        request = self._submit("late")
        frappe.set_user(APPROVER_USER)
        approval = frappe.db.get_value("ASOUD Workflow Task", {
            "workflow_instance": request["workflow_instance"], "status": "Open"}, "name")
        with patch.object(workflow_runtime, "_notify_user"):
            workflow_runtime.complete_workflow_task(approval, "Return", comment="مبلغ را اصلاح کنید")
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.ValidationError):
            workflow_request.update_request(request["name"], "خرید تجهیزات", {"amount": 20})
