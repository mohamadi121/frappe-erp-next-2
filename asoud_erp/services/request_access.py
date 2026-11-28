import frappe

from asoud_erp.services import certificate_access
from asoud_erp.services import request_access_policy as policy


def company_access(company, user=None):
    user = user or frappe.session.user
    if user == "Guest" or not company:
        return False
    if user == 'Administrator':
        return True
    # Native creation records an explicit owner. This authorises the creator's
    # own office, not every office merely because he holds System Manager.
    if frappe.db.get_value('Company', company, 'owner') == user:
        return True
    conf = getattr(frappe, "conf", None) or {}
    if user == conf.get("asoud_workflow_service_user"):
        from asoud_erp.services.automatic_action_metadata import service_user

        # service_user() asks Frappe for native Company read permission, which runs the
        # office permission hook, which asks company_access() again. The nested ask is
        # answered from the native check alone; the outer call still decides.
        checking = frappe.flags.setdefault("asoud_service_company_check", set())
        if company in checking:
            return True
        checking.add(company)
        try:
            return service_user(company) == user
        except frappe.PermissionError:
            return False
        finally:
            checking.discard(company)
    roles = set(frappe.get_roles(user))
    # An account-only first HR lead has no Employee yet. Native Company User
    # Permission is its explicit scope, not membership in every company.
    if "HR Manager" in roles and frappe.db.exists("User Permission", {
        "user": user, "allow": "Company", "for_value": company, "apply_to_all_doctypes": 1
    }):
        return True
    if frappe.db.exists("ASOUD Office Role Assignment", {"user": user, "company": company}):
        return True
    if frappe.db.exists('User Permission', {'user': user, 'allow': 'Company', 'for_value': company,
            'apply_to_all_doctypes': 1}):
        return True
    # A manager (e.g. an HR Manager, who has no Company read right in a standard install) who is
    # an active employee of this very office belongs to it, exactly like any other employee.
    return bool(frappe.db.exists("Employee", {"user_id": user, "company": company, "status": "Active"}))


def require_company(company):
    if not company_access(company):
        frappe.throw("شما به اطلاعات این شرکت دسترسی ندارید.", frappe.PermissionError,
                     title="COMPANY_ACCESS_DENIED")


#: Activity actions that are a decision the user made on a task. Claiming a shared task,
#: being assigned, saving a draft, escalation and system actions are not decisions (PA-055 P5).
DECISION_ACTIONS = ("Approve", "Reject", "Return", "Complete", "Follow Up", "Blocked",
                    "Reassigned", "Resubmitted")


def _form_stage_of(doc):
    """The name of the request's own form stage (the user task right after Start), or None.

    Completing this stage is the requester submitting the request, not an assignee decision.
    Imported locally to avoid a circular import at module load (``workflow_request`` imports
    this module).
    """
    definition = doc.get("workflow_definition")
    if not definition:
        return None
    from asoud_erp.api.v1.workflow_request import form_stage_name

    return form_stage_name(definition)


def request_level(doc, user=None):
    """The approved access level (FULL/MASKED/NONE) of ``user`` for this request (PA-055).

    The office boundary is enforced here, not only in ``request_permission``: a user without
    company access to the request's company is NONE, even if they are the owner or hold an
    Open task (the service-user path in ``request_permission`` is unchanged).
    """
    user = user or frappe.session.user
    if not company_access(doc.company, user):
        return policy.NONE
    instance = doc.get("workflow_instance")
    # The requester's own submission (completing the request's form stage as the submitter)
    # is not an assignee decision (PA-055 P1 vs P3). Only that submission is excluded: a
    # decision on the same stage by another user still counts as acting. ``started_by`` is
    # the stable "who submitted" marker (``doc.owner`` can move, e.g. in the doctype test).
    form_stage = _form_stage_of(doc)
    started_by = frappe.db.get_value("ASOUD Workflow Instance", instance, "started_by") if instance else None

    def is_submission(stage):
        return policy.is_submission(user, started_by, stage, form_stage)

    task_rows = []
    if instance:
        task_rows = [{"status": row.status,
                      "acted": row.status == "Completed" and not is_submission(row.workflow_stage)}
                     for row in frappe.get_all("ASOUD Workflow Task",
                                               filters={"workflow_instance": instance,
                                                        "assigned_to": user},
                                               fields=["status", "workflow_stage"], limit_page_length=0)]
    # Acting = a decision activity the user made, except their own form submission (a mere
    # Claim of a shared task is not one either). Filtered in Python so a NULL stage (e.g. a
    # Reassigned row) is not dropped by a SQL ``!=`` comparison.
    acted = False
    if instance:
        activities = frappe.get_all("ASOUD Workflow Activity",
            filters={"workflow_instance": instance, "actor": user,
                     "action": ["in", list(DECISION_ACTIONS)]},
            fields=["workflow_stage"], limit_page_length=0)
        acted = any(not is_submission(row.workflow_stage) for row in activities)
    # company_access is already guaranteed above, so only the role matters here.
    privileged = bool({"System Manager", "HR Manager"}.intersection(frappe.get_roles(user)))
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



def _workflow_read_base(doc, user, permission_type):
    """The shared task/instance/activity read rule (PA-055).

    Returns ``(decision, request)`` where ``decision`` is the answer for non-request
    instances (a bool, or None to delegate to native permissions) and ``request`` is the
    request doc when the instance references one (else None).
    """
    from asoud_erp.services.directive_access import workflow_permission

    result = workflow_permission(doc, user, permission_type)
    if result is not None:
        return result, None
    instance = doc if doc.doctype == "ASOUD Workflow Instance" else frappe.get_doc(
        "ASOUD Workflow Instance", doc.workflow_instance)
    if instance.reference_doctype == 'ASOUD Form Entry':
        from asoud_erp.services.workflow_submission_source import instance_permission

        return instance_permission(instance, user, permission_type), None
    if instance.reference_doctype and instance.reference_doctype not in (
            "ASOUD Workflow Request", "ASOUD Form Entry"):
        # A standard ERPNext reference document (e.g. Purchase Order): a task
        # attachment on it is readable exactly when the user may read the document.
        if not instance.reference_name:
            return False, None
        return bool(frappe.has_permission(instance.reference_doctype, "read",
                                          instance.reference_name, user=user)), None
    if instance.reference_doctype != "ASOUD Workflow Request":
        return None, None
    return None, frappe.get_doc("ASOUD Workflow Request", instance.reference_name)


def workflow_read_allowed(doc, user=None, permission_type=None):
    """Whether the masked whitelisted endpoints may show a task/instance/activity (PA-055).

    For a request instance this is FULL or MASKED: a previous assignee who acted (MASKED)
    reads their own task and the instance's history with confidential values masked. NONE is
    denied. This is the gate for the whitelisted runtime endpoints, which mask the output; it
    is deliberately looser than ``workflow_record_permission`` (the raw REST ``has_permission``
    hook), which stays FULL-only so a MASKED viewer cannot read the form task's response_json
    or the request's values_json through REST.
    """
    user = user or frappe.session.user
    decision, request = _workflow_read_base(doc, user, permission_type)
    if request is None:
        return decision
    conf = getattr(frappe, "conf", None) or {}
    if user == conf.get("asoud_workflow_service_user"):
        return None if company_access(request.company, user) else False
    if permission_type not in (None, "read", "select"):
        return False
    return request_level(request, user) in (policy.FULL, policy.MASKED)


def workflow_record_permission(doc, user=None, permission_type=None):
    """Raw REST ``has_permission`` for a task/instance/activity (PA-055).

    For a request instance this is FULL-only: a MASKED viewer must not read the form task's
    response_json or the request's values_json through REST. A MASKED previous assignee reads
    their own task and the instance's history through the masked whitelisted endpoints, which
    use ``workflow_read_allowed`` (via ``_assert_generic_access``), not this hook.
    """
    user = user or frappe.session.user
    decision, request = _workflow_read_base(doc, user, permission_type)
    if request is None:
        return decision
    return request_permission(request, user=user, permission_type=permission_type)


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
