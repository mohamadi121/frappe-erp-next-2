import secrets
from unittest.mock import patch

import frappe
from werkzeug.wrappers import Request

from asoud_erp.api.v1 import auth, session, sync
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create, open_task, status_key
from asoud_erp.services import personnel_representation as representation


class TestPersonnelRepresentation(APITestCase):
    def setUp(self):
        super().setUp()
        self.flags = patch.dict(frappe.conf, {"asoud_enable_personnel_representation": 1})
        self.flags.start()
        self.addCleanup(self.flags.stop)
        self.sid = secrets.token_hex(20)
        frappe.db.sql(
            "insert into tabSessions (sid, user, status, lastupdate, sessiondata) values (%s,%s,%s,%s,%s)",
            (self.sid, "Administrator", "Active", frappe.utils.now_datetime(), "{}"),
        )
        self.employee = frappe.db.get_value("Employee", {"user_id": APPROVER_USER}, "name")
        self.addCleanup(self._clear_request)

    def _clear_request(self):
        frappe.local.asoud_personnel_representation = None
        frappe.local.request = None
        frappe.local.form_dict = frappe._dict()

    def _request(self, method, token=None, **parameters):
        path = "/api/method/" + method
        header = {"Authorization": f"Asoud-Delegated {token}"} if token else {}
        frappe.local.request = Request.from_values(path, method="POST", base_url="https://localhost", headers=header)
        frappe.local.form_dict = frappe._dict(parameters)
        if token:
            frappe.set_user("Guest")
        else:
            frappe.session.sid = self.sid
        # set_user resets form_dict, just as Frappe's native auth hooks do.
        frappe.local.form_dict = frappe._dict(parameters)
        frappe.local.asoud_personnel_representation = None

    def _start(self):
        self._request("asoud_erp.api.v1.session.start_personnel_representation")
        data = session.start_personnel_representation(self.company, self.employee, "آزمون نمایندگی کارتابل")["data"]
        token = data["credential"]
        self.addCleanup(frappe.cache.delete_value, representation._key(token))
        return token

    def test_real_approval_audited_and_child_logout_keeps_parent(self):
        definition, _ = make_definition(self.company, approvals=1)
        record = create(self.company, definition=definition, values={"reason": "آزمون"})
        task = open_task(record["workflow_instance"], APPROVER_USER)
        frappe.set_user("Administrator")
        self.assertTrue(representation._active_parent(self.sid))
        token = self._start()
        self._request("asoud_erp.api.v1.sync.execute_mutation", token)
        representation.authenticate()
        representation.audit_request()
        self.assertEqual(auth.current_user()["data"]["user_id"], APPROVER_USER)
        sync.execute_mutation(secrets.token_hex(16),
                              "asoud_erp.api.v1.workflow_runtime.complete_workflow_task",
                              {"task": task.name, "action": "Approve"})
        self.assertEqual(status_key(record["name"]), "approved")
        self.assertTrue(frappe.db.exists("ASOUD Security Audit", {
            "action": "auth.personnel_representation_request", "actor": "Administrator", "target": APPROVER_USER,
        }))
        self._request("asoud_erp.api.v1.session.logout", token)
        representation.authenticate()
        self.assertTrue(session.logout()["data"]["revoked"])
        self.assertTrue(representation._active_parent(self.sid))
        self._request("asoud_erp.api.v1.auth.current_user", token)
        with self.assertRaises(frappe.AuthenticationError):
            representation.authenticate()

    def test_requires_real_admin_and_rejects_sensitive_routes_and_revoked_parent(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            self._start()
        frappe.set_user("Administrator")
        token = self._start()
        self._request("asoud_erp.api.v1.account_security.change_password", token)
        with self.assertRaises(frappe.PermissionError):
            representation.authenticate()
        self._request("asoud_erp.api.v1.sync.execute_mutation", token)
        representation.authenticate()
        with self.assertRaises(frappe.PermissionError):
            sync.execute_mutation("forbidden", "asoud_erp.api.v1.access_profiles.save_account_access")
        self._request("asoud_erp.api.v1.auth.current_user", token, cmd="frappe.desk.form.save.savedocs")
        with self.assertRaises(frappe.PermissionError):
            representation.authenticate()
        frappe.db.sql("delete from tabSessions where sid=%s", self.sid)
        self._request("asoud_erp.api.v1.auth.current_user", token)
        with self.assertRaises(frappe.AuthenticationError):
            representation.authenticate()
