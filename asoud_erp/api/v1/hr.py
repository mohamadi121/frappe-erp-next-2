from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.hr_contract import normalize_communication_payload, normalize_report_payload
from asoud_erp.services.request_access import require_company


def _payload(value):
    return json.loads(value) if isinstance(value, str) else dict(value or {})


def _employee_for_user(user: str | None = None):
    user = user or frappe.session.user
    name = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    if not name:
        frappe.throw(_("No active Employee is linked to this user"))
    return frappe.get_doc("Employee", name)


def _employee_row(doc) -> dict:
    party_profile = frappe.db.get_value(
        "ASOUD Party Profile", {"employee": doc.name}, "name"
    )
    return {
        "id": doc.name, "party_profile": party_profile or "", "name": doc.employee_name, "company": doc.company,
        "department": doc.department or "", "designation": doc.designation or "",
        "reports_to": doc.reports_to or "", "user_id": doc.user_id or "",
        "status": doc.status, "date_of_joining": str(doc.date_of_joining or ""),
        "image": doc.image or "", "cell_number": doc.cell_number or "",
        "personal_email": doc.personal_email or "",
    }


@frappe.whitelist()
def get_dashboard(company: str | None = None):
    employee_name = frappe.db.get_value(
        "Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
    )
    if not employee_name:
        roles = set(frappe.get_roles(frappe.session.user))
        if not roles.intersection({"System Manager", "HR Manager"}):
            frappe.throw(_("No active Employee is linked to this user"))
        selected_company = company or frappe.defaults.get_user_default("company")
        if not selected_company:
            companies = frappe.get_all("Company", limit=1, pluck="name")
            selected_company = companies[0] if companies else None
        unread = frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0})
        pending = frappe.db.count("ASOUD Workflow Task", {"assigned_to": frappe.session.user, "status": "Open"})
        received = frappe.db.count(
            "ASOUD Communication Recipient", {"user": frappe.session.user, "read_at": ["is", "not set"]}
        )
        return success({
            "manager_access": True,
            "company": selected_company,
            "pending_tasks": pending,
            "unread_notifications": unread,
            "unread_communications": received,
        })
    employee = frappe.get_doc("Employee", employee_name)
    selected_company = company or employee.company
    today_report = frappe.db.get_value("ASOUD Work Report", {"employee": employee.name, "report_date": nowdate()}, ["name", "status"], as_dict=True)
    unread = frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0})
    pending = frappe.db.count("ASOUD Workflow Task", {"assigned_to": frappe.session.user, "status": "Open"})
    received = frappe.db.count("ASOUD Communication Recipient", {"user": frappe.session.user, "read_at": ["is", "not set"]})
    return success({"employee": _employee_row(employee), "company": selected_company, "today_report": today_report, "pending_tasks": pending, "unread_notifications": unread, "unread_communications": received})


@frappe.whitelist()
def get_my_profile():
    return success(_employee_row(_employee_for_user()))


@frappe.whitelist()
def list_team(query: str | None = None):
    employee, company = _report_actor()
    roles = set(frappe.get_roles(frappe.session.user))
    filters = {"company": company, "status": "Active"}
    if not roles.intersection({"System Manager", "HR Manager", "HR User"}):
        filters["reports_to"] = employee.name
    if employee and not frappe.has_permission("Employee", ptype="read", doc=employee.name):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    rows = frappe.get_all("Employee", filters=filters, fields=["name"], limit_page_length=100)
    values = [_employee_row(frappe.get_doc("Employee", row.name)) for row in rows]
    if query:
        needle = query.strip().lower()
        values = [row for row in values if needle in row["name"].lower() or needle in row["department"].lower()]
    return success(values)


@frappe.whitelist()
def organization_tree(company: str):
    require_company(company)
    frappe.has_permission("Department", ptype="read", throw=True)
    return success(frappe.get_all("Department", filters={"company": company, "disabled": 0}, fields=["name", "department_name", "parent_department", "is_group"], order_by="lft asc", limit_page_length=500))


def _active_employee(user: str | None = None):
    user = user or frappe.session.user
    name = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    return frappe.get_doc("Employee", name) if name else None


def _report_actor(company_hint: str | None = None):
    """(employee or None, company) of the session user.

    A system administrator needs no personnel file to report: the report is then keyed by the
    login account (``reporter``) in an office the administrator can access. Everybody else must
    have an active Employee, exactly as before."""
    from asoud_erp.services.system_admin import is_system_admin

    employee = _active_employee()
    if employee:
        return employee, employee.company
    if not is_system_admin():
        frappe.throw(_("No active Employee is linked to this user"))
    company = company_hint or frappe.defaults.get_user_default("company")
    if not company:
        company = frappe.db.get_value("ASOUD Company Setup", {"office_saved": 1}, "company",
                                      order_by="creation asc")
    if not company:
        frappe.throw(_("Create the first office before sending work reports"))
    require_company(company)
    return None, company


def _report_owner_is_me(doc, user: str) -> bool:
    if doc.get("reporter"):
        return doc.reporter == user
    return bool(doc.employee) and frappe.db.get_value("Employee", doc.employee, "user_id") == user


def _review_route(employee) -> dict:
    superior = frappe.db.get_value("Employee", employee.reports_to, ["name", "employee_name", "user_id"],
                                   as_dict=True) if employee and employee.reports_to else None
    if superior:
        return {"route": "direct_manager", "superior": superior.name, "superior_name": superior.employee_name}
    return {"route": "managers_pool", "superior": None, "superior_name": None,
            "note": "مافوق مستقیمی تعریف نشده؛ گزارش را مدیر کل سیستم یا مدیر منابع انسانی بررسی می‌کند."}


@frappe.whitelist()
def list_reports(status: str | None = None, limit_start: int = 0, limit_page_length: int = 30):
    employee, _company = _report_actor()
    filters = {}
    if status:
        filters["status"] = status
    or_filters = {"reporter": frappe.session.user}
    if employee:
        or_filters["employee"] = employee.name
    return success(frappe.get_all("ASOUD Work Report", filters=filters, or_filters=or_filters, fields=["name", "report_date", "status", "total_minutes", "manager_comment", "modified"], order_by="report_date desc", limit_start=int(limit_start), limit_page_length=min(int(limit_page_length), 100)))


@frappe.whitelist(methods=["POST"])
def save_report(payload):
    data = normalize_report_payload(_payload(payload))
    employee, company = _report_actor(data.get("company"))
    name = data.get("name")
    doc = frappe.get_doc("ASOUD Work Report", name) if name else frappe.new_doc("ASOUD Work Report")
    if name and not _report_owner_is_me(doc, frappe.session.user):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if name and doc.status in ("Approved", "Archived"):
        frappe.throw(_("A reviewed report cannot be edited"), frappe.PermissionError)
    doc.company, doc.reporter = company, frappe.session.user
    doc.employee = employee.name if employee else None
    doc.report_date = getdate(data.get("report_date") or nowdate())
    doc.status = data.get("status") or "Draft"
    doc.set("activities", [])
    total = 0
    for row in data["activities"]:
        total += row["duration_minutes"]
        doc.append("activities", row)
    doc.total_minutes = total
    doc.save()
    return success({"name": doc.name, "status": doc.status, "report_date": str(doc.report_date),
                    "total_minutes": total, "review": _review_route(employee)})


@frappe.whitelist(methods=["POST"])
def review_report(report: str, action: str, comment: str | None = None):
    reviewer = _active_employee()
    doc = frappe.get_doc("ASOUD Work Report", report)
    if _report_owner_is_me(doc, frappe.session.user):
        frappe.throw(_("You cannot review your own report"), frappe.PermissionError)
    owner = frappe.get_doc("Employee", doc.employee) if doc.employee else None
    roles = set(frappe.get_roles(frappe.session.user))
    require_company(doc.company)
    direct = bool(owner and reviewer and owner.reports_to == reviewer.name)
    if not direct and not roles.intersection({"System Manager", "HR Manager"}):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    states = {"approve": "Approved", "return": "Returned", "review": "Under Review"}
    if action not in states:
        frappe.throw(_("Review action is invalid"))
    doc.status = states[action]
    doc.manager_comment = str(comment or "").strip()
    doc.save()
    return success({"name": doc.name, "status": doc.status, "manager_comment": doc.manager_comment})


@frappe.whitelist()
def list_communications(box: str = "inbox", limit_start: int = 0, limit_page_length: int = 30):
    user = frappe.session.user
    if box == "sent":
        filters = {"sender": user}
    else:
        parents = frappe.get_all("ASOUD Communication Recipient", filters={"user": user}, pluck="parent", limit_page_length=500)
        filters = {"name": ["in", parents or [""]]}
    from asoud_erp.services.directive_access import can_read
    rows = frappe.get_all("ASOUD Internal Communication", filters=filters, fields=["name", "subject", "sender", "communication_type", "priority", "confidential", "due_date", "status", "modified"], order_by="modified desc", limit_start=int(limit_start), limit_page_length=min(int(limit_page_length), 100))
    return success([r for r in rows if r.communication_type != "Directive" or can_read(frappe.get_doc("ASOUD Internal Communication",r.name))])


@frappe.whitelist(methods=["POST"])
def create_communication(payload):
    data = normalize_communication_payload(_payload(payload))
    _employee, company = _report_actor(_payload(payload).get("company"))
    doc = frappe.new_doc("ASOUD Internal Communication")
    doc.company, doc.sender = company, frappe.session.user
    for field in ("communication_type", "subject", "content", "priority", "confidential", "due_date"):
        if field in data:
            setattr(doc, field, data[field])
    doc.status = "Sent"
    for user in data["recipients"]:
        doc.append(
            "recipients",
            {"user": user, "recipient_type": "To"}
        )
    doc.insert()
    return success({"name": doc.name, "status": doc.status})


@frappe.whitelist()
def list_notifications(limit_start: int = 0, limit_page_length: int = 30):
    return success(frappe.get_all("Notification Log", filters={"for_user": frappe.session.user}, fields=["name", "subject", "email_content", "document_type", "document_name", "read", "creation"], order_by="creation desc", limit_start=int(limit_start), limit_page_length=min(int(limit_page_length), 100)))
