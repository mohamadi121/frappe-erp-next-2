"""Shared presentation tree for office profiles. Never a source of grants."""
import hashlib
import json
import re

import frappe

FIELD = 'access_catalog_layout'
SETTINGS = 'ASOUD Settings'


def _state(lock=False):
    query = 'select value from tabSingles where doctype=%s and field=%s'
    rows = frappe.db.sql(query + (' for update' if lock else ''), (SETTINGS, FIELD))
    raw = (rows[0][0] if rows else '') or ''
    return (json.loads(raw) if raw else {}), hashlib.sha256(raw.encode()).hexdigest()


def _module_id(title):
    return 'module-' + hashlib.sha256(title.encode()).hexdigest()[:20]


def _version(value, catalog):
    signature = sorted((row['doctype'], row['module'], row['title']) for row in catalog)
    return hashlib.sha256(json.dumps([value, signature]).encode()).hexdigest()


def _visible(state, catalog):
    modules = state.get('modules', [])
    seen = set(state.get('hidden', []))
    seen.update(doc['id'] for module in modules for doc in module['children'])
    by_id = {module['id']: module for module in modules}
    for row in catalog:
        doc_id = 'native:' + row['doctype']
        if doc_id in seen:
            continue
        mid = _module_id(row['module'])
        if mid not in by_id:
            module = {'id': mid, 'title': row['module'], 'children': []}
            modules.append(module)
            by_id[mid] = module
        by_id[mid]['children'].append({'id': doc_id, 'title': row['title'], 'children': []})
    return modules


def read(catalog):
    state, version = _state()
    return {'modules': _visible(state, catalog), 'version': _version(version, catalog),
            'editable': frappe.session.user == 'Administrator'}


def _checked_tree(tree, native, previous):
    used = set()

    def invalid():
        frappe.throw('ساختار کاتالوگ معتبر نیست. نام، شناسه و سطح ردیف‌ها را بررسی کنید.')

    def check(rows, depth):
        if not isinstance(rows, list) or (depth == 3 and rows):
            invalid()
        siblings = set()
        result = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'id', 'title', 'children'}:
                invalid()
            key, title = row['id'], row['title']
            if not isinstance(key, str) or not isinstance(title, str):
                invalid()
            title = title.strip()
            stable = re.fullmatch(r'(custom|module)-[a-f0-9]{20,48}', key)
            native_row = depth == 1 and key.startswith('native:') and key in native | previous
            if (not title or len(title) > 140 or title.casefold() in siblings or key in used
                    or (not stable and not native_row) or len(used) >= 2000):
                invalid()
            used.add(key)
            siblings.add(title.casefold())
            result.append({'id': key, 'title': title, 'children': check(row['children'], depth + 1)})
        return result

    return check(tree, 0)


def save(company, tree, version):
    from asoud_erp.services import office_permission_profiles, security_audit

    office_permission_profiles.gate(company)
    if frappe.session.user != 'Administrator':
        frappe.throw('فقط مدیر اصلی سیستم می‌تواند کاتالوگ مشترک را تغییر دهد.', frappe.PermissionError)
    if not frappe.get_meta(SETTINGS).has_field(FIELD):
        frappe.throw('نسخه تنظیمات سرور هنوز به‌روزرسانی نشده است.')
    if len(json.dumps(tree, ensure_ascii=False)) > 500_000:
        frappe.throw('حجم کاتالوگ بیش از حد مجاز است.')
    # Lock a row that exists even before the first catalog has been saved.
    frappe.db.sql('select name from tabDocType where name=%s for update', (SETTINGS,))
    state, current = _state(lock=True)
    catalog = office_permission_profiles.catalog()
    if version != _version(current, catalog):
        frappe.throw('کاتالوگ در جلسه دیگری تغییر کرده است؛ دوباره آن را باز کنید.', frappe.TimestampMismatchError)
    native = {'native:' + row['doctype'] for row in catalog}
    previous = {doc['id'] for module in state.get('modules', []) for doc in module['children']}
    clean = _checked_tree(tree, native, previous)
    present = {doc['id'] for module in clean for doc in module['children']}
    hidden = sorted((set(state.get('hidden', [])) | native | {
        key for key in previous if key.startswith('native:')
    }) - present)
    frappe.db.set_single_value(SETTINGS, FIELD, json.dumps({'modules': clean, 'hidden': hidden}, ensure_ascii=False))
    security_audit.record('access.catalog_layout_save', company=company, target_type=SETTINGS, target=SETTINGS)
    return read(catalog)
