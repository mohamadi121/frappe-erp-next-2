"""Clean only the deterministic catalog identity reserved by this HTTP test."""
import os
import sys

if __name__ == '__main__':
    bench = os.environ.get('E2E_BENCH_PATH', os.path.expanduser('~/frappe-dev/bench'))
    for app in ('frappe', 'erpnext', 'hrms'):
        sys.path.insert(0, os.path.join(bench, 'apps', app))
    import frappe

    from asoud_erp.services.hr_form_catalog import form_name

    os.chdir(os.path.join(bench, 'sites'))
    frappe.init(site=os.environ.get('E2E_SITE', 'asoud.test'))
    frappe.connect()
    try:
        action, company, key = sys.argv[1:4]
        name = form_name(company, key)
        if action == 'reserve':
            if frappe.db.exists('ASOUD Form', name):
                raise RuntimeError('Test requires an unused catalog identity; existing records are never deleted.')
        elif action == 'cleanup':
            if frappe.db.exists('ASOUD Form Entry', {'form': name}):
                raise RuntimeError('Refusing to remove a catalog form with entries.')
            frappe.db.delete('ASOUD Form Revision', {'form': name})
            frappe.db.delete('Comment', {'reference_doctype': 'ASOUD Form', 'reference_name': name})
            frappe.db.delete('ASOUD Form', {'name': name})
            frappe.db.commit()
        else:
            raise ValueError(action)
    finally:
        frappe.destroy()
