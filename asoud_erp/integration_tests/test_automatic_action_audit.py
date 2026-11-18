"""Real-site regressions for automatic-action metadata, permissions and execution."""
import json
from uuid import uuid4

import frappe

from asoud_erp.api.v1 import automatic_actions, forms, workflow
from asoud_erp.integration_tests.fixtures import (
    ACCOUNTANT_USER,
    CUSTOMER,
    EMPLOYEE_USER,
    ITEM,
    SUPPLIER,
    APITestCase,
    warehouse,
)
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

    def test_calculate_supports_min_max_average_and_count(self):
        def fixed(value):
            return {'source': 'constant', 'value': value}
        # min/max are scalar over the mapped inputs; average and count route through
        # the form engine's single-column table aggregation (it has no scalar form).
        cases = {
            'min': 1.0, 'max': 9.0, 'average': 5.0, 'count': 2.0,
        }
        for method, expected in cases.items():
            result, _, _, _ = self.run_action('Calculate Value', {'target': {'source': 'current'},
                'field': 'amount', 'method': method,
                'inputs': {'a': fixed(1), 'b': fixed(9)}})
            values = json.loads(frappe.db.get_value(result['doctype'], result['name'], 'values_json'))
            self.assertEqual(values['amount'], expected, method)

    def table_execution(self):
        """A request whose form has a Table field with a numeric and a text column."""
        self.service()
        fields = [
            {'key': 'total', 'label': 'مجموع', 'type': 'Number'},
            {'key': 'lines', 'label': 'اقلام', 'type': 'Table',
             'columns': [{'key': 'amount', 'label': 'مبلغ', 'type': 'Number'},
                         {'key': 'note', 'label': 'توضیح', 'type': 'Short Text'}]},
        ]
        definition, stages = make_definition(self.company, fields=fields)
        request = create(self.company, definition=definition,
            values={'total': 0, 'lines': [{'amount': 10, 'note': 'اول'}, {'amount': 20, 'note': 'دوم'}]})
        stage = frappe.get_doc({'doctype': 'ASOUD Workflow Stage', 'workflow_definition': definition,
            'stage_key': uuid4().hex, 'stage_type': 'System Action', 'stage_title': 'خودکار',
            'sequence_no': 10, 'config_json': '{}'}).insert().name
        instance = frappe.get_doc('ASOUD Workflow Instance', request['workflow_instance'])
        receipt = frappe._dict(name=uuid4().hex, workflow_stage=stage)
        return definition, stage, instance, receipt

    def test_calculate_aggregates_a_table_column(self):
        definition, stage, instance, receipt = self.table_execution()
        # The action aggregates one column of the request's Table field; the form
        # engine's Decimal table aggregation does the math.
        cases = {'sum': 30.0, 'average': 15.0, 'min': 10.0, 'max': 20.0, 'count': 2.0}
        for method, expected in cases.items():
            config = validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Calculate Value',
                'operation': {'target': {'source': 'current'}, 'field': 'total', 'method': method,
                    'inputs': {}, 'table': {'table': 'lines', 'column': 'amount'}},
                'execution': {'extra_attempts': 0, 'retry_seconds': 60, 'timeout_seconds': 120}})
            with identity(self.company):
                result = perform(receipt, instance, config, self.company)
            values = json.loads(frappe.db.get_value(result['doctype'], result['name'], 'values_json'))
            self.assertEqual(values['total'], expected, method)

    def test_calculate_table_aggregation_rejects_a_non_numeric_column(self):
        definition, stage, _, _ = self.table_execution()
        with self.assertRaisesRegex(ValueError, 'باید عددی باشد'):
            validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Calculate Value',
                'operation': {'target': {'source': 'current'}, 'field': 'total', 'method': 'sum',
                    'inputs': {}, 'table': {'table': 'lines', 'column': 'note'}},
                'execution': {'extra_attempts': 0, 'retry_seconds': 60, 'timeout_seconds': 120}})

    def test_calculate_table_aggregation_rejects_an_unknown_table_field(self):
        definition, stage, _, _ = self.table_execution()
        with self.assertRaisesRegex(ValueError, 'فیلد جدول'):
            validate_config(definition, stage, {'schema_version': 2, 'action_type': 'Calculate Value',
                'operation': {'target': {'source': 'current'}, 'field': 'total', 'method': 'sum',
                    'inputs': {}, 'table': {'table': 'nope', 'column': 'amount'}},
                'execution': {'extra_attempts': 0, 'retry_seconds': 60, 'timeout_seconds': 120}})

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

    # --- PA-048: the engine supports the commercial documents --------------------

    def test_create_document_supports_a_native_sales_order(self):
        result, _, _, _ = self.run_action('Create Document', {'doctype': 'Sales Order', 'initial_state': 'Draft',
            'link_original': True, 'mapping': {'customer': {'source': 'constant', 'value': CUSTOMER},
                'transaction_date': {'source': 'system', 'value': 'today'},
                'items': {'source': 'current', 'value': 'items'}}})
        native = frappe.get_doc('Sales Order', result['name'])
        self.assertEqual(native.docstatus, 0)
        self.assertEqual(native.customer, CUSTOMER)
        self.assertEqual(native.items[0].item_code, ITEM)
        self.assertEqual(native.items[0].qty, 2)

    def test_create_document_supports_a_native_purchase_order(self):
        result, _, _, _ = self.run_action('Create Document', {'doctype': 'Purchase Order', 'initial_state': 'Draft',
            'link_original': True, 'mapping': {'supplier': {'source': 'constant', 'value': SUPPLIER},
                'transaction_date': {'source': 'system', 'value': 'today'},
                'items': {'source': 'current', 'value': 'items'}}})
        native = frappe.get_doc('Purchase Order', result['name'])
        self.assertEqual(native.docstatus, 0)
        self.assertEqual(native.supplier, SUPPLIER)
        self.assertEqual(native.items[0].item_code, ITEM)
        self.assertEqual(native.items[0].qty, 2)

    def test_create_document_supports_a_native_stock_entry(self):
        result, _, _, _ = self.run_action('Create Document', {'doctype': 'Stock Entry', 'initial_state': 'Draft',
            'link_original': True, 'mapping': {'purpose': {'source': 'constant', 'value': 'Material Receipt'},
                'posting_date': {'source': 'system', 'value': 'today'},
                'items': {'source': 'current', 'value': 'items'},
                'warehouse': {'source': 'constant', 'value': warehouse()}}})
        native = frappe.get_doc('Stock Entry', result['name'])
        self.assertEqual(native.docstatus, 0)
        self.assertEqual(native.purpose, 'Material Receipt')
        self.assertEqual(native.items[0].item_code, ITEM)
        self.assertEqual(native.items[0].t_warehouse, warehouse())

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

    def test_error_route_to_an_end_stage_is_accepted_at_save(self):
        # A failed automatic action may terminate the process at an End stage, so the
        # designer save must accept an Error route to End (not only a human task).
        definition, stage = self.graph()
        end = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'End'})
        config = {'schema_version': 2, 'title': 'اعلان خطا', 'action_type': 'Send Notification',
            'operation': {'recipients': ['initiator'], 'channels': ['in_app'], 'message': 'درخواست متوقف شد'}}
        automatic_actions.save(definition, stage, config, {'Success': end, 'Error': end})
        self.assertTrue(frappe.db.exists('ASOUD Workflow Transition', {
            'workflow_definition': definition, 'from_stage': stage, 'to_stage': end,
            'condition_json': json.dumps({'action': 'Error'})}))

    def test_error_route_to_a_non_human_non_end_stage_is_rejected_at_save(self):
        # An Error route may only go to a human task or End; a Condition stage is refused.
        definition = workflow.create_workflow_draft(company=self.company, module_key='HR',
            target_doctype='ASOUD Workflow Request', workflow_title='آزمون مسیر خطا')['data']['name']
        start = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Start'})
        workflow.add_workflow_stage(definition, 'System Action', start)
        stage = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'System Action'})
        workflow.add_workflow_stage(definition, 'Condition', stage)
        condition = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'Condition'})
        workflow.add_workflow_stage(definition, 'End', condition)
        end = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'End'})
        config = {'schema_version': 2, 'title': 'اعلان خطا', 'action_type': 'Send Notification',
            'operation': {'recipients': ['initiator'], 'channels': ['in_app'], 'message': 'درخواست متوقف شد'}}
        with self.assertRaises(frappe.ValidationError):
            automatic_actions.save(definition, stage, config, {'Success': end, 'Error': condition})

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
        frappe.db.set_value('ASOUD Workflow Definition', child, 'status', 'Inactive')
        workflow.save_stage_settings(child, user_stage.name, {'title': 'بررسی', 'activity_type': 'Review',
            'assignment_type': 'Initiator', 'submission_source': {'form': source['name'], 'revision': source['revision']}})
        frappe.db.set_value('ASOUD Workflow Definition', child, 'status', 'Active')
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

    def test_cancelling_a_request_cancels_its_queued_automatic_actions(self):
        from asoud_erp.api.v1.workflow_request import cancel_request

        # approvals=1 keeps the instance Running (waiting at the approval) so the
        # requester can still cancel it.
        definition, stages = make_definition(self.company, approvals=1, fields=[])
        result = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        self.assertEqual(instance.status, 'Running')
        # A queued automatic action waiting for the background worker.
        queued = frappe.get_doc({'doctype': 'ASOUD Action Execution',
            'workflow_instance': instance.name, 'workflow_stage': list(stages.values())[0].name,
            'trigger_id': uuid4().hex, 'status': 'Pending', 'action_type': 'Send Notification',
            'config_json': '{}', 'routes_json': '{}'}).insert(ignore_permissions=True)
        # A receipt already running is owned by a worker; cancellation must leave it.
        running = frappe.get_doc({'doctype': 'ASOUD Action Execution',
            'workflow_instance': instance.name, 'workflow_stage': list(stages.values())[0].name,
            'trigger_id': uuid4().hex, 'status': 'Running', 'action_type': 'Send Notification',
            'config_json': '{}', 'routes_json': '{}'}).insert(ignore_permissions=True)
        frappe.set_user(EMPLOYEE_USER)
        cancel_request(result['name'], 'لغو آزمایشی')
        frappe.set_user('Administrator')
        self.assertEqual(frappe.db.get_value('ASOUD Action Execution', queued.name, 'status'), 'Cancelled')
        self.assertEqual(frappe.db.get_value('ASOUD Action Execution', running.name, 'status'), 'Running')
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', instance.name, 'status'), 'Cancelled')

    def test_final_failure_notifies_the_requester(self):
        from asoud_erp.services.automatic_action_runtime import _final_failure

        definition, stages = make_definition(self.company, approvals=0, fields=[])
        result = create(self.company, definition=definition)
        instance = frappe.get_doc('ASOUD Workflow Instance', result['workflow_instance'])
        # A failed receipt with no Error route: the instance is marked Failed and the
        # requester must be told, not only System Managers.
        receipt = frappe.get_doc({'doctype': 'ASOUD Action Execution',
            'workflow_instance': instance.name, 'workflow_stage': list(stages.values())[0].name,
            'trigger_id': uuid4().hex, 'status': 'Failed', 'action_type': 'Send Notification', 'attempts': 1,
            'service_user': EMPLOYEE_USER, 'config_json': '{}',
            'routes_json': '{}'}).insert(ignore_permissions=True)
        _final_failure(receipt, instance)
        instance.reload()
        self.assertEqual(instance.status, 'Failed')
        self.assertTrue(frappe.db.exists('Notification Log', {
            'for_user': instance.started_by, 'document_name': instance.name}))

    def test_error_route_to_an_end_stage_terminates_the_instance(self):
        from asoud_erp.services.automatic_action_runtime import _finish

        definition, stage = self.graph()
        end = frappe.db.get_value('ASOUD Workflow Stage', {'workflow_definition': definition, 'stage_type': 'End'})
        instance = frappe.get_doc({'doctype': 'ASOUD Workflow Instance',
            'workflow_definition': definition, 'subject': 'آزمون مسیر خطا', 'status': 'Running',
            'current_stage': stage, 'started_by': EMPLOYEE_USER}).insert(ignore_permissions=True)
        receipt = frappe._dict(name=uuid4().hex, workflow_stage=stage, trigger_id='start',
            routes_json=json.dumps({'Error': end}), config_json='{}')
        _finish(receipt, instance, False)
        instance.reload()
        self.assertEqual(instance.current_stage, end)
        self.assertIn(instance.status, {'Completed', 'Rejected', 'Cancelled', 'Failed'})

    def test_update_fields_on_a_form_entry_is_refused(self):
        from asoud_erp.services.automatic_action_runtime import _update

        saved = forms.save_form(self.company, {'kind': 'Request', 'title': 'فرم به‌روزرسانی خودکار',
            'sections': [{'id': 'main', 'title': 'اطلاعات', 'fields': [
                {'key': 'amount', 'label': 'عدد', 'type': 'Integer'},
                {'key': 'note', 'label': 'توضیح', 'type': 'Text'}]}]}, client_id=uuid4().hex)['data']
        forms.transition(saved['name'], 'publish', saved['draft_version'])
        published = forms.get_form(saved['name'])['data']
        entry = forms.submit_form(published['name'], published['revision'], 'ثبت به‌روزرسانی',
            {'amount': 1, 'note': 'ابتدایی'}, uuid4().hex)['data']
        doc = frappe.get_doc('ASOUD Form Entry', entry['name'])
        # A submitted entry is immutable: the action is refused and nothing changes.
        with self.assertRaisesRegex(frappe.ValidationError, 'تغییرناپذیر'):
            _update(doc, {'amount': 9, 'note': 'به‌روزرسانی‌شده'}, self.company)
        values = json.loads(frappe.db.get_value('ASOUD Form Entry', entry['name'], 'values_json'))
        self.assertEqual(values['note'], 'ابتدایی')
