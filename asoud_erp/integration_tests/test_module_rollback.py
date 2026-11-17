"""PA-054: the module-key rollback report and the legacy-key read/save path.

A definition seeded with a legacy key (as old code would store it) must still open,
edit and save through the API and end on the canonical key, and rerunning the v0.18
normalization patch must delete nothing. Real rows, no mocks of frappe.db."""
import frappe

from asoud_erp.api.v1 import workflow
from asoud_erp.integration_tests.fixtures import APITestCase, _user
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.tenancy import setup_tenancy
from asoud_erp.services.module_rollback import REVERSE_MODULE_KEYS, rollback_report


class TestModuleRollback(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()
        cls.manager = _user('asoud.module-rollback-manager@example.com', ['System Manager'])
        frappe.db.commit()

    def test_reverse_map_covers_the_legacy_keys_and_not_it(self):
        # The runbook's reverse map must match the forward patch exactly, and IT has none.
        self.assertEqual(REVERSE_MODULE_KEYS, {
            "Finance": "Accounting", "Selling": "Sales", "Stock": "Inventory", "Admin": "Support"})
        self.assertNotIn("IT", REVERSE_MODULE_KEYS)
        self.assertNotIn("Purchase", REVERSE_MODULE_KEYS)
        self.assertNotIn("HR", REVERSE_MODULE_KEYS)

    def test_rollback_report_counts_keys_and_lists_it_definitions(self):
        # A fresh definition (canonical key) plus one forced to IT.
        definition, _ = make_definition(self.company, approvals=0, fields=[])
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'module_key', 'IT')
        report = rollback_report()
        self.assertGreaterEqual(report['counts'].get('IT', 0), 1)
        self.assertIn(definition, report['it_definitions'])
        # Every canonical key is present in the report even when zero.
        for key in ("Finance", "Purchase", "Selling", "Stock", "HR", "Admin", "IT"):
            self.assertIn(key, report['counts'])

    def test_legacy_key_definition_opens_edits_and_saves_canonical(self):
        definition, _ = make_definition(self.company, approvals=0, fields=[])
        # Simulate a record stored by old code with the legacy key "Inventory".
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'module_key', 'Inventory')
        # The read path shows the canonical key to the app.
        listed = workflow.list_workflows(company=self.company)['data']
        row = next(item for item in listed if item['name'] == definition)
        self.assertEqual(row['module_key'], 'Stock')
        # Editing and saving through the API keeps the canonical key.
        workflow.update_request_type_info(definition, workflow_title='گردش‌کار انبار آزمایشی',
            module_key='Stock')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', definition, 'module_key'), 'Stock')

    def test_rerun_of_normalize_module_keys_patch_deletes_nothing(self):
        definition, _ = make_definition(self.company, approvals=0, fields=[])
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'module_key', 'Inventory')
        before = frappe.db.count('ASOUD Workflow Definition')
        from asoud_erp.patches.v0_18.normalize_module_keys import execute

        execute()
        after = frappe.db.count('ASOUD Workflow Definition')
        self.assertEqual(before, after)
        # The patch normalized the legacy key in place; it did not drop the row.
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Definition', definition, 'module_key'), 'Stock')
