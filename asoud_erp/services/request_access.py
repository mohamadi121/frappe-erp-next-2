import frappe

from asoud_erp.services import certificate_access
from asoud_erp.services import request_access_policy as policy


def company_access(company, user=None):
    user = user or frappe.session.user
    if user == "Guest" or not company:
        return False
    conf = getattr(frappe, "conf", None) or {}
    if user == conf.get("asoud_workflow_service_user"):
        from asoud_erp.services.automatic_action_metadata import service_user

        try:
            return service_user(company) == user
        except frappe.PermissionError:
            return False
    roles = set(frappe.get_roles(user))
    # An account-only first HR lead has no Employee yet. Native Company User
    # Permission is its explicit scope, not membership in every company.
    if "HR Manager" in roles and frappe.db.exists("User Permission", {
        "user": user, "allow": "Company", "for_value": company, "apply_to_all_doctypes": 1
    }):
        return True
    if frappe.db.exists("ASOUD Office Role Assignment", {"user": user, "company": company}):
        return True
    if not roles.intersection({"System Manager", "HR Manager", "Accounts Manager", "Accounts User"}):
        return bool(frappe.db.exists("Employee", {"user_id": user, "company": company, "status": "Active"}))
    if frappe.has_permission("Company", "read", company, user=user):
        return True
    # A manager (e.g. an HR Manager, who has no Company read right in a standard install) who is
    # an active employee of this very office belongs to it, exactly like any other employee.
    return bool(frappe.db.exists("Employee", {"user_id": user, "company": company, "status": "Active"}))


def require_company(company):
    if not company_access(company):
        frappe.throw("شما به اطلاعات این شرکت دسترسی ندارید.", frappe.PermissionError)


#: Activity actions that are a decision the user made on a task. Claiming a shared task,
#: being assigned, saving a draft, escalation and system actions are not decisions (PA-055 P5).
DECISION_ACTIONS = ("Approve", "Reject", "Return", "Complete", "Follow Up", "Blocked",
                    "Reassigned", "Resubmitted")


def request_level(doc, user=None):
    """The approved access level (FULL/MASKED/NONE) of ``user`` for this request (PA-055)."""
    user = user or frappe.session.user
    instance = doc.get("workflow_instance")
    task_rows = []
    if instance:
        task_rows = [{"status": row.status, "acted": row.status == "Completed"}
                     for row in frappe.get_all("ASOUD Workflow Task",
                                               filters={"workflow_instance": instance,
                                                        "assigned_to": user},
                                               fields=["status"], limit_page_length=0)]
    # Acting = a decision activity the user made (a mere Claim of a shared task is not one).
    acted = bool(instance and frappe.db.exists("ASOUD Workflow Activity", {
        "workflow_instance": instance, "actor": user, "action": ["in", list(DECISION_ACTIONS)]}))
    privileged = bool(company_access(doc.company, user)
                      and {"System Manager", "HR Manager"}.intersection(frappe.get_roles(user)))
    return policy.classify(doc.owner == user, privileged, task_rows, acted)


def request_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    conf = getattr(frappe, "conf", None) or {}
    if user == conf.get("asoud_workflow_service_user"):
        # Returning None delegates to ordinary DocType permissions; it does not
        # grant write/read itself. Admin must explicitly grant the required role.
        return None if company_access(doc.company, user) else False
    if permission_type not in (None, "read", "select"):
        return False
    if not company_access(doc.company, user):
        return False
    # Raw document read (REST / frappe.get_doc) is granted only at FULL: the owner, a
    # privileged manager with company access, or the current assignee. A previous assignee
    # who acted (MASKED) reads through the masked whitelisted APIs, not the raw document.
    return request_level(doc, user) == policy.FULL


def request_query(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return "1=0"
    companies = frappe.get_all("Company", pluck="name")
    allowed = [company for company in companies if company_access(company, user)]
    if not allowed:
        return "1=0"
    allowed_sql = ",".join(frappe.db.escape(company) for company in allowed)
    if {"System Manager", "HR Manager"}.intersection(frappe.get_roles(user)):
        return "`tabASOUD Workflow Request`.`company` IN (" + allowed_sql + ")"
    # FULL only (PA-055): the owner, the current assignee (a task still Open for them), or a
    # privileged manager. A previous assignee who acted (MASKED) is excluded from the raw
    # list so a raw REST list cannot hand them unmasked values; they read through the masked
    # whitelisted APIs.
    return ("(`tabASOUD Workflow Request`.`owner` = " + frappe.db.escape(user)
        + " OR `tabASOUD Workflow Request`.`workflow_instance` IN (SELECT `workflow_instance`"
        " FROM `tabASOUD Workflow Task` WHERE `assigned_to` = " + frappe.db.escape(user)
        + " AND `status` = 'Open'))"
        + " AND `tabASOUD Workflow Request`.`company` IN (" + allowed_sql + ")")


def file_permission(doc, user=None, permission_type=None):
    from asoud_erp.services.directive_access import file_permission as directive_file_permission
    result = directive_file_permission(doc, user, permission_type)
    if result is not None:
        return result
    if doc.attached_to_doctype == "ASOUD Workflow Task" and doc.attached_to_name:
        return workflow_record_permission(frappe.get_doc("ASOUD Workflow Task", doc.attached_to_name),
                                          user=user, permission_type=permission_type)
    if doc.attached_to_doctype == "ASOUD Workflow Request":
        if not doc.is_private or not doc.attached_to_name:
            return False
        request = frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name)
        allowed = request_permission(request, user=user, permission_type=permission_type)
        if allowed and doc.get("attached_to_field") == certificate_access.FIELD:
            return certificate_permission(request, user)
        return allowed
    return None


def certificate_permission(request, user=None) -> bool:
    """The issued employment certificate: the requester, HR Managers and System Managers only."""
    user = user or frappe.session.user
    return certificate_access.can_download(
        user=user, roles=frappe.get_roles(user), owner=request.owner,
        company_ok=company_access(request.company, user))



def file_query(user=None):
    from asoud_erp.services.directive_access import file_clause
    user = user or frappe.session.user
    manager = bool(certificate_access.MANAGER_ROLES & set(frappe.get_roles(user)))
    certificate = "" if manager else (
        " AND (COALESCE(`tabFile`.`attached_to_doctype`, '') != 'ASOUD Workflow Request'"
        " OR COALESCE(`tabFile`.`attached_to_field`, '') != '" + certificate_access.FIELD + "'"
        " OR `tabFile`.`attached_to_name` IN (SELECT `name` FROM `tabASOUD Workflow Request` WHERE `owner` = "
        + frappe.db.escape(user) + "))")
    return ("(COALESCE(`tabFile`.`attached_to_doctype`, '') != 'ASOUD Workflow Request'"
            " OR `tabFile`.`attached_to_name` IN (SELECT `name` FROM `tabASOUD Workflow Request` WHERE "
            + request_query(user) + ")) AND (" + file_clause(user) + ")" + certificate)



def workflow_record_permission(doc, user=None, permission_type=None):
    from asoud_erp.services.directive_access import workflow_permission
    result = workflow_permission(doc, user, permission_type)
    if result is not None:
        return result
    instance = doc if doc.doctype == "ASOUD Workflow Instance" else frappe.get_doc(
        "ASOUD Workflow Instance", doc.workflow_instance)
    if instance.reference_doctype == 'ASOUD Form Entry':
        from asoud_erp.services.workflow_submission_source import instance_permission

        return instance_permission(instance, user, permission_type)
    if instance.reference_doctype and instance.reference_doctype not in (
            "ASOUD Workflow Request", "ASOUD Form Entry"):
        # A standard ERPNext reference document (e.g. Purchase Order): a task
        # attachment on it is readable exactly when the user may read the document.
        if not instance.reference_name:
            return False
        return bool(frappe.has_permission(instance.reference_doctype, "read",
                                          instance.reference_name, user=user))
    if instance.reference_doctype != "ASOUD Workflow Request":
        return None
    return request_permission(frappe.get_doc("ASOUD Workflow Request", instance.reference_name),
                              user=user, permission_type=permission_type)


def instance_query(user=None):
    from asoud_erp.services.directive_access import instance_clause
    from asoud_erp.services.workflow_submission_source import instance_clause as submitted_clause
    return ("(COALESCE(`tabASOUD Workflow Instance`.`reference_doctype`, '') != 'ASOUD Workflow Request'"
        " OR `tabASOUD Workflow Instance`.`reference_name` IN (SELECT `name` FROM `tabASOUD Workflow Request` WHERE "
        + request_query(user) + ")) AND (" + instance_clause(user) + ") AND (" + submitted_clause(user) + ")")


def task_query(user=None):
    from asoud_erp.services.directive_access import task_clause
    return "`tabASOUD Workflow Task`.`workflow_instance` IN (SELECT `name` FROM `tabASOUD Workflow Instance` WHERE " + instance_query(user) + ") AND (" + task_clause(user) + ")"


def activity_query(user=None):
    user = user or frappe.session.user
    return ("`tabASOUD Workflow Activity`.`workflow_instance` IN (SELECT `name` FROM `tabASOUD Workflow Instance` WHERE " + instance_query(user) + ") AND ("
        "`tabASOUD Workflow Activity`.workflow_instance NOT IN (SELECT workflow_instance FROM `tabASOUD Internal Communication` WHERE communication_type='Directive' AND workflow_instance IS NOT NULL) OR "
        "`tabASOUD Workflow Activity`.actor=" + frappe.db.escape(user) + " OR "
        "`tabASOUD Workflow Activity`.workflow_instance IN (SELECT workflow_instance FROM `tabASOUD Internal Communication` WHERE sender=" + frappe.db.escape(user) + "))")
