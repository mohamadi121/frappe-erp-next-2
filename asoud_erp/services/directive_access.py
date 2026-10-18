"""Directive authorization shared by RPC, REST, private downloads and controllers."""
from contextlib import contextmanager
from contextvars import ContextVar

import frappe

COMMUNICATION = "ASOUD Internal Communication"
_writing = ContextVar("directive_service_write", default=False)
ADAPTER_PREFIX = "ASOUD-DIRECTIVE-"


@contextmanager
def service_write():
    token = _writing.set(True)
    try:
        yield
    finally:
        _writing.reset(token)


def active_user(user):
    return user not in (None, "Guest", "Administrator") and bool(
        frappe.db.get_value("User", user, "enabled"))


def can_read(doc, user=None):
    user = user or frappe.session.user
    if not active_user(user) or not frappe.db.exists("Employee", {
        "user_id": user, "company": doc.company, "status": "Active"
    }):
        return False
    return doc.sender == user or (doc.status != "Draft" and any(
        row.user == user for row in doc.recipients))


def communication_permission(doc, user=None, permission_type=None):
    if doc.communication_type != "Directive":
        return None
    return permission_type in (None, "read", "select") and can_read(doc, user)


def directive_for(doc):
    if doc.doctype == "Comment" and doc.reference_doctype == COMMUNICATION and doc.reference_name:
        return directive_for(frappe.get_doc(COMMUNICATION, doc.reference_name))
    if doc.doctype == COMMUNICATION:
        return doc if doc.communication_type == "Directive" else None
    if doc.doctype == "File":
        if doc.attached_to_doctype not in (COMMUNICATION, "ASOUD Workflow Task") or not doc.attached_to_name:
            return None
        return directive_for(frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name))
    if doc.doctype in ("ASOUD Workflow Task", "ASOUD Workflow Activity"):
        if not doc.workflow_instance:
            return None
        doc = frappe.get_doc("ASOUD Workflow Instance", doc.workflow_instance)
    if doc.doctype == "ASOUD Workflow Instance" and doc.reference_doctype == COMMUNICATION and doc.reference_name:
        return directive_for(frappe.get_doc(COMMUNICATION, doc.reference_name))
    return None


def workflow_permission(doc, user=None, permission_type=None):
    directive = directive_for(doc)
    if not directive:
        return None
    user = user or frappe.session.user
    if permission_type not in (None, "read", "select") or not can_read(directive, user):
        return False
    if doc.doctype == "ASOUD Workflow Task":
        return user in (directive.sender, doc.assigned_to)
    if doc.doctype == "ASOUD Workflow Activity":
        return user == directive.sender or doc.actor == user
    return True


def file_permission(doc, user=None, permission_type=None):
    directive = directive_for(doc)
    if not directive:
        return None
    user = user or frappe.session.user
    if permission_type not in (None, "read", "select") or not doc.is_private or not can_read(directive, user):
        return False
    if doc.attached_to_doctype == "ASOUD Workflow Task":
        return workflow_permission(frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name), user, "read")
    if doc.attached_to_field == "directive":
        return True
    return doc.owner == user  # staged uploads are private even from the issuer


def _protected(doc):
    if doc.doctype == "ASOUD Directive Receipt":
        return True
    if doc.doctype in ("ASOUD Workflow Definition", "ASOUD Workflow Stage", "ASOUD Workflow Transition"):
        name = (doc.get("workflow_code") or doc.name) if doc.doctype == "ASOUD Workflow Definition" else doc.workflow_definition
        return str(name or "").startswith(ADAPTER_PREFIX)
    return bool(directive_for(doc))


def guard_write(doc, method=None):
    """Check old AND new relationships: changing type/parent cannot detach protection."""
    if _writing.get() or doc.doctype not in {
        COMMUNICATION, "Comment", "File", "ASOUD Directive Receipt",
        "ASOUD Workflow Definition", "ASOUD Workflow Stage", "ASOUD Workflow Transition",
        "ASOUD Workflow Instance", "ASOUD Workflow Task", "ASOUD Workflow Activity",
    }:
        return
    old = doc.get_doc_before_save()
    if not old and not doc.is_new() and frappe.db.exists(doc.doctype, doc.name):
        old = frappe.get_doc(doc.doctype, doc.name)
    if _protected(doc) or (old and _protected(old)):
        frappe.throw("از API اختصاصی دستور استفاده کنید.", frappe.PermissionError)


def reject_generic(doc):
    if directive_for(doc):
        frappe.throw("این وظیفه فقط از API دستورات قابل اقدام است.", frappe.PermissionError)


def communication_query(user=None):
    user = frappe.db.escape(user or frappe.session.user)
    table = "`tabASOUD Internal Communication`"
    return (f"({table}.communication_type != 'Directive' OR ("
        f"EXISTS (SELECT 1 FROM `tabUser` du WHERE du.name={user} AND du.enabled=1) AND "
        f"EXISTS (SELECT 1 FROM `tabEmployee` de WHERE de.user_id={user} AND de.status='Active' AND de.company={table}.company) AND "
        f"({table}.sender={user} OR ({table}.status!='Draft' AND EXISTS (SELECT 1 FROM "
        f"`tabASOUD Communication Recipient` dr WHERE dr.parent={table}.name AND dr.parenttype='{COMMUNICATION}' AND dr.user={user})))))")


def instance_clause(user=None):
    return ("(COALESCE(`tabASOUD Workflow Instance`.reference_doctype,'') != 'ASOUD Internal Communication' OR "
        "`tabASOUD Workflow Instance`.reference_name IN (SELECT name FROM `tabASOUD Internal Communication` WHERE "
        + communication_query(user) + "))")


def task_clause(user=None):
    user = frappe.db.escape(user or frappe.session.user)
    return ("(COALESCE(`tabASOUD Workflow Task`.directive_kind,'')='' OR "
        f"`tabASOUD Workflow Task`.assigned_to={user} OR `tabASOUD Workflow Task`.workflow_instance IN "
        "(SELECT workflow_instance FROM `tabASOUD Internal Communication` WHERE communication_type='Directive' "
        f"AND sender={user}))")


def file_clause(user=None):
    raw_user = user or frappe.session.user
    user = frappe.db.escape(raw_user)
    return ("(COALESCE(`tabFile`.attached_to_doctype,'') != 'ASOUD Internal Communication' OR "
        "`tabFile`.attached_to_name IN (SELECT name FROM `tabASOUD Internal Communication` WHERE "
        + communication_query(raw_user) + ")) AND (COALESCE(`tabFile`.attached_to_doctype,'') != 'ASOUD Workflow Task' OR "
        "`tabFile`.attached_to_name IN (SELECT name FROM `tabASOUD Workflow Task` WHERE "
        + task_clause(raw_user) + " AND workflow_instance IN (SELECT name FROM `tabASOUD Workflow Instance` WHERE "
        + instance_clause(raw_user) + "))) AND (COALESCE(`tabFile`.attached_to_field,'') != 'directive_pending' OR "
        f"`tabFile`.owner={user})")
