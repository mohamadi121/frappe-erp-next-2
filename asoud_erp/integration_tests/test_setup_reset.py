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
            'company': office, 'is_group': 0}).insert(ignore_permissions=True)
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
        self.assertIn('blocking_roles', data)
        self.assertIn('blocking_users', data)
        self.assertIn('preserved', data)
        self.assertEqual(frappe.db.count('Company'), before)

    def test_reset_succeeds_with_fiscal_year_in_scope(self):
        actor, office, chart, employee, department, role, profile = self.reset_fixture()
        fy_name = f'FY {uuid4().hex[:8]}'
        fy = frappe.get_doc({
            'doctype': 'Fiscal Year',
            'year': fy_name,
            'year_start_date': '2045-01-01',
            'year_end_date': '2045-12-31',
            'companies': [{'company': office}],
        }).insert(ignore_permissions=True)
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}), patch.dict(frappe.flags,
                {'asoud_setup_reset_worker': True, 'asoud_setup_reset_job': job}):
            groups, blockers, digest = service._collect(actor)
            self.assertEqual(blockers, [])
            self.assertIn(fy.name, [r['name'] for r in groups.get('Fiscal Year', [])])
            service._save_receipt(job, actor, 'running', digest=digest)
            service._execute(actor, digest)
            self.assertFalse(frappe.db.exists('Fiscal Year', fy.name))

    def test_reset_succeeds_after_onboarding_with_floating_detail(self):
        from frappe.utils.password import update_password

        from asoud_erp.api.v1.setup import save_office

        suffix = uuid4().hex[:10]
        actor = f'onboard-reset-{suffix}@example.com'
        frappe.get_doc({'doctype': 'User', 'email': actor, 'username': f'onb{suffix}',
            'first_name': 'مدیر آزمایش', 'send_welcome_email': 0, 'user_type': 'System User',
            'roles': [{'role': 'System Manager'}]}).insert(ignore_permissions=True)
        update_password(actor, uuid4().hex)
        frappe.set_user(actor)
        office = save_office('Personal', f'دفتر تست آنبوردینگ {suffix}')['data']['company']
        party = frappe.get_doc({
            'doctype': 'ASOUD Party Profile',
            'display_name': 'مدیر شخص آزمون',
            'party_type': 'Individual',
            'user': actor,
            'company': office,
            'roles_text': '["Employee"]',
        }).insert(ignore_permissions=True)
        group = frappe.get_doc({'doctype': 'ASOUD Detail Group', 'group_code': f'RESET-{suffix}',
            'group_name': 'پرسنل آزمون', 'party_role': 'Employee'}).insert(ignore_permissions=True)
        fd = frappe.get_doc({
            'doctype': 'ASOUD Floating Detail',
            'detail_code': f'FD-{suffix}',
            'title': 'مدیر شخص آزمون',
            'detail_type': 'Employee',
            'detail_group': group.name,
            'linked_doctype': 'ASOUD Party Profile',
            'linked_document': party.name,
        }).insert(ignore_permissions=True)
        job = uuid4().hex
        self.addCleanup(frappe.cache.delete_value, f'asoud_setup_reset_job:{job}')
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}), patch.dict(frappe.flags,
                {'asoud_setup_reset_worker': True, 'asoud_setup_reset_job': job}):
            preview_data = setup_reset.preview()['data']
            self.addCleanup(frappe.cache.delete_value, f"asoud_setup_reset:{preview_data['token']}")
            self.assertIn('ASOUD Floating Detail', preview_data['counts'])
            groups, blockers, digest = service._collect(actor)
            self.assertEqual(blockers, [], service._collect(actor, include_access_blockers=True)[3])
            service._save_receipt(job, actor, 'running', digest=digest)
            service._execute(actor, digest)
            self.assertFalse(frappe.db.exists('ASOUD Party Profile', party.name))
            self.assertFalse(frappe.db.exists('ASOUD Floating Detail', fd.name))

    # Named test_zz_* so unittest (alphabetical) runs it last: it leaves its office behind (a ledger
    # row blocks the reset), and _collect() looks at every office, so earlier tests that execute a
    # real reset would otherwise see this office's role profile holders as outside blockers.
    def test_zz_ledger_prefilter_excludes_only_referenced_floating_details(self):
        actor, office, *_ = self.reset_fixture()
        suffix = uuid4().hex[:10]
        party = frappe.get_doc({'doctype': 'ASOUD Party Profile', 'display_name': 'شخص آزمون دفتر',
            'party_type': 'Individual', 'company': office, 'user': actor,
            'roles_text': '["Employee"]'}).insert(ignore_permissions=True)
        group = frappe.get_doc({'doctype': 'ASOUD Detail Group', 'group_code': f'LEDGER-{suffix}',
            'group_name': 'گروه آزمون دفتر'}).insert(ignore_permissions=True)
        details = [frappe.get_doc({'doctype': 'ASOUD Floating Detail', 'detail_code': f'{suffix}-{index}',
            'title': 'تفصیلی آزمون', 'detail_type': 'Other', 'detail_group': group.name,
            'linked_doctype': party.doctype, 'linked_document': party.name}).insert(ignore_permissions=True)
            for index in range(2)]
        # Transaction-local legacy ledger shapes exercise the real query without
        # posting or modifying a native ledger controller. A different party type
        # with the same identifier must not mark the unused detail as referenced.
        for detail, party_type in zip(details, ('ASOUD Floating Detail', 'Customer')):
            entry = frappe.get_doc({'doctype': 'GL Entry', 'company': office,
                'party_type': party_type, 'party': detail.name})
            entry.name = uuid4().hex
            entry.db_insert()
        groups, blockers, _ = service._collect(actor)
        selected = {row['name'] for row in groups['ASOUD Floating Detail']}
        self.assertNotIn(details[0].name, selected)
        self.assertIn(details[1].name, selected)
        self.assertTrue(any('تفصیلی' in message for message in blockers))
        self.assertTrue(all(frappe.db.exists(detail.doctype, detail.name) for detail in details))

    def test_preview_returns_blocking_users_and_roles_for_access_assignments(self):
        actor, office, chart, employee, department, role, profile = self.reset_fixture()
        outside_user = f'outside-{uuid4().hex[:8]}@example.com'
        frappe.get_doc({'doctype': 'User', 'email': outside_user, 'username': f'out{uuid4().hex[:6]}',
            'first_name': 'کاربر خارج', 'send_welcome_email': 0, 'user_type': 'System User'}).insert(ignore_permissions=True)
        from asoud_erp.api.v1.user_access import _native

        native_role = _native(role, outside_user)
        frappe.get_doc({'doctype': 'Role', 'role_name': native_role, 'desk_access': 1}).insert(ignore_permissions=True)
        frappe.get_doc({
            'doctype': 'ASOUD Access Assignment',
            'managed_role': role,
            'user': outside_user,
            'native_role': native_role,
        }).insert(ignore_permissions=True)
        with patch.dict(frappe.conf, {'asoud_allow_setup_reset': 1}):
            data = setup_reset.preview()['data']
        self.assertTrue(data['blockers'])
        self.assertIn('blocking_roles', data)
        self.assertIn('blocking_users', data)
        self.assertIn(outside_user, data['blocking_users'])
        matched = [b for b in data['blocking_roles'] if b.get('user') == outside_user and b.get('role') == role]
        self.assertTrue(matched)
        self.assertEqual(matched[0]['native_role'], native_role)
        self.addCleanup(frappe.cache.delete_value, f"asoud_setup_reset:{data['token']}")
