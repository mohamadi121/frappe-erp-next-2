"""Authorization and durable receipt checks; never runs a destructive worker."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from asoud_erp.api.v1 import setup_reset
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.services import security_audit


class TestSetupReset(APITestCase):
    def test_disabled_server_rejects_admin_without_changing_offices(self):
        before = frappe.db.count('Company')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 0}):
            with self.assertRaises(frappe.ValidationError):
                setup_reset.preview()
        self.assertEqual(frappe.db.count('Company'), before)

    def test_employee_cannot_preview_perform_or_read_another_receipt(self):
        frappe.set_user(EMPLOYEE_USER)
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}):
            for call in (lambda: setup_reset.preview(), lambda: setup_reset.status('a' * 40),
                    lambda: setup_reset.perform('a' * 40, 'not-a-real-password', 'شروع دوباره', 1)):
                with self.assertRaises(frappe.PermissionError):
                    call()

    def test_durable_commit_receipt_survives_disabled_flag_and_missing_redis_receipt(self):
        job = uuid4().hex
        row = security_audit.build_row(actor='Administrator', action='onboarding.reset.completed',
            target_type='Setup Reset', target=job, occurred_on=now_datetime())
        frappe.get_doc(row).insert(ignore_permissions=True)
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 0}):
            self.assertEqual(setup_reset.status(job)['data']['state'], 'completed')
            with self.assertRaises(frappe.ValidationError):
                setup_reset.status(uuid4().hex)

    def test_preview_is_read_only_and_contains_explicit_scope(self):
        before = frappe.db.count('Company')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}):
            data = setup_reset.preview()['data']
        self.addCleanup(frappe.cache.delete_value, f"asoud_setup_reset:{data['token']}")
        self.assertIn('companies', data)
        self.assertIn('counts', data)
        self.assertIn('blockers', data)
        self.assertIn('preserved', data)
        self.assertEqual(frappe.db.count('Company'), before)
