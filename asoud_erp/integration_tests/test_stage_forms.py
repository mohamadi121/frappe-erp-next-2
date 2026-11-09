"""Workflow-stage forms: a new ASOUD Form kind with five trusted defaults."""

import frappe

from asoud_erp.api.v1 import forms
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import EMPLOYEE_A_USER, HR_MANAGER_USER, setup_tenancy

STAGE_KEYS = {
    'stage_request_checklist', 'stage_expert_opinion', 'stage_hr_review',
    'stage_finance_review', 'stage_operations_review',
}


class TestStageForms(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def test_stage_defaults_are_virtual_until_opened_then_idempotent(self):
        from asoud_erp.services.stage_form_catalog import form_name

        name = form_name(self.company, 'stage_hr_review')
        self.assertFalse(frappe.db.exists('ASOUD Form', name))
        rows = forms.list_forms(company=self.company, kind='Stage', manage=1)['data']
        self.assertEqual({r['builtin_key'] for r in rows if r.get('builtin_pending')}, STAGE_KEYS)
        self.assertFalse(frappe.db.exists('ASOUD Form', name))

        opened = forms.open_builtin(self.company, 'stage_hr_review', manage=1)['data']
        self.assertEqual(opened['name'], name)
        self.assertEqual(opened['schema']['kind'], 'Stage')
        self.assertEqual(opened['schema']['module'], 'HR')
        self.assertEqual(opened['schema']['usage'], 'approval')
        self.assertTrue(opened['active_revision'])
        # A second open returns the same materialized form and revision.
        again = forms.open_builtin(self.company, 'stage_hr_review', manage=1)['data']
        self.assertEqual(opened['name'], again['name'])
        self.assertEqual(opened['active_revision'], again['active_revision'])

    def test_stage_list_shows_materialized_plus_virtual_defaults(self):
        from asoud_erp.services.stage_form_catalog import form_name

        forms.open_builtin(self.company, 'stage_finance_review', manage=1)
        rows = forms.list_forms(company=self.company, kind='Stage', manage=1)['data']
        materialized = [r for r in rows if not r.get('builtin_pending')]
        virtual = [r for r in rows if r.get('builtin_pending')]
        self.assertEqual([r['name'] for r in materialized], [form_name(self.company, 'stage_finance_review')])
        self.assertEqual({r['builtin_key'] for r in virtual}, STAGE_KEYS - {'stage_finance_review'})
        self.assertEqual(len(virtual), 4)
        # A non-manage (consumer) list also carries the stage presentation keys.
        consumer = forms.list_forms(company=self.company, kind='Stage')['data']
        row = next(r for r in consumer if r['name'] == form_name(self.company, 'stage_finance_review'))
        self.assertEqual((row['usage'], row['color'], row['icon']), ('approval', '#C99A2E', 'payments'))
        self.assertEqual(row['description'], 'کنترل هزینه و اعتبار')

    def test_request_and_document_lists_never_include_stage(self):
        from asoud_erp.services.stage_form_catalog import form_name

        forms.open_builtin(self.company, 'stage_operations_review', manage=1)
        stage_name = form_name(self.company, 'stage_operations_review')
        for kind in ('Request', 'Document'):
            rows = forms.list_forms(company=self.company, kind=kind, manage=1)['data']
            self.assertNotIn(stage_name, [r['name'] for r in rows])
            self.assertNotIn('Stage', {r['kind'] for r in rows})

    def test_submit_form_rejects_stage(self):

        opened = forms.open_builtin(self.company, 'stage_request_checklist', manage=1)['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'به‌صورت درخواست مستقل ثبت نمی‌شود'):
            forms.submit_form(name=opened['name'], revision_name=opened['active_revision'],
                              subject='ثبت مرحله', values={}, request_key='s' * 24)

    def test_copy_form_creates_company_stage_form_and_keeps_source(self):

        opened = forms.open_builtin(self.company, 'stage_expert_opinion', manage=1)['data']
        source_name = opened['name']
        source_draft_version = frappe.db.get_value('ASOUD Form', source_name, 'draft_version')
        source_revision = frappe.db.get_value('ASOUD Form', source_name, 'active_revision')
        source_revisions = frappe.get_all('ASOUD Form Revision', filters={'form': source_name}, pluck='name')

        copied = forms.copy_form(company=self.company, name=source_name)['data']
        self.assertNotEqual(copied['name'], source_name)
        self.assertEqual(copied['kind'], 'Stage')
        self.assertEqual(copied['company'], self.company)
        self.assertEqual(copied['title'], f'{opened["schema"]["title"]} - نسخه اختصاصی')
        self.assertEqual(copied['schema']['kind'], 'Stage')
        self.assertTrue(copied['active_revision'])
        self.assertEqual(copied['schema']['sections'][0]['fields'][0]['key'], 'expert_review')

        # The source is never changed by a copy.
        self.assertEqual(frappe.db.get_value('ASOUD Form', source_name, 'draft_version'), source_draft_version)
        self.assertEqual(frappe.db.get_value('ASOUD Form', source_name, 'active_revision'), source_revision)
        self.assertEqual(frappe.get_all('ASOUD Form Revision', filters={'form': source_name}, pluck='name'), source_revisions)

        # A custom title is honored.
        titled = forms.copy_form(company=self.company, name=source_name, title='کپی اختصاصی')['data']
        self.assertEqual(titled['title'], 'کپی اختصاصی')
        self.assertNotEqual(titled['name'], copied['name'])

    def test_copy_form_requires_active_revision_and_stage_kind(self):
        # A draft (no active revision) cannot be copied.
        draft = forms.save_form(company=self.company, client_id='stg-draft-' + 'd' * 16,
                                schema={'kind': 'Stage', 'title': 'پیش‌نویس مرحله',
                                        'sections': [{'id': 'main', 'title': 'اصلی',
                                                      'fields': [{'key': 'note', 'label': 'توضیح', 'type': 'LongText'}]}]})['data']
        with self.assertRaisesRegex(frappe.ValidationError, 'هنوز منتشر نشده است'):
            forms.copy_form(company=self.company, name=draft['name'])

        # A published non-stage form cannot be copied.
        request = forms.save_form(company=self.company, client_id='stg-req-' + 'r' * 17,
                                  schema={'kind': 'Request', 'title': 'درخواست غیرمرحله',
                                          'sections': [{'id': 'main', 'title': 'اصلی',
                                                        'fields': [{'key': 'amount', 'label': 'مبلغ', 'type': 'Money'}]}]})['data']
        forms.transition(name=request['name'], action='publish', expected_version=1)
        with self.assertRaisesRegex(frappe.ValidationError, 'فقط فرم مرحله گردش کار قابل کپی است'):
            forms.copy_form(company=self.company, name=request['name'])

    def test_copy_form_is_designer_only_and_company_scoped(self):

        opened = forms.open_builtin(self.company, 'stage_hr_review', manage=1)['data']
        # A plain employee (company-scoped, no designer role) is refused.
        frappe.set_user(EMPLOYEE_A_USER)
        with self.assertRaises(frappe.PermissionError):
            forms.copy_form(company=self.company, name=opened['name'])
        # A user of another company is refused by company scope.
        frappe.set_user(HR_MANAGER_USER)
        with self.assertRaises(frappe.PermissionError):
            forms.copy_form(company=self.second, name=opened['name'])
        frappe.set_user('Administrator')
