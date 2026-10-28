"""One role matrix over real document APIs and the existing approval runtime.

Reads production policy; all writes are isolated test records and rolled back.
"""

import json
from uuid import uuid4

import frappe
from frappe.utils import nowdate

from asoud_erp.api.v1 import employment_certificates as certificates
from asoud_erp.api.v1 import employment_contracts as contracts
from asoud_erp.api.v1 import hiring_orders as hiring
from asoud_erp.api.v1 import personnel_introduction_letters as letters
from asoud_erp.api.v1 import salary_change_orders as salary
from asoud_erp.api.v1.workflow_runtime import complete_workflow_task
from asoud_erp.integration_tests.fixtures import APITestCase, _employee, _user, company
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import SECOND_COMPANY, setup_tenancy
from asoud_erp.services.employment_contract import DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS
from asoud_erp.services.hiring_orders import default_template as hiring_template
from asoud_erp.services.salary_change_orders import default_template as salary_template


class TestHRDocumentsLifecycle(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def _actors(self):
        actors = {}
        token = uuid4().hex[:10]
        if not frappe.db.exists("Role", "Payroll Manager"):
            frappe.get_doc({"doctype": "Role", "role_name": "Payroll Manager", "desk_access": 1}).insert()
        for label, roles in (
            ("operational", ["HR User"]), ("designer", ["HR Manager"]),
            ("payroll", ["Payroll Manager"]), ("employee", ["Employee"]),
            ("foreign", ["HR Manager"]),
        ):
            user = _user(f"matrix-{label}-{token}@example.com", roles)
            target = SECOND_COMPANY if label == "foreign" else company()
            # Designer deliberately has no Employee; native Company permission is
            # the account-only HR manager's scope.
            if label != "designer":
                if label == "foreign":
                    frappe.get_doc({"doctype": "Employee", "first_name": "آزمون",
                        "gender": "Male", "date_of_birth": "1990-01-01",
                        "date_of_joining": "2020-01-01", "company": target,
                        "status": "Active", "user_id": user,
                        "create_user_permission": 0}).insert(ignore_permissions=True)
                else:
                    _employee(user, "آزمون")
            frappe.get_doc({"doctype": "User Permission", "user": user,
                "allow": "Company", "for_value": target,
                "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
            actors[label] = user
        return actors

    def _templates(self, workflow):
        comp = company()
        contracts.save_contract_template(comp, DEFAULT_CLAUSES, DEFAULT_SALARY_ROWS, workflow=workflow)
        contracts.publish_contract_template(comp)
        for api, make, save, publish in (
            (hiring, hiring_template, "save_hiring_order_template", "publish_hiring_order_template"),
            (salary, salary_template, "save_salary_change_order_template", "publish_salary_change_order_template"),
        ):
            template = make()
            template["workflow"] = workflow
            saved = getattr(api, save)(comp, template=template)["data"]
            getattr(api, publish)(comp, revision=saved["revision"])
        for api in (certificates, letters):
            template = api.get_template(comp)["data"]
            saved = api.save_template_draft(comp, revision=template["revision"],
                clauses=template["clauses"], workflow=workflow)["data"]
            api.publish_template(comp, revision=saved["revision"])

    def _save(self, kind, employee, previous=None):
        data = dict(company=company(), employee=employee)
        if previous:
            data["revision"] = previous["revision"]
        if kind == "contract":
            return contracts.save_contract_draft(**data, start_date=nowdate(),
                client_id=uuid4().hex, contract_id=previous["contract_id"] if previous else None)["data"]
        if kind in {"hiring", "salary"}:
            endpoint = hiring.save_hiring_order if kind == "hiring" else salary.save_salary_change_order
            return endpoint(**data, effective_date=nowdate(), request_id=uuid4().hex,
                            order=previous["name"] if previous else None)["data"]
        api = certificates if kind == "certificate" else letters
        extra = {"addressee_name": "بانک"} if kind == "certificate" else {"bank_name": "بانک", "purpose": "افتتاح حساب"}
        return api.save_draft(**data, **extra, request_key=uuid4().hex,
                              name=previous["name"] if previous else "")["data"]

    def _send(self, kind, draft, key):
        if kind == "contract":
            return contracts.finalize_contract(draft["contract_id"], revision=draft["revision"], request_id=key)["data"]
        endpoint = {"hiring": hiring.send_hiring_order_for_review,
                    "salary": salary.send_salary_change_order_for_review,
                    "certificate": certificates.finalize_certificate, "letter": letters.finalize_letter}[kind]
        return endpoint(draft["name"], draft["revision"], key)["data"]

    def _read(self, kind, draft, print_only=False):
        if kind == "contract":
            endpoint = contracts.get_contract_print if print_only else contracts.get_contract
            return endpoint(draft["contract_id"])["data"]
        endpoints = {
            "hiring": (hiring.get_hiring_order, hiring.print_hiring_order),
            "salary": (salary.get_salary_change_order, salary.print_salary_change_order),
            "certificate": (certificates.get_certificate, certificates.get_certificate),
            "letter": (letters.get_letter, letters.print_letter),
        }
        return endpoints[kind][int(print_only)](draft["name"])["data"]

    def _denied(self, action):
        with self.assertRaises(frappe.PermissionError) as raised:
            action()
        message = str(raised.exception)
        self.assertRegex(message, r"[آ-ی]")
        self.assertNotRegex(message, r"[A-Za-z]|Traceback|\{.*\}")

    def test_five_documents_role_scope_approval_number_print_and_replay_matrix(self):
        actors = self._actors()
        employee = frappe.db.get_value("Employee", {"company": company(), "status": "Active"}, "name")
        definition, stages = make_definition(company(), fields=[])
        for stage in stages.values():
            if stage.stage_type == "Approval":
                config = json.loads(stage.config_json)
                config.update(assignment_type="Role", approver_roles=["System Manager"])
                frappe.db.set_value("ASOUD Workflow Stage", stage.name, "config_json", json.dumps(config))
        self._templates(definition)
        prefixes = {"contract": "CNT", "hiring": "HIRE", "salary": "SAL", "certificate": "CERT", "letter": "INTRO"}
        for kind in prefixes:
            for label, user in actors.items():
                with self.subTest(document=kind, role=label):
                    writable = label == "designer" or (label == "operational" and kind != "salary")
                    readable = writable or (label == "payroll" and kind == "salary")
                    frappe.set_user(user)
                    if not writable:
                        self._denied(lambda: self._save(kind, employee))
                        frappe.set_user(actors["designer"])
                    draft = self._save(kind, employee)
                    self.assertIn(draft["status"], {"draft", "Draft", "پیش‌نویس"})
                    if not writable:
                        frappe.set_user(user)
                        self._denied(lambda: self._save(kind, employee, draft))
                        self._denied(lambda: self._send(kind, draft, uuid4().hex))
                        frappe.set_user(actors["designer"])
                    draft = self._save(kind, employee, draft)
                    send_key = uuid4().hex
                    pending = self._send(kind, draft, send_key)
                    self.assertIn(pending["status"], {"pending", "Pending", "در جریان"})
                    instance_name = pending["workflow_instance"]
                    task = frappe.db.get_value("ASOUD Workflow Task", {
                        "workflow_instance": instance_name, "status": "Open"},
                        ["name", "assigned_to"], as_dict=True)
                    self.assertTrue(task)
                    frappe.set_user(user)
                    self._denied(lambda: complete_workflow_task(task.name, "Approve", comment="بررسی شد"))
                    if readable:
                        self._read(kind, draft)
                    else:
                        self._denied(lambda: self._read(kind, draft))
                    frappe.set_user(task.assigned_to)
                    complete_workflow_task(task.name, "Approve", comment="بررسی شد")
                    frappe.set_user("Administrator")
                    final = self._read(kind, draft)
                    number = final.get("contract_number") or final["number"]
                    self.assertRegex(number, rf"^{prefixes[kind]}-\d{{4}}-\d+$")
                    printed = self._read(kind, draft, True)
                    self.assertFalse(printed["letterhead_missing"])
                    before = json.dumps(printed, sort_keys=True)
                    # A second runtime decision is rejected; the document replay
                    # and repeated completion event must preserve the same number.
                    frappe.set_user(task.assigned_to)
                    with self.assertRaises(frappe.ValidationError):
                        complete_workflow_task(task.name, "Approve", comment="تکرار")
                    frappe.set_user("Administrator")
                    frappe.get_doc("ASOUD Workflow Instance", instance_name).save()
                    replay = self._send(kind, draft, send_key)
                    self.assertEqual(replay.get("contract_number") or replay["number"], number)
                    self.assertEqual(json.dumps(self._read(kind, draft, True), sort_keys=True), before)
                    frappe.set_user(user)
                    if readable:
                        self._read(kind, draft, True)
                    else:
                        self._denied(lambda: self._read(kind, draft, True))
                    frappe.set_user("Administrator")
