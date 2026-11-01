"""Real disposable records; deletion is transaction-local, never runs/commits a worker."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from asoud_erp.api.v1 import setup_reset
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase
from asoud_erp.services import security_audit
from asoud_erp.services import setup_reset as service


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
            target_type='Setup Reset', target=job, occurred_on=now_datetime(),
            details={'company_groups': [['دفتر آزمون']]})
        frappe.get_doc(row).insert(ignore_permissions=True)
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 0}):
            result = setup_reset.status(job)['data']
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(result['actor'], 'Administrator')
            self.assertEqual(result['companies'], ['دفتر آزمون'])
            with self.assertRaises(frappe.ValidationError):
                setup_reset.status(uuid4().hex)

    def test_cache_alone_cannot_claim_committed_deletion(self):
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        service._save_receipt(job, 'Administrator', 'completed')
        with self.assertRaises(frappe.ValidationError):
            setup_reset.status(job)

    def test_worker_receipt_preserves_verified_digest(self):
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        service._save_receipt(job, 'Administrator', 'queued', digest='verified-plan')
        service._save_receipt(job, 'Administrator', 'running')
        self.assertEqual(service._receipt(job)['digest'], 'verified-plan')

    def reset_fixture(self):
        from frappe.utils.password import update_password

        from asoud_erp.api.v1.role_management import create_category, save_role
        from asoud_erp.api.v1.setup import save_office

        suffix = uuid4().hex[:10]
        actor = f'reset-{suffix}@example.com'
        frappe.get_doc({'doctype': 'User', 'email': actor, 'username': f'reset{suffix}',
            'first_name': 'مدیر آزمایش', 'send_welcome_email': 0, 'user_type': 'System User',
            'roles': [{'role': 'System Manager'}]}).insert(ignore_permissions=True)
        update_password(actor, uuid4().hex)
        frappe.set_user(actor)
        office = save_office('Personal', f'دفتر بازنشانی {suffix}')['data']['company']
        chart = frappe.get_doc({'doctype': 'ASOUD Organization Chart', 'company': office,
            'structure_json': '[]'}).insert()
        employee = frappe.get_doc({'doctype': 'Employee', 'first_name': 'پرسنل آزمون',
            'company': office, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'create_user_permission': 0}).insert(ignore_permissions=True)
        department = frappe.get_doc({'doctype': 'Department', 'department_name': f'واحد {suffix}',
            'company': office, 'is_group': 0}).insert()
        category = create_category({'code': f'RESET-{suffix}'.upper(), 'title': 'آزمون', 'style': 'system'})['data']['code']
        role = save_role({'code': f'RESET-ROLE-{suffix}'.upper(), 'title': 'نقش آزمون',
            'category': category, 'scope': 'office', 'base_roles': ['Employee'], 'enabled': 1})['data']
        return actor, office, chart.name, employee.name, department.name, role['code'], role['profile']

    def test_confirmed_reset_removes_seeded_workflows_and_owned_setup_atomically(self):
        actor, office, chart, employee, department, role, profile = self.reset_fixture()
        workflows = frappe.get_all('ASOUD Workflow Definition', filters={'company': office}, pluck='name')
        self.assertTrue(workflows, 'Real office creation must seed the system workflow blocker')
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc('ASOUD Workflow Definition', workflows[0])
        frappe.clear_messages()
        identity = frappe.db.get_value('User', actor, ['name', 'username', 'email'], as_dict=True)
        password_hash = frappe.db.sql('select password from __Auth where doctype=%s and name=%s and fieldname=%s',
            ('User', actor, 'password'))
        self.assertTrue(password_hash)
        before_scope = getattr(frappe.flags, 'asoud_setup_reset_scope', None)
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}), patch.dict(frappe.flags,
                {'asoud_setup_reset_worker': True, 'asoud_setup_reset_job': job}):
            _, blockers, digest = service._collect(actor)
            self.assertEqual(blockers, [])
            service._save_receipt(job, actor, 'running', digest=digest)
            service._execute(actor, digest)  # No commit: APITestCase rolls back all disposable records.
            self.assertEqual(frappe.flags.asoud_setup_reset_scope, before_scope)
            result = setup_reset.status(job)['data']
        self.assertEqual(result['companies'], [office])
        self.assertEqual(result['actor'], actor)
        for doctype, name in [('Company', office), ('ASOUD Organization Chart', chart),
                ('Employee', employee), ('Department', department), ('ASOUD Role Definition', role),
                ('Role Profile', profile), *[('ASOUD Workflow Definition', name) for name in workflows]]:
            self.assertFalse(frappe.db.exists(doctype, name))
        self.assertTrue(frappe.db.exists('Company', self.company))
        self.assertEqual(frappe.db.get_value('User', actor, ['name', 'username', 'email'], as_dict=True), identity)
        self.assertIn('System Manager', frappe.get_roles(actor))
        self.assertEqual(frappe.db.sql('select password from __Auth where doctype=%s and name=%s and fieldname=%s',
            ('User', actor, 'password')), password_hash)
        self.assertIsNone(frappe.db.get_value('ASOUD Account State', actor, 'admin_profile_completed_on'))

    def test_native_outside_link_rolls_back_already_deleted_chart_and_workflow(self):
        actor, office, chart, employee, _, role, _ = self.reset_fixture()
        # A real outside employee can report to this employee; it must not be
        # edited/deleted just to permit the reset of the owned company.
        frappe.get_doc({'doctype': 'Employee', 'first_name': 'وابستگی خارجی',
            'company': self.company, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'reports_to': employee,
            'create_user_permission': 0}).insert(ignore_permissions=True)
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}), patch.dict(frappe.flags,
                {'asoud_setup_reset_worker': True, 'asoud_setup_reset_job': job}):
            _, blockers, digest = service._collect(actor)
            self.assertEqual(blockers, [])  # The native linked-record guard is exercised below.
            service._save_receipt(job, actor, 'running', digest=digest)
            with self.assertRaises(frappe.ValidationError):
                service._execute(actor, digest)
            self.assertFalse(service._committed(job, actor))
            self.assertIsNone(frappe.flags.asoud_setup_reset_scope)
        for doctype, name in [('Company', office), ('ASOUD Organization Chart', chart),
                ('Employee', employee), ('ASOUD Role Definition', role)]:
            self.assertTrue(frappe.db.exists(doctype, name))
        self.assertTrue(frappe.db.exists('ASOUD Workflow Definition', {'company': office}))

    def test_execution_history_blocks_reset_before_any_owned_data_is_removed(self):
        actor, office, chart, employee, _, role, _ = self.reset_fixture()
        name = frappe.db.get_value('ASOUD Workflow Definition', {'company': office}, 'name')
        instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance', 'workflow_definition': name,
            'subject': 'سابقه محفوظ', 'status': 'Completed'}).insert()
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}), patch.dict(frappe.flags,
                {'asoud_setup_reset_worker': True, 'asoud_setup_reset_job': job}):
            _, blockers, digest = service._collect(actor)
            self.assertTrue(blockers)
            service._save_receipt(job, actor, 'running', digest=digest)
            with self.assertRaises(frappe.ValidationError):
                service._execute(actor, digest)
        for doctype, value in [('Company', office), ('ASOUD Organization Chart', chart),
                ('Employee', employee), ('ASOUD Role Definition', role), ('ASOUD Workflow Instance', instance.name)]:
            self.assertTrue(frappe.db.exists(doctype, value))

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
