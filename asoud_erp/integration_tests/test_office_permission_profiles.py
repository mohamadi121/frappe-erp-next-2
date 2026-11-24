"""Native permission boundaries and explicit-copy templates on an isolated test site."""
import frappe

from asoud_erp.integration_tests import fixtures
from asoud_erp.integration_tests.tenancy import setup_tenancy
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
        saved = access.save_account_access(self.company, employee.name, profile['grants'], account['token'], profile['name'])
        self.assertEqual(set(saved['grants']['Journal Entry']), {'read', 'create', 'write'})
        access.save_profile(self.company, profile['title'], grants={'Journal Entry': ['read']},
            name=profile['name'], modified=profile['modified'])
        self.assertIn('write', access.get_account(self.company, employee.name)['grants']['Journal Entry'])
        manual = access.save_account_access(self.company, employee.name, {'Journal Entry': ['read']}, saved['token'])
        self.assertFalse(manual['profile'])
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

    def test_unsupported_actions_and_foreign_profile_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.profile(grants={'Journal Entry': ['submit']})
        employee, account = self.account()
        foreign = self.profile(self.second)
        with self.assertRaises(frappe.PermissionError):
            access.save_account_access(self.company, employee.name, {}, account['token'], foreign['name'])
