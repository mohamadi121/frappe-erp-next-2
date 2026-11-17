"""Integration matrix for the approved confidential-data policy (PA-055).

Two offices (tenancy). A request carrying a confidential value and a confidential file.
The matrix covers the requester, the current assignee, a previous assignee who approved,
a user whose shared-claim task was Cancelled, a reassigned-away holder, an HR Manager of
office A, an HR Manager of office B, and an ordinary user — read through ``get_request``,
``get_attachment``, the raw ``has_permission``/``frappe.get_list`` path, and File download
permission. Concrete values are asserted: the masked text is ``محرمانه`` and the secret is
absent.
"""

import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    APPROVER_USER,
    EMPLOYEE_USER,
    APITestCase,
)
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import act, valid_pdf_bytes
from asoud_erp.integration_tests.tenancy import HR_MANAGER_USER, SECOND_COMPANY, setup_tenancy

SECRET = "درمان بیماری خاص"
MASK = "محرمانه"
FIELDS = [
    {"key": "reason", "label": "دلیل", "type": "Long Text", "max_length": 2000},
    {"key": "proof", "label": "مدرک", "type": "Attachment"},
]


def form_schema(definition):
    return {
        "kind": "Request",
        "title": "درخواست محرمانه",
        "workflow": definition,
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "why", "label": "علت", "type": "LongText", "workflow_key": "reason",
                 "sensitive": True},
                {"key": "doc", "label": "مدرک", "type": "File", "workflow_key": "proof",
                 "sensitive": True},
            ],
        }],
    }


class ConfidentialRequestCase(APITestCase):
    """A confidential request (value + file) in office A, approved by APPROVER_USER."""

    def setUp(self):
        super().setUp()
        self.scope = setup_tenancy()
        self.company = self.scope["first"]
        self.definition, self.stages = make_definition(self.company, approvals=1, fields=FIELDS)
        self.hr_b = self._hr_manager_of(SECOND_COMPANY)

    def _hr_manager_of(self, company):
        email = "pa055-hr-" + uuid4().hex[:10] + "@example.test"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "مدیر منابع انسانی",
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": "HR Manager"}]}).insert(ignore_permissions=True)
        if not frappe.db.exists("User Permission", {"user": email, "allow": "Company",
                                                    "for_value": company, "apply_to_all_doctypes": 1}):
            frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Company",
                            "for_value": company, "apply_to_all_doctypes": 1}).insert(
                                ignore_permissions=True)
        return email

    def submit_confidential(self):
        """Submit the confidential form as EMPLOYEE_USER; returns (request, file_name)."""
        frappe.set_user("Administrator")
        saved = forms.save_form(self.company, form_schema(self.definition),
                                client_id=frappe.generate_hash(length=24))["data"]
        published = forms.transition(saved["name"], "publish", saved["draft_version"])["data"]
        frappe.set_user(EMPLOYEE_USER)
        file = frappe.get_doc({"doctype": "File", "file_name": "madrak.pdf",
                               "content": valid_pdf_bytes(), "is_private": 1}).insert(
            ignore_permissions=True)
        entry = forms.submit_form(saved["name"], published["active_revision"], "درخواست محرمانه",
                                  {"why": SECRET, "doc": file.name},
                                  frappe.generate_hash(length=24))["data"]
        frappe.set_user("Administrator")
        request = entry["reference_name"]
        attached = frappe.get_all("File", filters={"attached_to_doctype": "ASOUD Workflow Request",
                                                   "attached_to_name": request, "is_private": 1},
                                  pluck="name")
        return request, attached[0]

    def detail_as(self, user, name):
        frappe.set_user(user)
        try:
            return workflow_request.get_request(name)["data"]
        finally:
            frappe.set_user("Administrator")

    def raw_read(self, user, name):
        frappe.set_user(user)
        try:
            return frappe.get_doc("ASOUD Workflow Request", name).has_permission("read")
        finally:
            frappe.set_user("Administrator")

    def raw_list(self, user, name):
        frappe.set_user(user)
        try:
            return frappe.get_list("ASOUD Workflow Request", filters={"name": name},
                                   fields=["values_json"])
        finally:
            frappe.set_user("Administrator")

    def file_read(self, user, file_name):
        frappe.set_user(user)
        try:
            return frappe.has_permission("File", "read", frappe.get_doc("File", file_name))
        finally:
            frappe.set_user("Administrator")


class TestRequesterAndAssignee(ConfidentialRequestCase):
    def test_requester_reads_full(self):
        request, file = self.submit_confidential()
        data = self.detail_as(EMPLOYEE_USER, request)
        self.assertEqual(data["values"]["reason"], SECRET)
        self.assertTrue(self.raw_read(EMPLOYEE_USER, request))
        self.assertEqual(len(self.raw_list(EMPLOYEE_USER, request)), 1)
        self.assertTrue(self.file_read(EMPLOYEE_USER, file))

    def test_current_assignee_reads_full(self):
        request, file = self.submit_confidential()
        # The approval task is Open for APPROVER_USER (the requester's direct manager).
        self.assertTrue(frappe.db.exists("ASOUD Workflow Task", {
            "workflow_instance": frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance"),
            "assigned_to": APPROVER_USER, "status": "Open"}))
        data = self.detail_as(APPROVER_USER, request)
        self.assertEqual(data["values"]["reason"], SECRET)
        self.assertTrue(self.raw_read(APPROVER_USER, request))
        self.assertEqual(len(self.raw_list(APPROVER_USER, request)), 1)
        self.assertTrue(self.file_read(APPROVER_USER, file))

    def test_hr_manager_of_the_office_reads_full(self):
        request, file = self.submit_confidential()
        data = self.detail_as(HR_MANAGER_USER, request)
        self.assertEqual(data["values"]["reason"], SECRET)
        self.assertTrue(self.raw_read(HR_MANAGER_USER, request))
        self.assertTrue(self.file_read(HR_MANAGER_USER, file))


class TestPreviousAssigneeMasked(ConfidentialRequestCase):
    def test_previous_assignee_who_approved_is_masked(self):
        request, file = self.submit_confidential()
        instance = frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance")
        act(instance, "Approve")  # APPROVER_USER acts; their task is Completed
        data = self.detail_as(APPROVER_USER, request)
        # The request is readable but the confidential value is masked and the file hidden.
        self.assertEqual(data["values"]["reason"], MASK)
        self.assertNotIn(SECRET, json.dumps(data, ensure_ascii=False, default=str))
        # Raw document read and raw list are denied (FULL only).
        self.assertFalse(self.raw_read(APPROVER_USER, request))
        self.assertEqual(self.raw_list(APPROVER_USER, request), [])
        # The confidential file cannot be downloaded.
        self.assertFalse(self.file_read(APPROVER_USER, file))
        with self.assertRaises(frappe.PermissionError):
            self._attachment_as(APPROVER_USER, file)

    def _attachment_as(self, user, file_name):
        frappe.set_user(user)
        try:
            return workflow_request.get_attachment(file_name)
        finally:
            frappe.set_user("Administrator")


class TestOrdinaryUserDenied(ConfidentialRequestCase):
    def test_ordinary_user_is_denied_everywhere(self):
        request, file = self.submit_confidential()
        with self.assertRaises(frappe.PermissionError):
            self.detail_as(ACCOUNTANT_USER, request)
        self.assertFalse(self.raw_read(ACCOUNTANT_USER, request))
        self.assertEqual(self.raw_list(ACCOUNTANT_USER, request), [])
        self.assertFalse(self.file_read(ACCOUNTANT_USER, file))
        with self.assertRaises(frappe.PermissionError):
            self._attachment_as(ACCOUNTANT_USER, file)

    def _attachment_as(self, user, file_name):
        frappe.set_user(user)
        try:
            return workflow_request.get_attachment(file_name)
        finally:
            frappe.set_user("Administrator")


class TestCrossOffice(ConfidentialRequestCase):
    def test_hr_manager_of_another_office_is_denied(self):
        request, file = self.submit_confidential()
        # HR_MANAGER_USER has company access to office A (the request's office) -> FULL.
        self.assertEqual(self.detail_as(HR_MANAGER_USER, request)["values"]["reason"], SECRET)
        # An HR Manager of office B has no company access to office A -> NONE.
        with self.assertRaises(frappe.PermissionError):
            self.detail_as(self.hr_b, request)
        self.assertFalse(self.raw_read(self.hr_b, request))
        self.assertEqual(self.raw_list(self.hr_b, request), [])
        self.assertFalse(self.file_read(self.hr_b, file))


class TestDeniedReadAudit(ConfidentialRequestCase):
    def test_denied_get_request_writes_one_audit_row_without_the_secret(self):
        request, _file = self.submit_confidential()
        before = frappe.db.count("ASOUD Security Audit", {"action": "request.read_denied"})
        frappe.set_user(ACCOUNTANT_USER)
        try:
            with self.assertRaises(frappe.PermissionError):
                workflow_request.get_request(request)
        finally:
            frappe.set_user("Administrator")
        rows = frappe.get_all("ASOUD Security Audit", filters={"action": "request.read_denied"},
                              fields=["result", "target", "company", "details"])
        self.assertEqual(len(rows), before + 1)
        row = rows[-1]
        self.assertEqual(row.result, "denied")
        self.assertEqual(row.target, request)
        self.assertEqual(row.company, self.company)
        self.assertNotIn(SECRET, row.details)

    def test_denied_attachment_writes_one_audit_row_without_the_secret(self):
        # A MASKED user (a previous assignee who approved) passes _readable_request but is
        # denied the confidential file, so the attachment-specific audit row is written.
        request, file = self.submit_confidential()
        instance = frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance")
        act(instance, "Approve")
        before = frappe.db.count("ASOUD Security Audit", {"action": "request.attachment_denied"})
        frappe.set_user(APPROVER_USER)
        try:
            with self.assertRaises(frappe.PermissionError):
                workflow_request.get_attachment(file)
        finally:
            frappe.set_user("Administrator")
        rows = frappe.get_all("ASOUD Security Audit", filters={"action": "request.attachment_denied"},
                              fields=["result", "target", "details"])
        self.assertEqual(len(rows), before + 1)
        self.assertEqual(rows[-1].result, "denied")
        self.assertEqual(rows[-1].target, file)
        self.assertNotIn(SECRET, rows[-1].details)


class TestCancelledAndReassigned(ConfidentialRequestCase):
    """P4 (Cancelled, never acted -> NONE) and P5 (reassigned away -> MASKED only if acted).

    The shared-claim and reassign user-action stages are not part of the standard request
    definition (their real flows run on generic, non-request instances), so these tests
    construct the exact task/activity rows those flows leave behind on a real request's
    instance, then assert the access level the policy assigns.
    """

    def _company_user(self, prefix):
        """A user with company access to office A (an active Employee), so the denial is
        decided by the participant policy, not the company gate."""
        email = prefix + uuid4().hex[:8] + "@example.test"
        frappe.get_doc({"doctype": "User", "email": email, "first_name": "کارمند",
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": "Employee"}]}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "Employee", "first_name": "کارمند", "gender": "Male",
                        "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
                        "company": self.company, "status": "Active", "user_id": email,
                        "create_user_permission": 0}).insert(ignore_permissions=True)
        return email

    def _instance_of(self, request):
        return frappe.db.get_value("ASOUD Workflow Request", request, "workflow_instance")

    def _task(self, instance, assignee, status, action=None):
        return frappe.get_doc({"doctype": "ASOUD Workflow Task", "workflow_instance": instance,
                               "workflow_stage": frappe.db.get_value(
                                   "ASOUD Workflow Stage",
                                   {"workflow_definition": self.definition, "stage_type": "Approval"},
                                   "name"),
                               "task_title": "آزمون", "assigned_to": assignee, "status": status,
                               "action": action, "assigned_on": "2026-01-01 00:00:00"}
                              ).insert(ignore_permissions=True).name

    def _activity(self, instance, actor, action):
        frappe.get_doc({"doctype": "ASOUD Workflow Activity", "workflow_instance": instance,
                        "actor": actor, "action": action, "comment": "",
                        "created_on": "2026-01-01 00:00:00"}).insert(ignore_permissions=True)

    def test_cancelled_task_without_acting_is_none(self):
        request, file = self.submit_confidential()
        instance = self._instance_of(request)
        bystander = self._company_user("pa055-cancel-")
        # A shared-claim task that was Cancelled (lost the claim) and never acted on.
        self._task(instance, bystander, "Cancelled", "Claimed Elsewhere")
        with self.assertRaises(frappe.PermissionError):
            self.detail_as(bystander, request)
        self.assertFalse(self.raw_read(bystander, request))
        self.assertEqual(self.raw_list(bystander, request), [])
        self.assertFalse(self.file_read(bystander, file))

    def test_reassigned_away_who_acted_is_masked(self):
        request, file = self.submit_confidential()
        instance = self._instance_of(request)
        # APPROVER_USER holds the Open approval task; simulate a reassign that rewrites
        # assigned_to in place and records a Reassigned activity for the previous holder.
        approver_task = frappe.db.get_value("ASOUD Workflow Task",
                                            {"workflow_instance": instance, "assigned_to": APPROVER_USER},
                                            "name")
        self.assertTrue(approver_task)
        frappe.db.set_value("ASOUD Workflow Task", approver_task, "assigned_to", EMPLOYEE_USER)
        self._activity(instance, APPROVER_USER, "Reassigned")
        # The previous holder acted (Reassigned) -> MASKED: readable, but masked and no file.
        data = self.detail_as(APPROVER_USER, request)
        self.assertEqual(data["values"]["reason"], MASK)
        self.assertNotIn(SECRET, json.dumps(data, ensure_ascii=False, default=str))
        self.assertFalse(self.raw_read(APPROVER_USER, request))
        self.assertEqual(self.raw_list(APPROVER_USER, request), [])
        self.assertFalse(self.file_read(APPROVER_USER, file))

    def test_reassigned_away_who_only_claimed_is_none(self):
        request, file = self.submit_confidential()
        instance = self._instance_of(request)
        holder = self._company_user("pa055-reassign-")
        # A task that was reassigned away; the previous holder only Claimed it (not a decision).
        self._task(instance, holder, "Cancelled", "Claimed Elsewhere")
        self._activity(instance, holder, "Claim")
        with self.assertRaises(frappe.PermissionError):
            self.detail_as(holder, request)
        self.assertFalse(self.raw_read(holder, request))
        self.assertEqual(self.raw_list(holder, request), [])

    def _task_as(self, user, task):
        frappe.set_user(user)
        try:
            return workflow_runtime.get_workflow_task(task)
        finally:
            frappe.set_user("Administrator")

    def test_completed_previous_assignee_task_is_masked(self):
        # Defect 1: a previous assignee whose task is Completed must not read unmasked
        # request values through get_workflow_task (their task's assigned_to is still them).
        request, _file = self.submit_confidential()
        instance = self._instance_of(request)
        approver_task = frappe.db.get_value("ASOUD Workflow Task",
                                            {"workflow_instance": instance, "assigned_to": APPROVER_USER},
                                            "name")
        self.assertTrue(approver_task)
        act(instance, "Approve")  # APPROVER_USER acts; their task is Completed
        result = self._task_as(APPROVER_USER, approver_task)
        self.assertTrue(result["ok"])
        blob = json.dumps(result["data"], ensure_ascii=False, default=str)
        self.assertNotIn(SECRET, blob)
        # The request values are masked; the confidential file url is removed.
        self.assertEqual(result["data"]["request_values"].get("reason"), MASK)
        self.assertNotIn(SECRET, json.dumps(result["data"]["previous_data"], ensure_ascii=False, default=str))

    def test_cancelled_task_holder_cannot_read_task_and_is_audited(self):
        # Defect 1: a user whose shared-claim task was Cancelled (never acted) is NONE and
        # must be denied get_workflow_task, with one task.read_denied audit row.
        request, _file = self.submit_confidential()
        instance = self._instance_of(request)
        bystander = self._company_user("pa055-task-")
        task = self._task(instance, bystander, "Cancelled", "Claimed Elsewhere")
        before = frappe.db.count("ASOUD Security Audit", {"action": "task.read_denied"})
        with self.assertRaises(frappe.PermissionError):
            self._task_as(bystander, task)
        rows = frappe.get_all("ASOUD Security Audit", filters={"action": "task.read_denied"},
                              fields=["result", "target", "company", "details"])
        self.assertEqual(len(rows), before + 1)
        self.assertEqual(rows[-1].result, "denied")
        self.assertEqual(rows[-1].target, task)
        self.assertEqual(rows[-1].company, self.company)
        self.assertNotIn(SECRET, rows[-1].details)
