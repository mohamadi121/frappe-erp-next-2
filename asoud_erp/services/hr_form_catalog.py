"""Trusted catalog of the existing HR schemas; no client supplied definitions."""
import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _bundle():
    return json.loads(Path(__file__).with_name('hr_form_presets.json').read_text(encoding='utf-8'))


def catalog():
    return deepcopy(_bundle())


def form_name(company, key):
    return hashlib.sha256(f'asoud-builtin-hr:{company}:{key}'.encode()).hexdigest()[:32]


def builtin_key(company, name):
    return next((key for key in _bundle() if form_name(company, key) == name), None)


def catalog_rows(company, existing):
    return [dict(name=form_name(company, key), company=company, title=schema['title'],
                 kind='Request', module_key='HR', schema=schema, status='Published',
                 draft_version=0, version=1, builtin_key=key, builtin_pending=True)
            for key, schema in catalog().items() if form_name(company, key) not in existing]


def ensure_builtin(company, key):
    import frappe

    from asoud_erp.api.v1.forms import store
    from asoud_erp.services.form_schema import fail, validate_schema

    schemas = catalog()
    if not isinstance(key, str) or key not in schemas:
        fail('قالب پیش‌فرض انتخاب‌شده معتبر نیست.')
    # Shared company lock serializes concurrent first opens and removal.
    frappe.get_doc('Company', company, for_update=True)
    name = form_name(company, key)
    if frappe.db.exists('ASOUD Form', name):
        return frappe.get_doc('ASOUD Form', name, for_update=True)
    schema = validate_schema(schemas[key])
    encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True)
    doc = frappe.get_doc(dict(doctype='ASOUD Form', name=name, company=company,
                              title=schema['title'], kind='Request', module_key='HR',
                              draft_json=encoded, draft_version=1, disabled=0, pending_review=0))
    doc.flags.name_set = True
    store(doc)
    rev = store(frappe.get_doc(dict(doctype='ASOUD Form Revision', form=doc.name,
        version=1, schema_json=encoded, published_by=frappe.session.user,
        published_on=frappe.utils.now_datetime(), change_note='قالب پیش‌فرض همراه برنامه')))
    doc.active_revision = rev.name
    store(doc)
    return doc
