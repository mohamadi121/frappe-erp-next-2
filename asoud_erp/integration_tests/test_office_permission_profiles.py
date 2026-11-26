"""Native permission boundaries and explicit-copy templates on an isolated test site."""
from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from asoud_erp.api.v1 import account_security
from asoud_erp.integration_tests import fixtures
from asoud_erp.integration_tests.tenancy import setup_tenancy
from asoud_erp.services import access_catalog_layout, account_recovery
from asoud_erp.services import office_permission_profiles as access
from asoud_erp.services import office_permission_scope as scope


class TestOfficePermissionProfiles(fixtures.APITestCase):
    def setUp(self):
        super().setUp()
        self.second = setup_tenancy()['second']

    def employee(self, company):
        return frappe.get_doc({'doctype': 'Employee', 'first_name': 'Office Access',
            'gender': 'Male', 'date_of_birth': '1990-01-01', 'date_of_joining': '2020-01-01',
            'company': company, 'status': 'Active', 'create_user_permission': 0}).insert(ignore_permissions=True)

    def account(self, company=None):
        employee = self.employee(company or self.company)
        login = 'office.' + frappe.generate_hash(length=12) + '@example.com'
        return employee, access.create_account(employee.company, employee.name, login)

    def profile(self, company=None, grants=None):
        return access.save_profile(company or self.company, 'Profile ' + frappe.generate_hash(length=12),
            grants=grants or {'Journal Entry': ['read', 'create', 'write']})

    def test_shared_catalog_layout_is_not_a_permission_source(self):
        profile = self.profile()
        baseline = access.list_profiles(self.company)['catalog_layout']
        tree = baseline['modules']
        native_id = 'native:Journal Entry'
        self.assertTrue(any(row['id'] == native_id for group in tree for row in group['children']))
        for group in tree:
            group['children'] = [row for row in group['children'] if row['id'] != native_id]
        detail = {'id': 'custom-' + 'c' * 32, 'title': 'جزئیات آزمایشی', 'children': []}
        doc = {'id': 'custom-' + 'b' * 32, 'title': 'سند آزمایشی', 'children': [detail]}
        tree.append({'id': 'custom-' + 'a' * 32, 'title': 'ماژول آزمایشی', 'children': [doc]})
        saved = access_catalog_layout.save(self.company, tree, baseline['version'])
        self.assertEqual(access.list_profiles(self.second)['catalog_layout']['modules'], saved['modules'])
        self.assertEqual(access.get_profile(self.company, profile['name'])['grants'], profile['grants'])
        self.assertIn('Journal Entry', access.normalize({'Journal Entry': ['read']}))
        with self.assertRaises(frappe.ValidationError):
            access.normalize({doc['id']: ['read']})
        with self.assertRaises(frappe.TimestampMismatchError):
            access_catalog_layout.save(self.company, tree, baseline['version'])
        with mock.patch.object(access, 'gate'):
            old_user = frappe.session.user
            try:
                frappe.set_user(fixtures.EMPLOYEE_USER)
                with self.assertRaises(frappe.PermissionError):
                    access_catalog_layout.save(self.company, [], saved['version'])
            finally:
                frappe.set_user(old_user)

    def test_profile_title_unique_per_office_and_legacy_readonly(self):
        profile = self.profile()
        with self.assertRaises(frappe.ValidationError):
            access.save_profile(self.company, profile['title'], grants={})
        other = access.save_profile(self.second, profile['title'], grants={})
        self.assertNotEqual(profile['name'], other['name'])
        with self.assertRaises(frappe.PermissionError):
            access.get_profile(self.second, profile['name'])
        frappe.db.set_value('ASOUD Role Definition', profile['name'], 'company', None)
        legacy = access.get_profile(self.company, profile['name'])
        self.assertTrue(legacy['readonly'])
        with self.assertRaises(frappe.ValidationError):
            access.save_profile(self.company, legacy['title'], grants={}, name=legacy['name'], modified=legacy['modified'])

    def test_delete_only_unlinked_profile_in_own_office(self):
        profile = self.profile()
        with self.assertRaises(frappe.PermissionError):
            access.delete_profile(self.second, profile['name'], profile['modified'])
        with self.assertRaises(frappe.TimestampMismatchError):
            access.delete_profile(self.company, profile['name'], 'stale')
        employee, account = self.account()
        updated = access.save_account_access(
            self.company, employee.name, profile['grants'], account['token'], profile['name'])
        with self.assertRaises(frappe.ValidationError):
            access.delete_profile(self.company, profile['name'], profile['modified'])
        access.save_account_access(self.company, employee.name, updated['grants'], updated['token'])
        access.delete_profile(self.company, profile['name'], profile['modified'])
        self.assertFalse(frappe.db.exists('ASOUD Role Definition', profile['name']))
        self.assertEqual(access.get_account(self.company, employee.name)['grants'], updated['grants'])

    def test_account_uses_registered_contact_when_contact_omitted(self):
        employee = self.employee(self.company)
        login = 'office.' + frappe.generate_hash(length=12) + '@example.com'
        frappe.db.set_value('Employee', employee.name, 'personal_email', login)
        account = access.create_account(self.company, employee.name, method='email')
        self.assertEqual(account['login'], login)
        self.assertTrue(account['registered_delivery'])

    def test_native_default_company_is_not_legacy_profile_ownership(self):
        from asoud_erp.api.v1 import role_management

        frappe.defaults.set_user_default('company', self.company)
        code = 'LEGACY_' + frappe.generate_hash(length=12).upper()
        category = 'ACCESS_PROFILES'
        self.profile()  # ensure the shared classification exists
        role_management.save_role({'code': code, 'title': 'Legacy default',
            'category': category, 'base_roles': ['Employee']})
        self.assertFalse(frappe.db.get_value('ASOUD Role Definition', code, 'company'))
        self.assertTrue(access.get_profile(self.company, code)['readonly'])

    def test_office_template_cannot_be_used_as_a_technical_role(self):
        from asoud_erp.api.v1 import role_management, user_access
        from asoud_erp.services.role_assignment_service import definition_info

        profile = self.profile()
        roles = role_management.catalog()['data']['roles']
        self.assertNotIn(profile['name'], [row['code'] for row in roles])
        with self.assertRaises(frappe.ValidationError):
            definition_info(profile['name'])
        with self.assertRaises(frappe.PermissionError):
            user_access.editor(profile['name'])
        doc = frappe.get_doc('ASOUD Role Definition', profile['name'])
        doc.template_key = None
        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)

    def test_account_no_profile_no_specialist_role_no_new_employee(self):
        count = frappe.db.count('Employee')
        employee, account = self.account()
        self.assertEqual(frappe.db.count('Employee'), count + 1)
        self.assertEqual(frappe.db.get_value('Employee', employee.name, 'user_id'), account['user'])
        self.assertFalse(account['profile'])
        self.assertEqual(account['grants'], {})
        self.assertFalse({'HR Manager', 'Accounts User', 'System Manager'} & set(frappe.get_roles(account['user'])))
        self.assertIn('Employee', frappe.get_roles(account['user']))
        self.assertTrue(frappe.db.get_value('ASOUD Account State', account['user'], 'activation_pending'))

    def test_copy_is_explicit_and_profile_edit_does_not_change_user(self):
        employee, account = self.account()
        profile = self.profile()
        self.assertEqual(access.get_account(self.company, employee.name)['grants'], {})
        def listed_profile():
            return next(row['profile'] for row in access.list_accounts(self.company) if row.name == employee.name)

        self.assertIsNone(listed_profile())
        saved = access.save_account_access(self.company, employee.name, profile['grants'], account['token'], profile['name'])
        self.assertEqual(set(saved['grants']['Journal Entry']), {'read', 'create', 'write'})
        self.assertEqual(listed_profile(), profile['name'])
        access.save_profile(self.company, profile['title'], grants={'Journal Entry': ['read']},
            name=profile['name'], modified=profile['modified'])
        self.assertIn('write', access.get_account(self.company, employee.name)['grants']['Journal Entry'])
        manual = access.save_account_access(self.company, employee.name, {'Journal Entry': ['read']}, saved['token'])
        self.assertFalse(manual['profile'])
        self.assertIsNone(listed_profile())
        self.assertEqual(manual['grants']['Journal Entry'], ['read'])

    def test_foreign_doc_denied_and_own_grant_kept(self):
        employee, account = self.account()
        access.save_account_access(self.company, employee.name, {'Journal Entry': ['read']}, account['token'])
        user = account['user']
        own = frappe.get_doc({'doctype': 'Journal Entry', 'company': self.company})
        foreign = frappe.get_doc({'doctype': 'Journal Entry', 'company': self.second})
        self.assertTrue(scope.has_grant(user, self.company, 'Journal Entry', 'read'))
        self.assertIsNot(scope.permission(own, user, ptype='read'), False)
        self.assertTrue(frappe.has_permission('Journal Entry', 'read', doc=own, user=user))
        self.assertFalse(scope.permission(foreign, user, ptype='read'))
        self.assertFalse(frappe.has_permission('Journal Entry', 'read', doc=foreign, user=user))
        self.assertIn('company', scope.query(user, 'Journal Entry'))
        frappe.set_user(user)
        with self.assertRaises(frappe.PermissionError):
            access.list_profiles(self.company)

    def test_submitted_company_cannot_disguise_a_foreign_document(self):
        employee, account = self.account()
        access.save_account_access(self.company, employee.name,
            {'Journal Entry': ['read', 'write']}, account['token'])
        foreign = frappe.get_doc({'doctype': 'Journal Entry', 'company': self.second})
        foreign.set_new_name()
        foreign.db_insert()  # isolated, unposted draft; no ledger side effects
        foreign.company = self.company
        self.assertFalse(scope.permission(foreign, account['user'], ptype='write'))

    def test_system_manager_is_not_global_office_owner(self):
        from asoud_erp.services.request_access import company_access
        user = fixtures._user('scoped.manager.' + frappe.generate_hash(length=10) + '@example.com', ['System Manager'])
        self.assertFalse(company_access(self.company, user))
        self.assertTrue(company_access(self.company, 'Administrator'))

    def test_independent_accounts_for_same_person_in_two_offices(self):
        person_a, account_a = self.account()
        person_b, account_b = self.account(self.second)
        # Native Employee forbids linking two active files to one login. The same
        # person's independent office files use independent accounts, not a bypass.
        self.assertEqual(person_a.first_name, person_b.first_name)
        access.save_account_access(self.company, person_a.name, {'Journal Entry': ['read']}, account_a['token'])
        access.save_account_access(self.second, person_b.name, {'Journal Entry': ['read', 'create', 'write']}, account_b['token'])
        self.assertFalse(scope.has_grant(account_a['user'], self.company, 'Journal Entry', 'write'))
        self.assertTrue(scope.has_grant(account_b['user'], self.second, 'Journal Entry', 'write'))
        self.assertFalse(scope.has_grant(account_b['user'], self.company, 'Journal Entry', 'read'))

    def test_temporary_invitation_preserves_existing_activation_contract(self):
        employee = self.employee(self.company)
        account = access.create_account(self.company, employee.name, '09123456789', method='mobile')
        activation = access.invite_account(self.company, employee.name)
        self.assertEqual(activation['method'], 'temporary_password')
        self.assertTrue(activation['must_change_on_first_login'])
        self.assertGreaterEqual(len(activation['temporary_password']), 12)
        self.assertTrue(frappe.db.get_value('ASOUD Account State', account['user'], 'activation_pending'))

    def test_manual_invitation_uses_existing_activation_without_delivery(self):
        employee = self.employee(self.company)
        login = 'office.' + frappe.generate_hash(length=12) + '@example.com'
        frappe.db.set_value('Employee', employee.name, 'personal_email', login)
        with mock.patch.object(account_recovery, 'recovery_available', return_value=False), \
                mock.patch('frappe.sendmail') as send:
            account = access.create_account(self.company, employee.name, method='email',
                                            invite=True, delivery='manual_code')
        send.assert_not_called()
        first = account['activation']
        self.assertEqual(first['login'], login)
        self.assertEqual(first['method'], 'manual_code')
        self.assertTrue(account['activation_pending'])
        self.assertEqual(account['grants'], {})
        token = frappe.db.get_value('ASOUD Account Token', {'user': login, 'purpose': 'activation'},
            ['name', 'token_hash', 'company'], as_dict=True)
        self.assertNotEqual(token.token_hash, first['code'])
        self.assertEqual(token.company, self.company)
        self.assertNotIn('activation', access.get_account(self.company, employee.name))
        with self.assertRaises(frappe.PermissionError):
            access.invite_account(self.second, employee.name, delivery='manual_code')
        second = access.invite_account(self.company, employee.name, delivery='manual_code')
        self.assertTrue(frappe.db.get_value('ASOUD Account Token', token.name, 'consumed_on'))
        self.assertNotEqual(first['code'], second['code'])
        password = 'Avocado-Fog-Trade-9463!'
        with self.assertRaises(frappe.ValidationError):
            account_security.activate_account(login, first['code'], password, password)
        result = account_security.activate_account(login, second['code'], password, password)['data']
        self.assertTrue(result['changed'])
        self.assertFalse(access.get_account(self.company, employee.name)['activation_pending'])
        with self.assertRaises(frappe.ValidationError):
            account_security.activate_account(login, second['code'], password, password)
        with self.assertRaises(frappe.ValidationError):
            access.invite_account(self.company, employee.name, delivery='manual_code')

    def test_manual_invitation_rejects_foreign_scope_expiry_and_exhausted_attempts(self):
        employee, account = self.account()
        code = access.invite_account(self.company, employee.name, delivery='manual_code')['code']
        user = account['user']
        filters = {'user': user, 'purpose': 'activation'}
        token = frappe.db.get_value('ASOUD Account Token', filters, 'name')
        frappe.db.set_value('ASOUD Account Token', token, 'company', self.second)
        with self.assertRaises(frappe.ValidationError):
            account_recovery.consume(user, 'activation', code)
        frappe.db.set_value('ASOUD Account Token', token, {
            'company': self.company, 'expires_on': add_to_date(now_datetime(), minutes=-1)})
        with self.assertRaises(frappe.ValidationError):
            account_recovery.consume(user, 'activation', code)
        frappe.db.set_value('ASOUD Account Token', token, 'expires_on', add_to_date(now_datetime(), minutes=15))
        for _ in range(5):
            with self.assertRaises(frappe.ValidationError):
                account_recovery.consume(user, 'activation', 'WRONG-CODE-0')
        with self.assertRaises(frappe.ValidationError):
            account_recovery.consume(user, 'activation', code)

    def test_existing_email_and_sms_delivery_are_unchanged(self):
        employee, account = self.account()
        frappe.db.set_value('Employee', employee.name, 'personal_email', account['login'])
        with mock.patch.object(account_recovery, 'recovery_available', return_value=True), \
                mock.patch('frappe.sendmail') as mail:
            email = access.invite_account(self.company, employee.name, registered=True)
        self.assertEqual(email['method'], 'invite')
        self.assertEqual(mail.call_args.kwargs['recipients'], [account['login']])
        self.assertNotIn('code', email)

        mobile_employee = self.employee(self.company)
        mobile = '09123456789'
        frappe.db.set_value('Employee', mobile_employee.name, 'cell_number', mobile)
        mobile_account = access.create_account(self.company, mobile_employee.name, method='mobile')
        sms_settings = frappe._dict(sms_gateway_url='https://sms.example.invalid', use_post=True,
            receiver_parameter='recipient', message_parameter='message', parameters=[])
        get_single = frappe.get_single
        with mock.patch('frappe.get_single',
                side_effect=lambda doctype: sms_settings if doctype == 'SMS Settings' else get_single(doctype)), \
                mock.patch('frappe.core.doctype.sms_settings.sms_settings.send_request', return_value=200) as sms:
            delivery = access.invite_account(self.company, mobile_employee.name, registered=True)
        self.assertEqual(delivery['method'], 'sms')
        self.assertEqual(sms.call_args.args[1]['recipient'], mobile)
        self.assertNotIn('temporary_password', delivery)
        self.assertTrue(frappe.db.get_value('ASOUD Account State', mobile_account['user'], 'must_change_password'))

    def test_unsupported_actions_and_foreign_profile_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.profile(grants={'Journal Entry': ['submit']})
        employee, account = self.account()
        foreign = self.profile(self.second)
        with self.assertRaises(frappe.PermissionError):
            access.save_account_access(self.company, employee.name, {}, account['token'], foreign['name'])
