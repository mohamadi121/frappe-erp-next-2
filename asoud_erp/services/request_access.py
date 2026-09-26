import frappe


def company_access(company, user=None):
    user = user or frappe.session.user
    if user == "Guest" or not company:
        return False
    roles = set(frappe.get_roles(user))
    if not roles.intersection({"System Manager", "HR Manager", "Accounts Manager", "Accounts User"}):
        return bool(frappe.db.exists("Employee", {"user_id": user, "company": company, "status": "Active"}))
    return frappe.has_permission("Company", "read", company, user=user)


def require_company(company):
    if not company_access(company):
        frappe.throw("Company access denied", frappe.PermissionError)


def request_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    if permission_type not in (None, "read", "select"):
        return False
    if not company_access(doc.company, user):
        return False
    if doc.owner == user or {"System Manager", "HR Manager"}.intersection(frappe.get_roles(user)):
        return True
    # Stage assignees (e.g. the requester's direct manager) read the request they act on.
    return bool(doc.get("workflow_instance") and frappe.db.exists(
        "ASOUD Workflow Task", {"workflow_instance": doc.workflow_instance, "assigned_to": user}))


def request_query(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return "1=0"
    companies = frappe.get_all("Company", pluck="name")
    allowed = [company for company in companies if company_access(company, user)]
    if not allowed:
        return "1=0"
    return ("(`tabASOUD Workflow Request`.`owner` = " + frappe.db.escape(user)
        + " OR `tabASOUD Workflow Request`.`workflow_instance` IN (SELECT `workflow_instance`"
        " FROM `tabASOUD Workflow Task` WHERE `assigned_to` = " + frappe.db.escape(user) + "))"
        + " AND `tabASOUD Workflow Request`.`company` IN ("
        + ",".join(frappe.db.escape(company) for company in allowed) + ")")


def file_permission(doc, user=None, permission_type=None):
    if doc.attached_to_doctype == "ASOUD Workflow Task" and doc.attached_to_name:
        return workflow_record_permission(frappe.get_doc("ASOUD Workflow Task", doc.attached_to_name),
                                          user=user, permission_type=permission_type)
    if doc.attached_to_doctype == "ASOUD Workflow Request":
        if not doc.is_private or not doc.attached_to_name:
            return False
        return request_permission(frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name),
                                  user=user, permission_type=permission_type)
    return None



def file_query(user=None):
    return ("(COALESCE(`tabFile`.`attached_to_doctype`, '') != 'ASOUD Workflow Request'"
            " OR `tabFile`.`attached_to_name` IN (SELECT `name` FROM `tabASOUD Workflow Request` WHERE "
            + request_query(user) + "))")



def workflow_record_permission(doc, user=None, permission_type=None):
    instance = doc if doc.doctype == "ASOUD Workflow Instance" else frappe.get_doc(
        "ASOUD Workflow Instance", doc.workflow_instance)
    if instance.reference_doctype != "ASOUD Workflow Request":
        return None
    return request_permission(frappe.get_doc("ASOUD Workflow Request", instance.reference_name),
                              user=user, permission_type=permission_type)


def instance_query(user=None):
    return ("(COALESCE(`tabASOUD Workflow Instance`.`reference_doctype`, '') != 'ASOUD Workflow Request'"
        " OR `tabASOUD Workflow Instance`.`reference_name` IN (SELECT `name` FROM `tabASOUD Workflow Request` WHERE "
        + request_query(user) + "))")


def task_query(user=None):
    return "`tabASOUD Workflow Task`.`workflow_instance` IN (SELECT `name` FROM `tabASOUD Workflow Instance` WHERE " + instance_query(user) + ")"


def activity_query(user=None):
    return "`tabASOUD Workflow Activity`.`workflow_instance` IN (SELECT `name` FROM `tabASOUD Workflow Instance` WHERE " + instance_query(user) + ")"
