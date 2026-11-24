"""Additional denial-only office boundary over native Frappe DocPerms (no new ACL engine)."""
import frappe


def managed(user):
    return frappe.db.table_exists('ASOUD Access Assignment') and bool(frappe.db.exists(
        'ASOUD Access Assignment', {'user': user, 'company': ['is', 'set']}))


def native_roles(user, company):
    return frappe.get_all('ASOUD Access Assignment', filters={'user': user, 'company': company},
        pluck='native_role', limit_page_length=0)


def has_grant(user, company, doctype, action, level=0):
    if user == 'Administrator':
        return True
    from asoud_erp.services.request_access import company_access

    if not company_access(company, user):
        return False
    # Existing delegated managers keep native rights inside their explicit
    # office. New managed accounts use only their account/office grant role.
    roles = set(native_roles(user, company) if managed(user) else frappe.get_roles(user))
    return any(p.role in roles and int(p.permlevel or 0) == level and p.get(action)
               for p in frappe.get_meta(doctype).permissions)


def document_company(doc):
    if doc.doctype == 'ASOUD Role Definition' and not doc.get('template_key'):
        return None  # legacy technical role, not an office template
    if doc.doctype == 'ASOUD Access Assignment' and str(doc.get('native_role') or '').startswith('ASOUD-ACCESS-'):
        return None  # legacy technical assignment, awaiting explicit review
    if doc.doctype == 'Company':
        return doc.name
    if doc.meta.has_field('company'):
        return doc.get('company')
    if doc.meta.has_field('employee') and doc.get('employee'):
        return frappe.db.get_value('Employee', doc.employee, 'company')
    if doc.get('workflow_instance'):
        return frappe.db.get_value('ASOUD Workflow Instance', doc.workflow_instance, 'company')
    return None


def permission(doc, user=None, ptype=None, permission_type=None, **kwargs):
    user = user or frappe.session.user
    if user == 'Administrator' or user == 'Guest':
        return None
    if doc.doctype == 'Company' and doc.is_new() and (ptype or permission_type) == 'create':
        return None  # native create permission still applies before ownership exists
    from asoud_erp.services.request_access import company_access

    action = ptype or permission_type or 'read'
    if action in {'write', 'delete', 'submit', 'cancel', 'amend'} and not doc.is_new():
        # Authorise the stored tenant as well as the proposed tenant. A caller
        # must not move a foreign row into his office in the submitted JSON.
        before = doc.get_doc_before_save() or frappe.get_doc(doc.doctype, doc.name)
        stored_company = document_company(before)
        if stored_company and not company_access(stored_company, user):
            return False
    company = document_company(doc)
    if company and not company_access(company, user):
        return False
    if not managed(user) or not company:
        return None
    if action == 'select':
        action = 'read'
    if doc.doctype == 'Company' and action == 'read':
        return None
    # Native personal Employee access remains personal, not HR authority.
    if doc.doctype == 'Employee' and doc.user_id == user and action == 'read':
        return None
    if doc.meta.has_field('employee') and doc.get('employee') and action in {'read', 'create', 'write'}:
        if frappe.db.get_value('Employee', doc.employee, 'user_id') == user:
            # Native self-service permissions still decide the permitted actions.
            return None
    # Workflow task/instance permissions remain owned by the existing runtime.
    if doc.doctype.startswith('ASOUD Workflow'):
        return None
    return None if has_grant(user, company, doc.doctype, action) else False


def query(user=None, doctype=None):
    user = user or frappe.session.user
    if user in {'Administrator', 'Guest'} or not doctype:
        return ''
    meta = frappe.get_meta(doctype)
    linked_employee = doctype != 'Employee' and meta.has_field('employee')
    if doctype != 'Company' and not meta.has_field('company') and not linked_employee:
        return ''
    from asoud_erp.services.request_access import company_access

    companies = [name for name in frappe.get_all('Company', pluck='name') if company_access(name, user)]
    personal = doctype == 'Employee' or linked_employee
    if managed(user) and doctype != 'Company' and not doctype.startswith('ASOUD Workflow'):
        companies = [c for c in companies if has_grant(user, c, doctype, 'read') or (
            personal and frappe.db.exists('Employee', {'company': c, 'user_id': user}))]
    if not companies:
        return '1=0'
    if linked_employee and not meta.has_field('company'):
        clauses = [f"(`company`={frappe.db.escape(c)}" + (
            ')' if not managed(user) or has_grant(user, c, doctype, 'read')
            else f" AND `user_id`={frappe.db.escape(user)})") for c in companies]
        return f"`tab{doctype}`.`employee` IN (SELECT `name` FROM `tabEmployee` WHERE " + ' OR '.join(clauses) + ')'
    field = 'name' if doctype == 'Company' else 'company'
    scope = f"`tab{doctype}`.`{field}` IN ({','.join(frappe.db.escape(c) for c in companies)})"
    if managed(user) and personal:
        personal_clause = (f"`user_id`={frappe.db.escape(user)}" if doctype == 'Employee' else
            f"`tab{doctype}`.`employee` IN (SELECT `name` FROM `tabEmployee` WHERE `user_id`={frappe.db.escape(user)})")
        clauses = [f"(`company`={frappe.db.escape(c)} AND " + (
            '1=1)' if has_grant(user, c, doctype, 'read') else personal_clause + ')')
            for c in companies]
        scope += ' AND (' + ' OR '.join(clauses) + ')'
    return scope


def guard_write(doc, method=None):
    if frappe.session.user in {'Administrator', 'Guest'} or not managed(frappe.session.user):
        return
    if doc.doctype in {'ASOUD Access Assignment', 'ASOUD Role Definition', 'ASOUD Security Audit'}:
        return
    if not document_company(doc):
        return
    before = doc.get_doc_before_save()
    if before and document_company(before) != document_company(doc):
        frappe.throw('تغییر دفتر سند از مسیر ویرایش مجاز نیست.', frappe.PermissionError)
    action = 'delete' if method == 'on_trash' else 'create' if doc.is_new() else 'write'
    if method == 'before_submit':
        action = 'submit'
    elif method == 'before_cancel':
        action = 'cancel'
    if permission(doc, ptype=action) is False:
        frappe.throw('مجوز این عملیات را در دفتر این سند ندارید.', frappe.PermissionError)
