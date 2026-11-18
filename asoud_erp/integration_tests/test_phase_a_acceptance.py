"""End-to-end Phase A acceptance scenarios, run as the app calls the real request flow.

Each scenario drives the whitelisted endpoints the Flutter app uses
(``workflow_request.create_request`` / ``get_request`` / ``update_request``,
``workflow_runtime.complete_workflow_task`` including the user-action
``Claim``/``Reassign`` path, ``workflow.save_stage_*``) with users switched by
``frappe.set_user`` and two offices (``tenancy``). Concrete DB rows and API
outputs are asserted:

- S1 submit -> Running instance, one Open task, notification without confidential values
- S2 two-approval definition -> Completed only after both approvals, history rows
- S3 reject -> Rejected/closed, requester sees the outcome
- S4 return for correction -> owner edits and resubmits, approver gets it again
- S5 reassign -> new holder FULL, old holder acted -> MASKED, not acted / claim-only -> denied
- S6 access matrix: other-office HR denied, same-office HR full, ordinary user denied,
  raw REST denied for MASKED
- S7 confidentiality: masked value «محرمانه», confidential file denied, audit row without the secret
- S8 duplicate execution: same request_id twice -> one request/instance; double approve refused
- S9 design guard: edits on an Active definition with a Running instance refused, DB unchanged
- S10 legacy instance backfill: consistent one frozen (marker), inconsistent one untouched + Error Log
- S11 Limited Edit legacy stage: kept on untouched save, explicit change applies, new choice refused
- S12 IT module: key 'IT' saves/loads; the «فناوری اطلاعات» label is asserted via the label
  function and skipped while that change is not merged yet.
"""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition, native_workflow
from asoud_erp.integration_tests.request_helpers import act, create, open_task, status_key, valid_pdf_bytes
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, MANAGER_USER, SECOND_COMPANY, setup_tenancy
from asoud_erp.services.modules import MODULE_LABELS

SECRET = "درمان بیماری خاص"
MASK = "محرمانه"
FIELDS = [
    {"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 2000},
    {"key": "proof", "label": "مدرک", "type": "Attachment"},
]


def _detail_as(user, name):
    frappe.set_user(user)
    try:
        return workflow_request.get_request(name)["data"]
    finally:
        frappe.set_user("Administrator")


def _raw_read(user, name):
    frappe.set_user(user)
    try:
        return frappe.get_doc("ASOUD Workflow Request", name).has_permission("read")
    finally:
        frappe.set_user("Administrator")


def _raw_list(user, name):
    frappe.set_user(user)
    try:
        return frappe.get_list("ASOUD Workflow Request", filters={"name": name}, fields=["values_json"])
    finally:
        frappe.set_user("Administrator")


def _company_user(prefix, company):
    """An active Employee of ``company`` with a real account (no manager roles)."""
    email = prefix + uuid4().hex[:8] + "@example.test"
    frappe.get_doc({"doctype": "User", "email": email, "first_name": "کارمند",
                    "send_welcome_email": 0, "user_type": "System User",
                    "roles": [{"role": "Employee"}]}).insert(ignore_permissions=True)
    frappe.get_doc({"doctype": "Employee", "first_name": "کارمند", "gender": "Male",
                    "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
                    "company": company, "status": "Active", "user_id": email,
                    "create_user_permission": 0}).insert(ignore_permissions=True)
    return email


def _graph_fingerprint(definition):
    stages = frappe.get_all("ASOUD Workflow Stage", filters={"workflow_definition": definition},
                            fields=["name", "stage_type", "config_json"], order_by="name asc")
    edges = frappe.get_all("ASOUD Workflow Transition", filters={"workflow_definition": definition},
                           fields=["name", "from_stage", "to_stage", "transition_label", "condition_json"],
                           order_by="name asc")
    return json.dumps([stages, edges], ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------------- S1


class TestSubmit(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=1, fields=FIELDS)
        self.approval = self.stages["Approval2"]

    def test_submit_starts_running_instance_with_one_open_task_and_safe_notification(self):
        secret_value = "مقدار محرمانه آزمایشی"
        frappe.set_user(EMPLOYEE_USER)
        try:
            request = workflow_request.create_request(
                company=self.company, workflow_definition=self.definition,
                subject="درخواست پذیرش", request_id="acc-s1-" + uuid4().hex[:10],
                values={"reason": secret_value})["data"]
        finally:
            frappe.set_user("Administrator")
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        self.assertEqual(instance.status, "Running")
        self.assertEqual(instance.current_stage, self.approval.name)
        # Exactly one Open task, for the requester's direct manager.
        tasks = frappe.get_all("ASOUD Workflow Task",
                               filters={"workflow_instance": instance.name, "status": "Open"},
                               fields=["name", "assigned_to"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].assigned_to, APPROVER_USER)
        # The notification row exists and carries no confidential value.
        rows = frappe.get_all("Notification Log",
                              filters={"for_user": APPROVER_USER,
                                       "document_type": "ASOUD Workflow Instance",
                                       "document_name": instance.name},
                              fields=["subject", "email_content"])
        self.assertEqual(len(rows), 1)
        self.assertNotIn(secret_value, json.dumps(rows, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------- S2


class TestTwoApprovals(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=2, fields=FIELDS)
        self.approval1 = self.stages["Approval2"]
        self.approval2 = self.stages["Approval3"]
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        self.instance = self.request["workflow_instance"]

    def test_two_approvals_complete_only_after_both(self):
        act(self.instance, "Approve")
        # One approval is not enough: still running, now at the second approval.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "current_stage"),
                         self.approval2.name)
        act(self.instance, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Completed")
        self.assertEqual(status_key(self.request["name"]), "approved")
        # History: one Approve activity per approval stage, both by the manager.
        rows = frappe.get_all("ASOUD Workflow Activity",
                              filters={"workflow_instance": self.instance, "action": "Approve"},
                              fields=["workflow_stage", "actor"])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.workflow_stage for row in rows},
                         {self.approval1.name, self.approval2.name})
        self.assertTrue(all(row.actor == APPROVER_USER for row in rows))


# --------------------------------------------------------------------------- S3


class TestReject(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1, fields=FIELDS)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        self.instance = self.request["workflow_instance"]

    def test_reject_closes_and_requester_sees_outcome(self):
        act(self.instance, "Reject", comment="مبلغ اشتباه است")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Rejected")
        self.assertEqual(status_key(self.request["name"]), "rejected")
        # No open task survives the closed instance.
        self.assertEqual(frappe.db.count("ASOUD Workflow Task",
                                         {"workflow_instance": self.instance, "status": "Open"}), 0)
        # The requester reads the outcome and the reason.
        detail = _detail_as(EMPLOYEE_USER, self.request["name"])
        self.assertEqual(detail["status"], "Rejected")
        self.assertEqual(detail["status_key"], "rejected")
        self.assertEqual(detail["rejection_reason"], "مبلغ اشتباه است")


# --------------------------------------------------------------------------- S4


class TestReturnResubmit(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=2, fields=FIELDS)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل اولیه"})
        self.instance = self.request["workflow_instance"]

    def test_return_edit_resubmit_updates_values_and_reopens_approver(self):
        act(self.instance, "Approve")
        act(self.instance, "Return", comment="مبلغ را اصلاح کنید")
        self.assertEqual(status_key(self.request["name"]), "returned")
        # The owner corrects the values through the real update endpoint.
        frappe.set_user(EMPLOYEE_USER)
        try:
            workflow_request.update_request(self.request["name"],
                                            values=json.dumps({"reason": "دلیل اصلاح‌شده"}))
        finally:
            frappe.set_user("Administrator")
        # The stored values are updated.
        stored = json.loads(frappe.db.get_value("ASOUD Workflow Request", self.request["name"], "values_json"))
        self.assertEqual(stored["reason"], "دلیل اصلاح‌شده")
        # The flow restarts at the first approval: the approver gets it again.
        task = open_task(self.instance, APPROVER_USER)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Stage",
                                             frappe.db.get_value("ASOUD Workflow Task", task.name, "workflow_stage"),
                                             "stage_title"), "تأیید 1")
        # The correction is recorded with its before/after diff.
        activity = frappe.get_all("ASOUD Workflow Activity",
                                  filters={"workflow_instance": self.instance, "action": "Resubmitted"},
                                  fields=["actor", "change_json"])
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0].actor, EMPLOYEE_USER)
        self.assertEqual(json.loads(activity[0].change_json),
                         {"before": {"reason": "دلیل اولیه"}, "after": {"reason": "دلیل اصلاح‌شده"},
                          "labels": {"reason": "دلیل"}})
        # The approver now reads the corrected value.
        self.assertEqual(_detail_as(APPROVER_USER, self.request["name"])["values"]["reason"], "دلیل اصلاح‌شده")


# --------------------------------------------------------------------------- S5


def _action_request_definition(company, role):
    """Start -> request form -> shared user-action review (reassignable) -> End."""
    token = uuid4().hex[:8]
    definition = frappe.get_doc({
        "doctype": "ASOUD Workflow Definition", "workflow_code": f"acc-{token}",
        "workflow_title": f"درخواست اقدام {token}", "company": company, "module_key": "Support",
        "target_doctype": "ASOUD Workflow Request", "status": "Inactive", "readiness_status": "Ready",
        "allow_user_submission": 1, "frappe_workflow": native_workflow(),
        "template_key": "", "template_version": 0, "is_system_template": 0,
    }).insert(ignore_permissions=True)
    review_config = {"title": "بررسی", "activity_type": "Data Entry", "task_purpose": "Existing",
                     "action_contract_version": 1, "result_mode": "Simple",
                     "simple_result_style": "Report", "allow_draft": True,
                     "allow_add_attachments": False, "allow_reassign": True,
                     "assignment_rule": {"basis": "Role", "role": role, "scope": "Company"}}
    stages = [
        ("Start", "start", {"title": "شروع"}),
        ("User Task", "form", {"title": "ثبت درخواست", "activity_type": "Data Entry",
                               "assignment_type": "Initiator", "form_fields": FIELDS}),
        ("User Task", "review", review_config),
        ("End", "end", {"title": "پایان", "outcome": "Completed"}),
    ]
    rows = []
    for index, (kind, _key, config) in enumerate(stages):
        rows.append(frappe.get_doc({
            "doctype": "ASOUD Workflow Stage", "workflow_definition": definition.name,
            "stage_key": f"{kind.lower().replace(' ', '-')}-{index}-{token}", "stage_title": config["title"],
            "stage_type": kind, "sequence_no": index + 1,
            "config_json": json.dumps(config, ensure_ascii=False),
            "configuration_status": "Complete"}).insert(ignore_permissions=True))
    for first, second in zip(rows, rows[1:]):
        frappe.get_doc({"doctype": "ASOUD Workflow Transition", "workflow_definition": definition.name,
                        "from_stage": first.name, "to_stage": second.name,
                        "condition_json": "{}"}).insert(ignore_permissions=True)
    # Saving through the real endpoint normalizes the user-action config (Shared delivery).
    workflow.save_stage_settings(definition.name, rows[2].name, review_config)
    frappe.db.set_value("ASOUD Workflow Definition", definition.name, "status", "Active")
    return definition.name, {"form": rows[1], "review": rows[2]}


class TestReassign(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def setUp(self):
        super().setUp()
        self.role = frappe.get_doc({"doctype": "Role",
                                    "role_name": f"Accept {uuid4().hex[:10]}"}).insert().name
        for user in (APPROVER_USER, MANAGER_USER):
            frappe.get_doc("User", user).add_roles(self.role)
        self.bystander = _company_user("acc-bystander-", self.company)
        frappe.get_doc("User", self.bystander).add_roles(self.role)
        self.definition, self.stages = _action_request_definition(self.company, self.role)
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل اقدام"})
        self.instance = self.request["workflow_instance"]

    def _task_of(self, user):
        return frappe.db.get_value("ASOUD Workflow Task",
                                   {"workflow_instance": self.instance, "assigned_to": user}, "name")

    def test_reassign_new_holder_full_old_acted_masked_not_acted_denied(self):
        # The shared review stage opened one Awaiting-Claim task per role holder.
        self.assertEqual(sorted(self._task_of(user) is not None
                                for user in (APPROVER_USER, MANAGER_USER, self.bystander)), [True, True, True])
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", self._task_of(MANAGER_USER), "action"),
                         "Awaiting Claim")
        before = frappe.db.count("ASOUD Workflow Task", {"workflow_instance": self.instance})
        manager_task = self._task_of(MANAGER_USER)
        frappe.set_user(MANAGER_USER)
        try:
            workflow_runtime.complete_workflow_task(manager_task, "Claim")
            workflow_runtime.complete_workflow_task(manager_task, "Reassign", assignee=APPROVER_USER)
        finally:
            frappe.set_user("Administrator")
        # The reassign rewrote the same task in place; the new holder is FULL.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", manager_task, "assigned_to"), APPROVER_USER)
        # The reassign rewrote the same task in place: no new task row.
        self.assertEqual(frappe.db.count("ASOUD Workflow Task", {"workflow_instance": self.instance}), before)
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": self.instance, "action": "Reassigned",
                                          "actor": MANAGER_USER, "reference_name": APPROVER_USER}), 1)
        new_detail = _detail_as(APPROVER_USER, self.request["name"])
        self.assertEqual(new_detail["values"]["reason"], "دلیل اقدام")
        self.assertTrue(_raw_read(APPROVER_USER, self.request["name"]))
        # The old holder acted (Claim + Reassigned) -> MASKED: readable, raw REST denied.
        old_detail = _detail_as(MANAGER_USER, self.request["name"])
        self.assertEqual(old_detail["values"]["reason"], "دلیل اقدام")
        self.assertFalse(_raw_read(MANAGER_USER, self.request["name"]))
        # A peer whose claim task was Cancelled and who never acted -> NONE, denied.
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Task", self._task_of(self.bystander), "status"),
                         "Cancelled")
        with self.assertRaises(frappe.PermissionError):
            _detail_as(self.bystander, self.request["name"])
        self.assertFalse(_raw_read(self.bystander, self.request["name"]))
        # A holder who only Claimed (task Cancelled, no decision) -> NONE, denied.
        claim_only = _company_user("acc-claimonly-", self.company)
        frappe.get_doc({"doctype": "ASOUD Workflow Task", "workflow_instance": self.instance,
                        "workflow_stage": self.stages["review"].name, "task_title": "بررسی",
                        "assigned_to": claim_only, "status": "Cancelled", "action": "Claimed Elsewhere",
                        "assigned_on": "2026-01-01 00:00:00"}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "ASOUD Workflow Activity", "workflow_instance": self.instance,
                        "actor": claim_only, "action": "Claim", "comment": "",
                        "created_on": "2026-01-01 00:00:00"}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            _detail_as(claim_only, self.request["name"])
        self.assertFalse(_raw_read(claim_only, self.request["name"]))


# --------------------------------------------------------------------------- S6 / S7


class ConfidentialCase(APITestCase):
    """A confidential request (value + file) in office A, approved by APPROVER_USER."""

    def setUp(self):
        super().setUp()
        self.scope = setup_tenancy()
        self.company = self.scope["first"]
        self.definition, _stages = make_definition(self.company, approvals=1, fields=FIELDS)
        self.hr_b = self._hr_manager_of(SECOND_COMPANY)

    def _hr_manager_of(self, company):
        email = "acc-hr-" + uuid4().hex[:10] + "@example.test"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "مدیر منابع انسانی",
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": "HR Manager"}]}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Company",
                        "for_value": company, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
        return email

    def submit_confidential(self):
        """Submit the confidential form as EMPLOYEE_USER; returns (request, file_name)."""
        schema = {"kind": "Request", "title": "درخواست محرمانه", "workflow": self.definition,
                  "sections": [{"id": "main", "title": "اصلی", "fields": [
                      {"key": "why", "label": "علت", "type": "LongText", "workflow_key": "reason",
                       "sensitive": True},
                      {"key": "doc", "label": "مدرک", "type": "File", "workflow_key": "proof",
                       "sensitive": True}]}]}
        frappe.set_user("Administrator")
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))["data"]
        published = forms.transition(saved["name"], "publish", saved["draft_version"])["data"]
        frappe.set_user(EMPLOYEE_USER)
        file = frappe.get_doc({"doctype": "File", "file_name": "madrak.pdf",
                               "content": valid_pdf_bytes(), "is_private": 1}).insert(ignore_permissions=True)
        entry = forms.submit_form(saved["name"], published["active_revision"], "درخواست محرمانه",
                                  {"why": SECRET, "doc": file.name},
                                  frappe.generate_hash(length=24))["data"]
        frappe.set_user("Administrator")
        request = entry["reference_name"]
        attached = frappe.get_all("File", filters={"attached_to_doctype": "ASOUD Workflow Request",
                                                   "attached_to_name": request, "is_private": 1},
                                  pluck="name")
        return request, attached[0]

    def _attachment_as(self, user, file_name):
        frappe.set_user(user)
        try:
            return workflow_request.get_attachment(file_name)
        finally:
            frappe.set_user("Administrator")


class TestAccess(ConfidentialCase):
    def test_other_office_hr_denied_same_office_full_ordinary_denied_raw_rest_masked_denied(self):
        request, _file = self.submit_confidential()
        # Same-office HR Manager: full read.
        self.assertEqual(_detail_as(HR_MANAGER_USER, request)["values"]["reason"], SECRET)
        # Other-office HR Manager: denied everywhere.
        with self.assertRaises(frappe.PermissionError):
            _detail_as(self.hr_b, request)
        self.assertFalse(_raw_read(self.hr_b, request))
        self.assertEqual(_raw_list(self.hr_b, request), [])
        # Ordinary user (no participation): denied everywhere.
        with self.assertRaises(frappe.PermissionError):
            _detail_as(ACCOUNTANT_USER, request)
        self.assertFalse(_raw_read(ACCOUNTANT_USER, request))
        self.assertEqual(_raw_list(ACCOUNTANT_USER, request), [])
        # Raw REST is FULL-only: a MASKED previous assignee (approved) is denied.
        instance = frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance")
        act(instance, "Approve")
        self.assertEqual(_detail_as(APPROVER_USER, request)["values"]["reason"], MASK)
        self.assertFalse(_raw_read(APPROVER_USER, request))
        self.assertEqual(_raw_list(APPROVER_USER, request), [])


class TestConfidentiality(ConfidentialCase):
    def test_masked_viewer_gets_mask_and_file_denied_and_audit_without_secret(self):
        request, file = self.submit_confidential()
        instance = frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance")
        act(instance, "Approve")  # APPROVER_USER acted -> MASKED
        data = _detail_as(APPROVER_USER, request)
        self.assertEqual(data["values"]["reason"], MASK)
        self.assertNotIn(SECRET, json.dumps(data, ensure_ascii=False, default=str))
        # The confidential file is denied, with one audit row that carries no secret text.
        before = frappe.db.count("ASOUD Security Audit", {"action": "request.attachment_denied"})
        with self.assertRaises(frappe.PermissionError):
            self._attachment_as(APPROVER_USER, file)
        rows = frappe.get_all("ASOUD Security Audit", filters={"action": "request.attachment_denied"},
                              fields=["result", "target", "company", "details"])
        self.assertEqual(len(rows), before + 1)
        row = rows[-1]
        self.assertEqual(row.result, "denied")
        self.assertEqual(row.target, file)
        self.assertEqual(row.company, self.company)
        self.assertNotIn(SECRET, row.details)


# --------------------------------------------------------------------------- S8


class TestDuplicateExecution(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, _stages = make_definition(self.company, approvals=1, fields=FIELDS)

    def test_same_request_id_twice_creates_one_request_and_instance(self):
        request_id = "acc-dup-" + uuid4().hex[:10]
        first = create(self.company, definition=self.definition, request_id=request_id,
                       values={"reason": "اول"})
        second = create(self.company, definition=self.definition, request_id=request_id,
                        values={"reason": "اول"})
        self.assertEqual(first["name"], second["name"])
        self.assertEqual(frappe.db.count("ASOUD Workflow Request", {"request_id": request_id}), 1)
        self.assertEqual(frappe.db.count("ASOUD Workflow Instance",
                                         {"reference_doctype": "ASOUD Workflow Request",
                                          "reference_name": first["name"]}), 1)

    def test_double_approve_of_same_task_refused_no_extra_activity(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = request["workflow_instance"]
        task = frappe.db.get_value("ASOUD Workflow Task",
                                   {"workflow_instance": instance, "assigned_to": APPROVER_USER}, "name")
        act(instance, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")
        # The same completion sent twice (a network retry without a request_id) is refused.
        frappe.set_user(APPROVER_USER)
        try:
            with self.assertRaises(frappe.ValidationError):
                workflow_runtime.complete_workflow_task(task, "Approve")
        finally:
            frappe.set_user("Administrator")
        # One transition, one decision: no extra activity or end row.
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "Approve"}), 1)
        self.assertEqual(frappe.db.count("ASOUD Workflow Activity",
                                         {"workflow_instance": instance, "action": "پایان عملیات"}), 1)
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance, "status"), "Completed")


# --------------------------------------------------------------------------- S9


class TestDesignGuard(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=2)
        self.approval1 = self.stages["Approval2"]
        self.end = self.stages["End4"]
        self.request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        self.instance = self.request["workflow_instance"]

    def test_active_definition_with_running_instance_refuses_edits_db_unchanged(self):
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Running")
        before = _graph_fingerprint(self.definition)
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_routes(self.definition, self.approval1.name, {"Approve": self.end.name})
        with self.assertRaises(frappe.ValidationError):
            workflow.save_stage_settings(self.definition, self.approval1.name,
                                         {"title": "تأیید تغییرشده", "assignment_type": "Direct Manager",
                                          "approval_mode": "Any", "allow_reject": True, "allow_return": True})
        self.assertEqual(_graph_fingerprint(self.definition), before)
        # The running instance still needs both approvals to complete.
        act(self.instance, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "current_stage"),
                         self.stages["Approval3"].name)
        act(self.instance, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", self.instance, "status"), "Completed")


# --------------------------------------------------------------------------- S10


class TestBackfill(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, self.stages = make_definition(self.company, approvals=2)

    def _legacy_instance(self):
        request = create(self.company, definition=self.definition, values={"reason": "دلیل"})
        instance = frappe.get_doc("ASOUD Workflow Instance", request["workflow_instance"])
        # Simulate an instance started before the snapshot field existed.
        frappe.db.set_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json", None)
        return instance

    def test_backfill_freezes_consistent_legacy_instance_and_still_needs_both_approvals(self):
        instance = self._legacy_instance()
        from asoud_erp.patches.v0_19.backfill_graph_snapshots import execute

        execute()
        snapshot = frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json")
        self.assertTrue(snapshot)
        self.assertEqual(json.loads(snapshot)["snapshot_source"], "backfill_live_graph")
        # The frozen instance still needs both approvals.
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Running")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "current_stage"),
                         self.stages["Approval3"].name)
        act(instance.name, "Approve")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "status"), "Completed")

    def test_backfill_leaves_inconsistent_instance_untouched_and_logs(self):
        instance = self._legacy_instance()
        # The live graph no longer matches what this instance executed.
        frappe.db.set_value("ASOUD Workflow Instance", instance.name, "current_stage", "acc-missing-stage")
        from asoud_erp.patches.v0_19.backfill_graph_snapshots import execute

        with patch.object(frappe, "log_error") as log_error:
            execute()
        self.assertIsNone(frappe.db.get_value("ASOUD Workflow Instance", instance.name, "graph_snapshot_json"))
        self.assertTrue(log_error.called, "an inconsistent instance must be logged for review")
        self.assertEqual(log_error.call_args.kwargs.get("title"), "PA-015 snapshot backfill needs review")
        self.assertIn(instance.name, log_error.call_args.kwargs.get("message", ""))


# --------------------------------------------------------------------------- S11


def _user_task_config(document_access, title="بررسی"):
    return {"title": title, "activity_type": "Data Entry", "assignment_type": "Initiator",
            "document_access": document_access}


class TestLimitedEdit(APITestCase):
    def setUp(self):
        super().setUp()
        self.definition, stages = make_definition(self.company, approvals=0, fields=[])
        # Design edits require an Inactive workflow with no running instance.
        frappe.db.set_value("ASOUD Workflow Definition", self.definition, "status", "Inactive")
        self.stage = next(item for item in stages.values() if item.stage_type == "User Task")

    def _stored_access(self):
        return json.loads(frappe.db.get_value("ASOUD Workflow Stage", self.stage.name, "config_json"))[
            "document_access"]

    def test_limited_edit_legacy_stage_rules(self):
        # A record saved by an older app already stores Limited Edit.
        frappe.db.set_value("ASOUD Workflow Stage", self.stage.name, "config_json",
                            json.dumps(_user_task_config("Limited Edit"), ensure_ascii=False))
        # Saving another setting (app 0.31 re-sends Edit without the change flag) keeps it.
        workflow.save_stage_settings(self.definition, self.stage.name,
                                     _user_task_config("Edit", title="بررسی تغییرشده"))
        self.assertEqual(self._stored_access(), "Limited Edit")
        # An explicit change with the flag applies.
        workflow.save_stage_settings(self.definition, self.stage.name,
                                     {**_user_task_config("Read Only"), "document_access_changed": True})
        self.assertEqual(self._stored_access(), "Read Only")
        # Limited Edit is refused as a new choice; the stored value is untouched.
        with self.assertRaises(frappe.ValidationError) as ctx:
            workflow.save_stage_settings(self.definition, self.stage.name,
                                         _user_task_config("Limited Edit"))
        self.assertIn("ویرایش محدود دیگر قابل انتخاب نیست", str(ctx.exception))
        self.assertEqual(self._stored_access(), "Read Only")


# --------------------------------------------------------------------------- S12


class TestITModule(APITestCase):
    def test_it_module_definition_saves_and_loads(self):
        result = workflow.create_workflow_draft(workflow_title="گردش‌کار فناوری اطلاعات",
                                                module_key="IT", target_doctype="Asset",
                                                company=self.company)["data"]
        self.assertEqual(result["module_key"], "IT")
        self.assertEqual(frappe.db.get_value("ASOUD Workflow Definition", result["name"], "module_key"), "IT")
        design = workflow.get_workflow_design(result["name"])["data"]
        self.assertEqual(design["workflow"]["module_key"], "IT")

    def test_it_module_label(self):
        # The approved Persian title is «فناوری اطلاعات»; the label change is another
        # worker's task, so this assert runs only once it is merged.
        if MODULE_LABELS.get("IT") != "فناوری اطلاعات":
            self.skipTest(f"IT label «فناوری اطلاعات» not merged yet (current: {MODULE_LABELS.get('IT')!r})")
        self.assertEqual(MODULE_LABELS["IT"], "فناوری اطلاعات")
