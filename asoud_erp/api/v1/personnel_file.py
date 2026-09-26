"""The personnel file (پرونده پرسنلی) and the employee's own panel.

One read aggregates what HR and the employee see about a person, from the
standard records: Employee (personal, organizational, employment data,
education, work history), ERPNext Contract (party type Employee), HRMS Salary
Structure Assignment and Salary Slip, Employee Promotion and Transfer, Attendance,
Employee Checkin, leave balances, private Files and change Versions.

Access follows `api.v1.personnel`: HR Manager and System Manager see every
profile of their companies; an employee sees only their own. Bank details are
never returned (they stay on the ERPNext Employee form).
"""

import base64
import html
from pathlib import PurePosixPath

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate, strip_html

from asoud_erp.api.v1 import personnel as personnel_api
from asoud_erp.api.v1.responses import success
from asoud_erp.services.personnel_employee import EMPLOYEE_FIELD_LABELS, employee_for, profile_revision
from asoud_erp.services.personnel_file import (
    HISTORY_TITLES,
    as_date,
    contract_state,
    days_remaining,
    document_status,
    promotion_rows,
    service_length,
    sort_history,
)

ACTIVITY_LIMIT = 15
ANNOUNCEMENT_LIMIT = 5
MAX_FILE_BYTES = 5 * 1024 * 1024


def _label(doctype: str, name: str | None, field: str) -> str:
    if not name:
        return ""
    return frappe.db.get_value(doctype, name, field) or name


def _has(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _my_profile() -> str:
    employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"},
                                   ["name", "company"], as_dict=True)
    if not employee:
        frappe.throw(_("No active Employee is linked to this user"), frappe.PermissionError)
    profile = frappe.db.get_value("ASOUD Party Profile", {"employee": employee.name, "company": employee.company},
                                  "name")
    if not profile:
        frappe.throw(_("HR has not created a personnel file for you yet"), frappe.DoesNotExistError)
    return profile


def _require_manager():
    if not personnel_api._manager():
        frappe.throw(_("Only HR managers can change the personnel file"), frappe.PermissionError)


# ---------------------------------------------------------------- sections

def _header(person, employee, row, today):
    return {
        "name": row.get("display_name") or person.get("display_name") or "",
        "employee_code": employee.name if employee else None,
        "designation": row.get("job_title") or "",
        "department": row.get("department") or "",
        "department_name": _label("Department", row.get("department"), "department_name"),
        "company": person.company,
        "status": employee.status if employee else "Active",
        "photo_record": row.get("photo_record"),
        "employment_type": row.get("employment_type") or "",
        "date_of_joining": row.get("date_of_joining") or "",
        "service_length": service_length(row.get("date_of_joining"), today,
                                         employee.relieving_date if employee else None),
        "linked": bool(employee),
    }


def _personal(employee, row):
    data = {key: row.get(key) or "" for key in (
        "national_id", "father_name", "birth_date", "employee_gender", "marital_status", "blood_group",
        "mobile", "phone", "email", "company_email", "address_line", "province", "city", "postal_code")}
    data["emergency"] = {"name": row.get("emergency_contact_name") or "",
                         "phone": row.get("emergency_phone") or "",
                         "relation": row.get("emergency_relation") or ""}
    data["permanent_address"] = (employee.permanent_address or "") if employee else ""
    data["education"] = [
        {"qualification": r.qualification or "", "school": r.school_univ or "", "level": r.level or "",
         "year_of_passing": cint(r.year_of_passing) or None, "major": r.maj_opt_subj or ""}
        for r in (employee.education if employee else [])]
    # Previous salary in external history is deliberately left out.
    data["previous_work"] = [
        {"company": r.company_name or "", "designation": r.designation or "",
         "experience": r.total_experience or ""}
        for r in (employee.external_work_history if employee else [])]
    return data


def _organization(employee, row):
    if not employee:
        return {"department": row.get("department") or "", "designation": row.get("job_title") or ""}
    path, current = [], employee.department
    while current and len(path) < 10:
        values = frappe.db.get_value("Department", current, ["department_name", "parent_department", "is_group"],
                                     as_dict=True)
        if not values:
            break
        if values.department_name != "All Departments":
            path.insert(0, values.department_name)
        current = values.parent_department
    manager = None
    if employee.reports_to:
        values = frappe.db.get_value("Employee", employee.reports_to,
                                     ["name", "employee_name", "designation", "department"], as_dict=True)
        if values:
            manager = {"employee": values.name, "name": values.employee_name,
                       "designation": values.designation or "",
                       "department_name": _label("Department", values.department, "department_name")}
    return {
        "company": employee.company,
        "department": employee.department or "",
        "department_name": _label("Department", employee.department, "department_name"),
        "department_path": path,
        "designation": employee.designation or "",
        "branch": employee.branch or "",
        "employee_number": employee.employee_number or "",
        "reports_to": manager,
        "direct_reports": frappe.db.count("Employee", {"reports_to": employee.name, "status": "Active"}),
    }


def _employment(employee, row, today):
    data = {
        "employment_type": row.get("employment_type") or "",
        "date_of_joining": row.get("date_of_joining") or "",
        "status": employee.status if employee else "Active",
        "service_length": service_length(row.get("date_of_joining"), today,
                                         employee.relieving_date if employee else None),
    }
    if employee:
        data.update({
            "scheduled_confirmation_date": str(employee.scheduled_confirmation_date or ""),
            "final_confirmation_date": str(employee.final_confirmation_date or ""),
            "contract_end_date": str(employee.contract_end_date or ""),
            "notice_number_of_days": cint(employee.notice_number_of_days),
            "relieving_date": str(employee.relieving_date or ""),
            "holiday_list": employee.holiday_list or "",
            "default_shift": (employee.get("default_shift") or "") if employee.meta.has_field("default_shift") else "",
        })
    return data


def _contract_file(contract: str) -> dict | None:
    row = frappe.db.get_value("File", {"attached_to_doctype": "Contract", "attached_to_name": contract,
                                       "is_private": 1}, ["name", "file_name"], as_dict=True,
                              order_by="creation desc")
    return {"id": row.name, "filename": row.file_name} if row else None


def _contracts(employee, today):
    if not employee:
        return []
    rows = frappe.get_all("Contract", filters={"party_type": "Employee", "party_name": employee.name,
                                               "docstatus": ["<", 2]},
                          fields=["name", "start_date", "end_date", "status", "is_signed", "signed_on",
                                  "docstatus", "contract_terms"],
                          order_by="start_date desc, creation desc")
    return [{
        "name": row.name, "start_date": str(row.start_date or ""), "end_date": str(row.end_date or ""),
        "status": row.status, "is_signed": cint(row.is_signed), "signed_on": str(row.signed_on or ""),
        "docstatus": row.docstatus,
        "state": contract_state(row.start_date, row.end_date, row.docstatus, cint(row.is_signed), today),
        "days_remaining": days_remaining(row.end_date, today),
        "terms": strip_html(row.contract_terms or "")[:500],
        "file": _contract_file(row.name),
    } for row in rows]


def _salary(employee, row, manager, today):
    result = {"visible": True, "currency": None, "current": None, "history": [], "latest_slip": None,
              "legacy": None}
    if manager and not employee:
        result["legacy"] = {key: row.get(key) for key in personnel_api.FINANCIAL_FIELDS}
    if not employee or not _has("Salary Structure Assignment"):
        return result
    result["currency"] = frappe.get_cached_value("Company", employee.company, "default_currency")
    assignments = frappe.get_all("Salary Structure Assignment",
                                 filters={"employee": employee.name, "docstatus": 1},
                                 fields=["name", "salary_structure", "from_date", "base", "variable", "currency"],
                                 order_by="from_date desc")
    history = [{"name": a.name, "salary_structure": a.salary_structure, "from_date": str(a.from_date),
                "base": flt(a.base), "variable": flt(a.variable), "currency": a.currency} for a in assignments]
    result["history"] = history
    result["current"] = next((a for a in history if as_date(a["from_date"]) <= today), None)
    slip = frappe.get_all("Salary Slip", filters={"employee": employee.name, "docstatus": 1},
                          fields=["name"], order_by="start_date desc", limit_page_length=1)
    if slip:
        doc = frappe.get_doc("Salary Slip", slip[0].name)

        def lines(rows):
            return [{"component": r.salary_component, "amount": flt(r.amount)} for r in rows]

        result["latest_slip"] = {
            "name": doc.name, "start_date": str(doc.start_date), "end_date": str(doc.end_date),
            "gross_pay": flt(doc.gross_pay), "total_deduction": flt(doc.total_deduction),
            "net_pay": flt(doc.net_pay), "earnings": lines(doc.earnings), "deductions": lines(doc.deductions),
        }
    if manager and not history:
        result["legacy"] = {key: row.get(key) for key in personnel_api.FINANCIAL_FIELDS}
    return result


def _documents(person, employee, today):
    rows, linked = [], set()
    for record in frappe.get_all("ASOUD Personnel Record",
                                 filters={"party": person.name, "company": person.company, "kind": "document"},
                                 fields=["name", "title", "record_date", "document_category", "document_number",
                                         "expiry_date", "native_doctype", "native_name"],
                                 order_by="record_date desc, creation desc"):
        filename = ""
        if record.native_doctype == "File" and record.native_name:
            linked.add(record.native_name)
            filename = frappe.db.get_value("File", record.native_name, "file_name") or ""
        rows.append({"id": record.name, "title": record.title, "category": record.document_category or "",
                     "document_number": record.document_number or "", "issue_date": str(record.record_date or ""),
                     "expiry_date": str(record.expiry_date or ""),
                     "status": document_status(record.expiry_date, today), "filename": filename})
    if employee:
        image = employee.image
        for file in frappe.get_all("File", filters={"attached_to_doctype": "Employee",
                                                    "attached_to_name": employee.name, "is_private": 1},
                                   fields=["name", "file_name", "file_url", "attached_to_field", "creation"],
                                   order_by="creation desc"):
            if file.name in linked or file.attached_to_field == "image" or file.file_url == image:
                continue
            rows.append({"id": f"native:File:{file.name}", "title": file.file_name, "category": "",
                         "document_number": "", "issue_date": str(file.creation)[:10], "expiry_date": "",
                         "status": "no_expiry", "filename": file.file_name})
    return rows


def _history(employee, salary_visible, today):
    if not employee:
        return []
    events = []

    def add(kind, day, details="", order=0, reference=None):
        if day:
            events.append({"kind": kind, "title": HISTORY_TITLES[kind], "date": str(day)[:10],
                           "details": details, "order": order, "reference": reference})

    add("joining", employee.date_of_joining, " · ".join(filter(None, [
        employee.designation, _label("Department", employee.department, "department_name")])))
    for row in employee.internal_work_history:
        add("internal", row.from_date, " · ".join(filter(None, [
            row.designation, _label("Department", row.department, "department_name"), row.branch])), order=1)
    if _has("Employee Promotion"):
        for promotion in frappe.get_all("Employee Promotion", filters={"employee": employee.name, "docstatus": 1},
                                        fields=["name", "promotion_date"]):
            details = frappe.get_all("Employee Property History",
                                     filters={"parent": promotion.name, "parenttype": "Employee Promotion"},
                                     fields=["property", "current", "new"], order_by="idx asc")
            add("promotion", promotion.promotion_date,
                "، ".join(f"{d.property}: {d.current or '—'} ← {d.new}" for d in details), 2, promotion.name)
    if _has("Employee Transfer"):
        for transfer in frappe.get_all("Employee Transfer", filters={"employee": employee.name, "docstatus": 1},
                                       fields=["name", "transfer_date", "new_company"]):
            add("transfer", transfer.transfer_date, transfer.new_company or "", 2, transfer.name)
    for contract in frappe.get_all("Contract", filters={"party_type": "Employee", "party_name": employee.name,
                                                        "docstatus": 1},
                                   fields=["name", "start_date", "end_date"]):
        add("contract", contract.start_date,
            f"{contract.start_date or ''} تا {contract.end_date or 'نامحدود'}", 3, contract.name)
    if _has("Salary Structure Assignment"):
        for assignment in frappe.get_all("Salary Structure Assignment",
                                         filters={"employee": employee.name, "docstatus": 1},
                                         fields=["name", "from_date", "salary_structure", "base"]):
            details = assignment.salary_structure
            if salary_visible:
                details += f" · {flt(assignment.base):,.0f}"
            add("salary", assignment.from_date, details, 4, assignment.name)
    add("relieving", employee.relieving_date, order=5)
    return [{key: value for key, value in row.items() if key != "order"} for row in sort_history(events)]


def _attendance(employee, today):
    if not employee or not _has("Attendance"):
        return None
    start = get_first_day(today)
    rows = frappe.get_all("Attendance", filters={"employee": employee.name, "docstatus": 1,
                                                 "attendance_date": ["between", [start, today]]},
                          fields=["status", "late_entry", "early_exit"])
    counts: dict = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    last = frappe.get_all("Employee Checkin", filters={"employee": employee.name}, fields=["time", "log_type"],
                          order_by="time desc", limit_page_length=1) if _has("Employee Checkin") else []
    return {
        "from_date": str(start), "to_date": str(today), "by_status": counts,
        "present": counts.get("Present", 0) + counts.get("Work From Home", 0),
        "absent": counts.get("Absent", 0), "on_leave": counts.get("On Leave", 0),
        "half_day": counts.get("Half Day", 0),
        "late_entries": sum(1 for row in rows if row.late_entry),
        "early_exits": sum(1 for row in rows if row.early_exit),
        "last_checkin": {"time": str(last[0].time), "log_type": last[0].log_type} if last else None,
    }


def _leave(employee, today):
    if not employee or not _has("Leave Application"):
        return []
    from hrms.hr.doctype.leave_application.leave_application import get_leave_details

    try:
        details = get_leave_details(employee.name, today)
    except frappe.ValidationError:
        return []
    return [{"leave_type": leave_type, **values}
            for leave_type, values in (details.get("leave_allocation") or {}).items()]


RECORD_ACTIVITY = {"document": "ثبت مدرک", "photo": "تغییر تصویر", "attendance": "ثبت حضور",
                   "evaluation": "ثبت ارزیابی", "history": "یادداشت پرسنلی"}


def _activity(person, employee):
    items = []

    def by(user):
        return frappe.utils.get_fullname(user) if user else ""

    if employee:
        for version in frappe.get_all("Version", filters={"ref_doctype": "Employee", "docname": employee.name},
                                      fields=["data", "creation", "owner"], order_by="creation desc",
                                      limit_page_length=ACTIVITY_LIMIT):
            changed = frappe.parse_json(version.data or "{}").get("changed", [])
            labels = sorted({EMPLOYEE_FIELD_LABELS[field] for field, *_ in changed
                             if field in EMPLOYEE_FIELD_LABELS})
            if labels:
                items.append({"date": str(version.creation), "title": "ویرایش اطلاعات پرسنلی",
                              "details": "، ".join(labels), "by": by(version.owner)})
        for contract in frappe.get_all("Contract", filters={"party_type": "Employee", "party_name": employee.name},
                                       fields=["name", "creation", "owner", "start_date"],
                                       order_by="creation desc", limit_page_length=ACTIVITY_LIMIT):
            items.append({"date": str(contract.creation), "title": "ثبت قرارداد",
                          "details": str(contract.start_date or ""), "by": by(contract.owner)})
    for record in frappe.get_all("ASOUD Personnel Record", filters={"party": person.name, "company": person.company},
                                 fields=["kind", "title", "creation", "owner"], order_by="creation desc",
                                 limit_page_length=ACTIVITY_LIMIT):
        items.append({"date": str(record.creation), "title": RECORD_ACTIVITY.get(record.kind, "ثبت سابقه"),
                      "details": record.title or "", "by": by(record.owner)})
    items.sort(key=lambda item: item["date"], reverse=True)
    return items[:ACTIVITY_LIMIT]


def build_file(profile_name: str) -> dict:
    person = personnel_api._person(profile_name)
    manager = personnel_api._manager()
    employee = employee_for(person) if person.get("employee") else None
    row = personnel_api._row(person, include_financial=manager)
    today = getdate()
    return {
        "profile_id": person.name,
        "can_edit": manager,
        "revision": profile_revision(person),
        "header": _header(person, employee, row, today),
        "personal": _personal(employee, row),
        "organization": _organization(employee, row),
        "employment": _employment(employee, row, today),
        "contracts": _contracts(employee, today),
        "salary": _salary(employee, row, manager, today),
        "documents": _documents(person, employee, today),
        "history": _history(employee, True, today),
        "attendance": _attendance(employee, today),
        "leave": _leave(employee, today),
        "activity": _activity(person, employee),
    }


@frappe.whitelist()
def get_personnel_file(name: str) -> dict:
    """The full personnel file of a profile (HR, or the employee themselves)."""
    return success(build_file(name))


@frappe.whitelist()
def get_my_personnel_file() -> dict:
    """The session user's own personnel file («اطلاعات من»)."""
    return success(build_file(_my_profile()))


# ---------------------------------------------------------------- HR writes

def _employee_of(profile_name: str):
    _require_manager()
    person = personnel_api._person(profile_name, write=True)
    return person, employee_for(person, lock=True)


def _attach(doctype: str, name: str, content_base64: str, filename: str | None):
    try:
        raw = base64.b64decode(content_base64 or "", validate=True)
    except (ValueError, TypeError):
        frappe.throw(_("The attachment is not valid base64"))
    if not raw or len(raw) > MAX_FILE_BYTES:
        frappe.throw(_("The attachment must be between 1 byte and 5 MB"))
    if raw.startswith(b"%PDF-"):
        suffix = ".pdf"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif raw.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    else:
        frappe.throw(_("Only PDF, PNG and JPEG attachments are accepted"))
    stem = PurePosixPath(str(filename or "contract").replace("\\", "/")).stem or "contract"
    return frappe.get_doc({"doctype": "File", "file_name": stem + suffix, "content": raw, "is_private": 1,
                           "attached_to_doctype": doctype, "attached_to_name": name}).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def save_contract(name: str, start_date: str, terms: str, end_date: str | None = None, contract: str | None = None,
                  is_signed: int = 0, file: str | None = None, filename: str | None = None,
                  submit: int = 0) -> dict:
    """Creates or edits (while draft) an ERPNext Contract with the employee as party.

    ``file`` is an optional base64 PDF/PNG/JPEG of the signed contract, stored privately.
    Submitting locks the contract; ERPNext derives its status from the signature and dates.
    """
    person, employee = _employee_of(name)
    if not (terms or "").strip():
        frappe.throw(_("Contract terms are required"))
    if contract:
        doc = frappe.get_doc("Contract", contract)
        if doc.party_type != "Employee" or doc.party_name != employee.name:
            frappe.throw(_("This contract belongs to another party"), frappe.PermissionError)
        if doc.docstatus != 0:
            frappe.throw(_("A submitted contract cannot be edited; cancel and amend it in ERPNext"))
    else:
        doc = frappe.new_doc("Contract")
        doc.update({"party_type": "Employee", "party_name": employee.name})
    doc.update({
        "start_date": getdate(start_date), "end_date": getdate(end_date) if end_date else None,
        "contract_terms": html.escape(terms.strip()).replace("\n", "<br>"),
        "is_signed": cint(is_signed), "party_full_name": employee.employee_name,
    })
    if cint(is_signed) and not doc.signee:
        doc.signee = employee.employee_name
        doc.signed_on = frappe.utils.now_datetime()
    doc.save()
    if file:
        _attach("Contract", doc.name, file, filename)
    if cint(submit):
        doc.submit()
    if doc.end_date and cint(submit):
        # Keep the Employee's own contract end date in step with the latest submitted contract.
        latest = frappe.get_all("Contract", filters={"party_type": "Employee", "party_name": employee.name,
                                                     "docstatus": 1}, pluck="end_date",
                                order_by="end_date desc", limit_page_length=1)
        if latest and latest[0] and employee.contract_end_date != latest[0]:
            frappe.db.set_value("Employee", employee.name, "contract_end_date", latest[0])
    return success(_contracts(frappe.get_doc("Employee", employee.name), getdate()))


@frappe.whitelist()
def get_contract_file(contract: str) -> dict:
    """The newest private attachment of a contract, as base64, for its HR or its employee."""
    doc = frappe.get_doc("Contract", contract)
    if doc.party_type != "Employee":
        frappe.throw(_("Not a personnel contract"), frappe.PermissionError)
    profile = frappe.db.get_value("ASOUD Party Profile", {"employee": doc.party_name}, "name")
    if not profile:
        frappe.throw(_("Employee has no personnel file"), frappe.PermissionError)
    personnel_api._person(profile)
    row = _contract_file(doc.name)
    if not row:
        frappe.throw(_("This contract has no attachment"), frappe.DoesNotExistError)
    file = frappe.get_doc("File", row["id"])
    content = file.get_content()
    if isinstance(content, str):
        content = content.encode()
    return success({"filename": file.file_name, "content_base64": base64.b64encode(content).decode()})


@frappe.whitelist(methods=["POST"])
def add_promotion(name: str, promotion_date: str, designation: str | None = None, department: str | None = None,
                  branch: str | None = None, remarks: str | None = None) -> dict:
    """Records an HRMS Employee Promotion; when it is due (today or earlier) it is
    submitted and HRMS applies the new designation/department/branch to the Employee."""
    person, employee = _employee_of(name)
    changes = {key: value for key, value in {"designation": designation, "department": department,
                                              "branch": branch}.items() if value}
    try:
        rows = promotion_rows({field: employee.get(field) for field in ("designation", "department", "branch")},
                              changes)
    except ValueError as error:
        frappe.throw(_(str(error)))
    if department and frappe.db.get_value("Department", department, "company") not in (None, employee.company):
        frappe.throw(_("The department belongs to another company"))
    doc = frappe.get_doc({"doctype": "Employee Promotion", "employee": employee.name, "company": employee.company,
                          "promotion_date": getdate(promotion_date), "promotion_details": rows})
    doc.insert()
    if remarks and remarks.strip():
        doc.add_comment("Comment", html.escape(remarks.strip()))
    if doc.promotion_date <= getdate():
        doc.submit()
    return success({"name": doc.name, "docstatus": doc.docstatus, "promotion_date": str(doc.promotion_date),
                    "changes": rows})


# ---------------------------------------------------------------- employee panel

def _announcements(limit=ANNOUNCEMENT_LIMIT):
    today = getdate()
    rows = frappe.get_all("Note", filters={"public": 1},
                          or_filters=[["expire_notification_on", ">=", today],
                                      ["expire_notification_on", "is", "not set"]],
                          fields=["name", "title", "content", "modified", "expire_notification_on"],
                          order_by="modified desc", limit_page_length=limit)
    return [{"name": row.name, "title": row.title, "summary": strip_html(row.content or "")[:280],
             "date": str(row.modified), "expires_on": str(row.expire_notification_on or "")} for row in rows]


@frappe.whitelist()
def list_announcements() -> dict:
    """Public company announcements (Frappe Note), newest first, not expired."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Sign in required"), frappe.PermissionError)
    return success(_announcements(limit=50))


@frappe.whitelist(methods=["POST"])
def create_announcement(title: str, content: str, expire_on: str | None = None) -> dict:
    """A public announcement shown on every employee's home screen (HR managers)."""
    _require_manager()
    if not 3 <= len((title or "").strip()) <= 140:
        frappe.throw(_("Title must contain 3 to 140 characters"))
    note = frappe.get_doc({"doctype": "Note", "title": title.strip(), "public": 1, "notify_on_login": 0,
                           "content": html.escape((content or "").strip()).replace("\n", "<br>"),
                           "expire_notification_on": getdate(expire_on) if expire_on else None})
    note.insert(ignore_permissions=True)
    return success(_announcements(limit=50))


@frappe.whitelist()
def get_my_home() -> dict:
    """Everything the employee's home screen shows: greeting, counts and announcements."""
    user = frappe.session.user
    employee_name = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
    if not employee_name:
        frappe.throw(_("No active Employee is linked to this user"), frappe.PermissionError)
    employee = frappe.get_doc("Employee", employee_name)
    profile = frappe.db.get_value("ASOUD Party Profile", {"employee": employee.name, "company": employee.company},
                                  "name")
    photo = None
    if profile:
        photo = personnel_api._row(frappe.get_doc("ASOUD Party Profile", profile)).get("photo_record")
    today = getdate()
    leave = _leave(employee, today)
    counts = {
        "open_requests": frappe.db.count("ASOUD Workflow Instance", {"started_by": user, "status": "Running"}),
        "open_tasks": frappe.db.count("ASOUD Workflow Task", {"assigned_to": user, "status": "Open"}),
        "unread_notifications": frappe.db.count("Notification Log", {"for_user": user, "read": 0}),
        "pending_leave_applications": frappe.db.count("Leave Application", {"employee": employee.name,
                                                                             "status": "Open", "docstatus": 0})
        if _has("Leave Application") else 0,
        "leave_remaining": flt(sum(flt(row.get("remaining_leaves")) for row in leave)),
    }
    attendance = _attendance(employee, today)
    return success({
        "profile_id": profile,
        "employee": employee.name,
        "name": employee.employee_name,
        "designation": employee.designation or "",
        "department_name": _label("Department", employee.department, "department_name"),
        "company": employee.company,
        "photo_record": photo,
        "date": str(today),
        "counts": counts,
        "last_checkin": attendance["last_checkin"] if attendance else None,
        "announcements": _announcements(),
    })
