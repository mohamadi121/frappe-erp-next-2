"""Real-site regressions for automatic-action metadata, permissions and execution."""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import automatic_actions, forms, workflow
from asoud_erp.integration_tests.fixtures import ACCOUNTANT_USER, EMPLOYEE_USER, ITEM, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import create
from asoud_erp.services.automatic_action_metadata import identity, validate_config
from asoud_erp.services.automatic_action_runtime import perform


class TestAutomaticActionAudit(APITestCase):
    def service(self):
        """A dedicated test role; no Administrator execution and no site-config write."""
        from frappe.permissions import add_permission, update_permission_property

        previous = {key: frappe.conf.get(key) for key in ('asoud_workflow_service_user', 'asoud_workflow_service_companies')}
        self.addCleanup(lambda: frappe.conf.update(previous))
        frappe.conf.asoud_workflow_service_user = ACCOUNTANT_USER
        frappe.conf.asoud_workflow_service_companies = [self.company]
        role = 'Automatic Audit ' + uuid4().hex[:8]
        frappe.get_doc({'doctype': 'Role', 'role_name': role}).insert()
        frappe.get_doc('User', ACCOUNTANT_USER).add_roles(role, 'Employee')
        for doctype in ('ASOUD Workflow Request', 'ASOUD Form Entry'):
            add_permission(doctype, role, 0)
            for permission in ('read', 'write', 'create'):
                update_permission_property(doctype, role, 0, permission, 1)
        frappe.clear_cache(user=ACCOUNTANT_USER)

    def execution(self):
        self.service()
        fields = [{'key': 'amount', 'label': 'عدد', 'type': 'Number'},
            {'key': 'reason', 'label': 'شرح', 'type': 'Long Text'},
            {'key': 'items', 'label': 'اقلام', 'type': 'Item Table', 'row_options': {'min_rows': 0, 'max_rows': 10}}]
        definition, stages = make_definition(self.company, fields=fields)
        request = create(self.company, definition=definition, values={'amount': 12, 'reason': 'اطلاعات مبنا',
            'items': [{'item_code': ITEM, 'qty': 2, 'uom': 'Nos'}]})
        stage = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition,
            'stage_key': uuid4().hex, 'stage_type': 'System Action', 'stage_title': 'خودکار',
            'sequence_no': 10, 'config_json': '{}'}).insert().name
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        receipt = frappe._dict(name=uuid4().hex, workflow_stage=stage)
        return definition, stage, instance, receipt, stages

    def run_action(self, kind, operation):
        definition, stage, instance, receipt, _ = self.execution()
        config = validate_config(definition, stage, {'schema_version': 2, 'action_type': kind,
            'operation': operation, 'execution': {'extra_attempts': 0, 'retry_seconds': 60, 'timeout_seconds': 120}})
        with identity(self.company):
            result = perform(receipt, instance, config, self.company)
        return result, instance, receipt, config

    def test_calculate_uses_existing_decimal_form_engine_and_update_is_real(self):
        def fixed(value):
            return {'source': 'constant', 'value': value}
        result, _, _, _ = self.run_action('Calculate Value', {'target': {'source': 'current'},
            'field': 'amount', 'method': 'sum', 'inputs': {'a': fixed(0.1), 'b': fixed(0.2)}})
        values = json.loads(frappe.db.get_value(result['doctype'], result['name'], 'values_json'))
        self.assertEqual(values['amount'], 0.3)

    def test_update_fields_writes_only_allowed_values(self):
        result, _, _, _ = self.run_action('Update Fields', {'target': {'source': 'current'},
            'mapping': {'reason': {'source': 'constant', 'value': 'شرح اصلاح‌شده'},
                'amount': {'source': 'constant', 'value': 0}}})
        values = json.loads(frappe.db.get_value(result['doctype'], result['name'], 'values_json'))
        self.assertEqual((values['amount'], values['reason']), (0, 'شرح اصلاح‌شده'))

    def test_notification_deduplicates_recipient_and_records_each_channel(self):
        result, instance, _, _ = self.run_action('Send Notification', {'recipients': ['initiator', EMPLOYEE_USER],
            'channels': ['in_app', 'email'], 'message': 'بررسی {{subject}}'})
        internal = [row for row in result['notifications'] if row['channel'] == 'in_app']
        self.assertEqual(len(internal), 1)
        self.assertEqual(internal[0]['status'], 'created')
        self.assertTrue(frappe.db.exists('Notification Log', {'name': internal[0]['reference'],
            'document_name': instance.reference_name, 'for_user': EMPLOYEE_USER}))
        self.assertEqual(len([row for row in result['notifications'] if row['channel'] == 'email']), 1)

    def test_link_existing_record_never_changes_its_workflow(self):
        result, instance, _, _ = self.run_action('Link Record', {'target': {'source': 'current'},
            'doctype': 'ASOUD Workflow Request', 'lookup_field': 'subject',
            'lookup': {'source': 'current', 'value': 'subject'}, 'relationship': 'supports',
            'missing': 'error', 'multiple': 'error'})
        self.assertEqual(result['linked_name'], instance.reference_name)
        self.assertEqual(result['relationship'], 'supports')
        self.assertTrue(frappe.db.exists('Comment', result['comment']))

    def test_create_request_reuses_existing_submission_idempotency(self):
        definition, stage, instance, receipt, _ = self.execution()
        child, _ = make_definition(self.company, approvals=0, fields=[{'key': 'amount', 'label': 'عدد', 'type': 'Number'}])
        config = validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Create Request',
            'operation': {'request_type': child, 'mapping': {'subject': {'source': 'constant', 'value': 'درخواست ساخته‌شده'},
                'amount': {'source': 'current', 'value': 'amount'}}, 'link_original': False}})
        with identity(self.company):
            one = perform(receipt, instance, config, self.company)
            two = perform(receipt, instance, config, self.company)
        self.assertEqual(one['name'], two['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Request', {'workflow_definition': child}), 1)

    def test_create_document_reuses_native_material_request_controller(self):
        result, _, _, _ = self.run_action('Create Document', {'doctype': 'Material Request', 'initial_state': 'Draft',
            'link_original': True, 'mapping': {'transaction_date': {'source': 'system', 'value': 'today'},
                'schedule_date': {'source': 'constant', 'value': self.future()},
                'items': {'source': 'current', 'value': 'items'}}})
        native = frappe.get_doc('Material Request', result['name'])
        self.assertEqual(native.docstatus, 0)
        self.assertEqual(native.items[0].item_code, ITEM)
        self.assertEqual(native.items[0].qty, 2)

    def test_change_status_refuses_to_set_an_arbitrary_string(self):
        definition, stage, _, _, _ = self.execution()
        with self.assertRaises((ValueError, frappe.ValidationError)):
            validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Change Status',
                'operation': {'target': {'source': 'current'}, 'transition': 'وضعیت ساختگی'}})

    def test_change_status_uses_a_real_native_transition_under_service_permissions(self):
        definition, stage, instance, receipt, _ = self.execution()
        from asoud_erp.integration_tests.request_fixtures import native_workflow

        source = frappe.get_doc(instance.reference_doctype, instance.reference_name)
        initial = 'Automatic audit pending'
        frappe.db.set_value(source.doctype, source.name, 'display_status', initial)
        target = 'Automatic audit reviewed'
        action = 'Automatic audit review'
        for state in (initial, target):
            if not frappe.db.exists('Workflow State', state):
                frappe.get_doc({'doctype': 'Workflow State', 'workflow_state_name': state}).insert()
        if not frappe.db.exists('Workflow Action Master', action):
            frappe.get_doc({'doctype': 'Workflow Action Master', 'workflow_action_name': action}).insert()
        native = frappe.get_doc('Workflow', native_workflow())
        native.workflow_state_field = 'display_status'  # Existing field: no test DDL or custom schema.
        native.is_active = 1
        native.set('states', [{'state': state, 'doc_status': '0', 'allow_edit': 'Employee'} for state in (initial, target)])
        native.set('transitions', [{'state': initial, 'action': action, 'next_state': target,
            'allowed': 'Employee', 'allow_self_approval': 1}])
        native.save()
        frappe.clear_cache(doctype=source.doctype)
        config = validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Change Status',
            'operation': {'target': {'source': 'current'}, 'transition': action}})
        with identity(self.company):
            perform(receipt, instance, config, self.company)
        self.assertEqual(frappe.db.get_value(source.doctype, source.name, 'display_status'), target)

    def test_atomic_save_rolls_back_settings_if_route_validation_fails(self):
        definition, stage = self.graph()
        before = frappe.db.get_value('ASOUD Workflow Stage', stage, ['config_json', 'stage_title'], as_dict=True)
        invalid = {'schema_version': 2, 'title': 'عنوان نباید باقی بماند', 'action_type': 'Send Notification',
            'operation': {'recipients': ['initiator'], 'channels': ['in_app'], 'message': 'پیام'}}
        with self.assertRaises(frappe.ValidationError):
            automatic_actions.save(definition, stage, invalid, {'Success': stage})
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Stage', stage,
            ['config_json', 'stage_title'], as_dict=True), before)

    def graph(self):
        definition = workflow.create_workflow_draft(company=self.company, module_key='HR',
            target_doctype='ASOUD Workflow Request', workflow_title='آزمون اقدام خودکار')['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'System Action', start)
        stage = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'System Action'})
        workflow.add_workflow_stage(definition, 'End', stage)
        return definition, stage

    def test_options_read_published_source_without_requiring_a_legacy_first_task(self):
        definition, stage = self.graph()
        form = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم مبنای اقدام',
            'sections': [{'id': 'main', 'title': 'اطلاعات', 'fields': [
                {'key': 'amount', 'label': 'مبلغ', 'type': 'Money'},
                {'key': 'kind', 'label': 'نوع', 'type': 'Select', 'options': ['اول', 'دوم']},
            ]}]}, client_id=uuid4().hex)['data']
        forms.transition(form['name'], 'publish', form['draft_version'])
        published = forms.get_form(form['name'])['data']
        workflow.save_start_settings(definition, 'Document Event', [], 'Source Document',
            settings={'trigger_type': 'Document Event', 'initiator_roles': [],
                'submission_source': {'form': form['name'], 'revision': published['revision'], 'kind': 'Request'}})
        result = automatic_actions.options(definition, stage)['data']
        fields = {row['key']: row for row in result['sources']['current']}
        self.assertEqual(fields['amount']['type'], 'Money')
        self.assertEqual(fields['kind']['options'], published['schema']['sections'][0]['fields'][1]['options'])
        self.assertEqual(result['schema_version'], 2)

    def test_real_employee_cannot_read_automatic_configuration(self):
        definition, stage = self.graph()
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            automatic_actions.options(definition, stage)

    def test_native_document_metadata_does_not_use_request_field_reader(self):
        definition, stage = self.graph()
        frappe.db.set_value('ASOUD Workflow Definition', definition, 'target_doctype', 'Material Request')
        result = automatic_actions.options(definition, stage)['data']
        self.assertEqual(result['sources']['record_doctype'], 'Material Request')
        self.assertIn('transaction_date', {row['key'] for row in result['sources']['writable']})

    def test_published_form_request_creation_uses_existing_entry_route_and_idempotency(self):
        definition, stage, instance, receipt, _ = self.execution()
        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'درخواست منتشرشدهٔ مقصد',
            'sections': [{'id': 'main', 'title': 'اطلاعات', 'fields': [
                {'key': 'amount', 'label': 'عدد', 'type': 'Decimal'}]}]}, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        source = forms.get_form(saved['name'])['data']
        child, stages = make_definition(self.company, approvals=0, fields=[])
        user_stage = next(row for row in stages.values() if row.stage_type == 'User Task')
        workflow.save_stage_settings(child, user_stage.name, {'title': 'بررسی', 'activity_type': 'Review',
            'assignment_type': 'Initiator', 'submission_source': {'form': source['name'], 'revision': source['revision']}})
        config = validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Create Request',
            'operation': {'request_type': child, 'link_original': False, 'mapping': {
                'subject': {'source': 'constant', 'value': 'ثبت خودکار فرم منتشرشده'},
                'amount': {'source': 'current', 'value': 'amount'}}}})
        before = frappe.db.count('ASOUD Workflow Request')
        with identity(self.company):
            first = perform(receipt, instance, config, self.company)
            second = perform(receipt, instance, config, self.company)
        self.assertEqual(first['doctype'], 'ASOUD Form Entry')
        self.assertEqual(first['name'], second['name'])
        self.assertEqual(frappe.db.count('ASOUD Workflow Instance', {
            'reference_doctype': first['doctype'], 'reference_name': first['name']}), 1)
        self.assertEqual(frappe.db.count('ASOUD Workflow Request'), before)
