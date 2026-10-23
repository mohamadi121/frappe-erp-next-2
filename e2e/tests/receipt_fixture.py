"""Real equipment rows for the receipt confirmation HTTP spec (N6)."""

import json
import os
import sys
from uuid import uuid4

FOREIGN_USER = 'e2e.receipt.foreign@example.com'
FOREIGN_PASSWORD = 'E2e-Pw-Foreign-2026'
REQUESTER = 'asoud.employee@example.com'


def one(doctype, **values):
    import frappe

    return frappe.get_doc({'doctype': doctype, **values}).insert(ignore_permissions=True)


def prepare():
    import frappe
    from frappe.utils import add_days, nowdate
    from frappe.utils.password import update_password

    from asoud_erp.integration_tests.fixtures import company
    from asoud_erp.integration_tests.request_fixtures import make_definition
    from asoud_erp.services.form_execution.asset_movement import apply
    from asoud_erp.services.request_followup_runtime import create_followup

    token = uuid4().hex[:8]
    name = company()
    second = frappe.db.get_value('Company', {'name': ['!=', name]}, 'name')
    location = one('Location', location_name='E2E receipt ' + token).name
    account = frappe.get_all('Account', filters=dict(company=name, is_group=0, account_type='Fixed Asset'),
                             pluck='name', limit=1)[0]
    category = one('Asset Category', asset_category_name='E2E receipt ' + token,
                   accounts=[dict(company_name=name, fixed_asset_account=account)]).name
    item = one('Item', item_code='E2E receipt ' + token, stock_uom='Nos', is_fixed_asset=1, is_stock_item=0,
               item_group=frappe.get_all('Item Group', filters={'is_group': 0}, pluck='name', limit=1)[0],
               asset_category=category).name
    asset = one('Asset', asset_name='لپ‌تاپ E2E ' + token, item_code=item, company=name, location=location,
                is_existing_asset=1, purchase_date=add_days(nowdate(), -30),
                available_for_use_date=add_days(nowdate(), -30), gross_purchase_amount=100, asset_quantity=1)
    asset.submit()
    definition, _ = make_definition(name, token='rcv-' + token)
    if not frappe.db.exists('User', FOREIGN_USER):
        one('User', email=FOREIGN_USER, first_name='E2E Foreign', send_welcome_email=0,
            roles=[dict(role='Employee')])
        update_password(FOREIGN_USER, FOREIGN_PASSWORD)
    if not frappe.db.exists('Employee', {'user_id': FOREIGN_USER}):
        one('Employee', first_name='E2E Foreign', company=second, user_id=FOREIGN_USER, status='Active',
            gender='Male', date_of_birth='1990-01-01', date_of_joining='2020-01-01', create_user_permission=0)
    cases = {}
    for key in ('confirm', 'reject'):
        instance = one('ASOUD Workflow Instance', workflow_definition=definition, subject='تجهیزات ' + key,
                       status='Completed', started_by=REQUESTER)
        request = one('ASOUD Workflow Request', company=name, workflow_definition=definition,
                      workflow_instance=instance.name, request_type='تجهیزات', subject='تجهیزات ' + key,
                      status='Completed')
        request.db_set('owner', REQUESTER)
        result = apply(request, dict(asset=asset.name, direction='Issue', date=nowdate(), note='تحویل'))
        task = create_followup(request, result.followup)
        cases[key] = dict(request=request.name, instance=instance.name, movement=result.name, task=task)
    return dict(token=token, asset=asset.name, location=location, category=category, item=item,
                definition=definition, cases=cases, company=name)


def inspect(asset, movement, instance, task):
    import frappe

    return dict(
        docstatus=frappe.db.get_value('Asset Movement', movement, 'docstatus'),
        custodian=frappe.db.get_value('Asset', asset, 'custodian'),
        employee=frappe.db.get_value('Employee', {'user_id': REQUESTER}, 'name'),
        status=frappe.db.get_value('ASOUD Workflow Task', task, 'status'),
        comment=frappe.db.get_value('ASOUD Workflow Task', task, 'comment'),
        notified=frappe.get_all('Notification Log', filters={
            'document_type': 'ASOUD Workflow Instance', 'document_name': instance,
            'subject': ['like', '%عدم دریافت%']}, pluck='for_user'),
        movement_comments=frappe.db.count('Comment', {'reference_doctype': 'Asset Movement',
                                                      'reference_name': movement, 'comment_type': 'Comment'}))


def cleanup(asset, location, category, item, definition, cases, **_):
    import frappe

    for case in cases.values():
        for doctype in ('ASOUD Workflow Activity', 'ASOUD Workflow Task'):
            frappe.db.delete(doctype, {'workflow_instance': case['instance']})
        frappe.db.delete('Notification Log', {'document_name': case['instance']})
        frappe.db.delete('Comment', {'reference_doctype': 'Asset Movement', 'reference_name': case['movement']})
        frappe.db.delete('Asset Movement Item', {'parent': case['movement']})
        frappe.db.delete('Asset Movement', {'name': case['movement']})
        frappe.db.delete('ASOUD Workflow Request', {'name': case['request']})
        frappe.db.delete('ASOUD Workflow Instance', {'name': case['instance']})
    frappe.db.delete('Asset Activity', {'asset': asset})
    frappe.db.delete('Asset', {'name': asset})
    frappe.db.delete('Item', {'name': item})
    frappe.db.delete('Asset Category', {'name': category})
    frappe.db.delete('Location', {'name': location})
    for doctype in ('ASOUD Workflow Transition', 'ASOUD Workflow Stage'):
        frappe.db.delete(doctype, {'workflow_definition': definition})
    frappe.db.delete('ASOUD Workflow Definition', {'name': definition})
    return {'cleaned': True}


if __name__ == '__main__':
    bench = os.path.expanduser('~/frappe-dev/bench')
    for app in ('frappe', 'erpnext', 'hrms'):
        sys.path.insert(0, os.path.join(bench, 'apps', app))
    import frappe

    os.chdir(os.path.join(bench, 'sites'))
    frappe.init(site=os.environ.get('E2E_SITE', 'asoud.test'))
    frappe.connect()
    frappe.set_user('Administrator')
    action = sys.argv[1]
    options = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    try:
        if action == 'prepare':
            result = prepare()
        elif action == 'inspect':
            result = inspect(**options)
        elif action == 'cleanup':
            result = cleanup(**options)
        else:
            raise ValueError('unknown action')
        frappe.db.commit()
        print('@@RECEIPT_JSON@@' + json.dumps(result, ensure_ascii=False, default=str))
    finally:
        frappe.destroy()
