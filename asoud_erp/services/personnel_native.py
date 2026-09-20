"""Translate the mobile contract to native HRMS/Frappe documents.

ASOUD Personnel Record is a compatibility reference and presentation metadata.
Times, scores and file contents are read from the native document on every read.
Legacy JSON is retained for explicit migration, never silently reinterpreted.
Callers must authorize the party before using this internal service.
"""
import base64
import hashlib
import html
import json
from pathlib import PurePosixPath

import frappe
from frappe.utils import get_datetime, strip_html

from asoud_erp.services.personnel_employee import EMPLOYEE_FIELDS, employee_for

NATIVE_TYPES = {"attendance": "Employee Checkin", "evaluation": "Appraisal",
                "photo": "File", "document": "File", "history": "Comment"}

EXTERNAL_TYPES = {"Employee Checkin": "attendance", "Attendance": "attendance",
                  "Appraisal": "evaluation", "File": "document", "Comment": "history", "Version": "history"}


def external_id(doctype, name):
    return f"native:{doctype}:{name}"


def external_owner(identifier):
    _, doctype, name = identifier.split(":", 2)
    if doctype not in EXTERNAL_TYPES:
        frappe.throw("Unsupported personnel record")
    native = frappe.get_doc(doctype, name)
    if doctype == "File":
        employee = native.attached_to_name if native.attached_to_doctype == "Employee" else None
    elif doctype == "Comment":
        employee = native.reference_name if native.reference_doctype == "Employee" else None
    elif doctype == "Version":
        employee = native.docname if native.ref_doctype == "Employee" else None
    else:
        employee = native.employee
    if not employee:
        frappe.throw("Record is not attached to an Employee", frappe.PermissionError)
    return native, employee


def read_external(native, include_file=True):
    kind = EXTERNAL_TYPES[native.doctype]
    data = {"kind": kind, "title": native.name, "date": str(native.creation)[:10], "notes": "",
            "_id": external_id(native.doctype, native.name), "_revision": str(native.modified),
            "_can_edit": False, "_native_doctype": native.doctype, "_native_name": native.name}
    if native.doctype == "Employee Checkin":
        timestamp = get_datetime(native.time)
        data.update(date=timestamp.date().isoformat(), title=f"{native.log_type or 'Checkin'} {timestamp:%H:%M}")
    elif native.doctype == "Attendance":
        data.update(date=str(native.attendance_date), title=native.status)
    elif native.doctype == "Appraisal":
        data.update(title=native.appraisal_cycle, date=str(native.start_date),
                    score=float(native.total_score or 0) * 20, appraisal_cycle=native.appraisal_cycle)
    elif native.doctype == "Comment":
        data.update(title="یادداشت پرسنلی", notes=strip_html(native.content or ""))
    elif native.doctype == "Version":
        changes = json.loads(native.data or "{}").get("changed", [])
        fields = {field for field, *_ in changes if field in EMPLOYEE_FIELDS.values()}
        # Never expose unrelated payroll/bank fields from the raw Version JSON.
        labels = {"employee_name": "نام", "cell_number": "موبایل", "personal_email": "ایمیل",
                  "date_of_birth": "تولد", "date_of_joining": "شروع کار", "gender": "جنسیت",
                  "designation": "سمت", "department": "واحد سازمانی", "employment_type": "نوع استخدام",
                  "current_address": "آدرس"}
        data.update(title="تغییر اطلاعات پرسنلی",
                    notes="، ".join(labels[field] for field in sorted(fields)))
    else:
        data.update(title=native.file_name, filename=native.file_name,
                    kind="photo" if native.attached_to_field == "image" else "document")
        if include_file:
            if not native.is_private or not str(native.file_url).startswith("/private/files/"):
                frappe.throw("Personnel attachments must be stored as private local files")
            content = native.get_content()
            if isinstance(content, str):
                content = content.encode()
            if len(content) > 5 * 1024 * 1024:
                frappe.throw("Attachment exceeds the mobile download limit")
            data["file"] = base64.b64encode(content).decode()
    return data


def external_records(person, linked):
    if not person.get("employee"):
        return []
    employee = employee_for(person)
    rows = []
    for doctype in EXTERNAL_TYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        if doctype == "File":
            filters = {"attached_to_doctype": "Employee", "attached_to_name": employee.name, "is_private": 1}
        elif doctype == "Comment":
            filters = {"reference_doctype": "Employee", "reference_name": employee.name, "comment_type": "Comment"}
        elif doctype == "Version":
            filters = {"ref_doctype": "Employee", "docname": employee.name}
        else:
            filters = {"employee": employee.name}
            if doctype in {"Attendance", "Appraisal"}:
                filters.update(company=person.company, docstatus=["!=", 2])
        for name in frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0):
            if (doctype, name) in linked:
                continue
            data = read_external(frappe.get_doc(doctype, name), include_file=False)
            rows.append({"name": data["_id"], "kind": data["kind"],
                         "title": data["title"], "record_date": data["date"]})
    return rows


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_hrms():
    if "hrms" not in frappe.get_installed_apps():
        frappe.throw("Install HRMS version-15 and migrate the site before recording HR transactions")


def evaluation_context(person, cycle_name):
    require_hrms()
    if not cycle_name:
        frappe.throw("Select an appraisal cycle configured for this employee")
    cycle = frappe.get_doc("Appraisal Cycle", cycle_name)
    if cycle.company != person.company or cycle.status == "Completed":
        frappe.throw("Appraisal cycle is unavailable for this company")
    if cycle.kra_evaluation_method != "Manual Rating":
        frappe.throw("Use HRMS to evaluate cycles based on goals")
    assignments = [row for row in cycle.appraisees if row.employee == person.employee]
    if len(assignments) != 1 or not assignments[0].appraisal_template:
        frappe.throw("Assign an appraisal template to this employee in the selected cycle")
    template = frappe.get_doc("Appraisal Template", assignments[0].appraisal_template)
    if (len(template.goals) != 1 or float(template.goals[0].per_weightage) != 100
            or template.rating_criteria):
        frappe.throw("This appraisal template has multiple criteria; complete it in HRMS")
    return cycle, template


def options(person):
    employee_for(person)
    require_hrms()
    cycles = []
    for name in frappe.get_all("Appraisal Cycle", filters={"company": person.company,
            "status": ["!=", "Completed"], "kra_evaluation_method": "Manual Rating"}, pluck="name"):
        cycle = frappe.get_doc("Appraisal Cycle", name)
        rows = [r for r in cycle.appraisees if r.employee == person.employee and r.appraisal_template]
        if len(rows) != 1:
            continue
        template = frappe.get_doc("Appraisal Template", rows[0].appraisal_template)
        if len(template.goals) == 1 and float(template.goals[0].per_weightage) == 100 and not template.rating_criteria:
            cycles.append({"name": name, "template": template.name,
                           "start_date": str(cycle.start_date), "end_date": str(cycle.end_date)})
    return {"appraisal_cycles": cycles}


def create_native(person, data):
    employee = employee_for(person, lock=True)
    kind = data["kind"]
    secondary = None
    if kind == "attendance":
        require_hrms()
        docs = []
        for field, log_type in (("start", "IN"), ("end", "OUT")):
            docs.append(frappe.get_doc({"doctype": "Employee Checkin", "employee": employee.name,
                "time": f"{data['date']} {data[field]}", "log_type": log_type}).insert(ignore_permissions=True))
        native, secondary = docs[0], docs[1].name
    elif kind == "evaluation":
        cycle, template = evaluation_context(person, data.get("appraisal_cycle"))
        native = frappe.get_doc({"doctype": "Appraisal", "employee": employee.name,
            "company": employee.company, "appraisal_cycle": cycle.name,
            "appraisal_template": template.name, "start_date": cycle.start_date,
            "end_date": cycle.end_date, "rate_goals_manually": 1})
        native.set_kras_and_rating_criteria()
        native.goals[0].score = data["score"] / 20
        native.insert(ignore_permissions=True)
    elif kind in {"photo", "document"}:
        raw = base64.b64decode(data["file"], validate=True)
        suffix = ".pdf" if raw.startswith(b"%PDF-") else ".png" if raw.startswith(b"\x89PNG") else ".jpg"
        filename = PurePosixPath(str(data.get("filename") or "attachment").replace("\\", "/")).name
        # Force the validated content type, including for misleading supplied extensions.
        filename = PurePosixPath(filename).stem + suffix
        native = frappe.get_doc({"doctype": "File", "file_name": filename,
            "content": raw, "is_private": 1, "attached_to_doctype": "Employee",
            "attached_to_name": employee.name,
            "attached_to_field": "image" if kind == "photo" else None}).insert(ignore_permissions=True)
        if kind == "photo":
            employee.image = native.file_url
            employee.save(ignore_permissions=True)
    else:
        native = frappe.get_doc({"doctype": "Comment", "comment_type": "Comment",
            "reference_doctype": "Employee", "reference_name": employee.name,
            "content": html.escape(data.get("notes") or data["title"]).replace("\n", "<br>")
        }).insert(ignore_permissions=True)
    return native, secondary


def link_record(doc, native, secondary, data):
    doc.native_doctype = native.doctype
    doc.native_name = native.name
    doc.native_secondary = secondary
    doc.title = data["title"]
    doc.record_date = data["date"]
    # Display-only annotations have no equivalent on a Checkin or File.
    doc.notes = data.get("notes", "") if data["kind"] != "history" else ""


def native_documents(doc, person, lock=False):
    employee = employee_for(person)
    if doc.native_doctype != NATIVE_TYPES.get(doc.kind):
        frappe.throw("Invalid native record reference")
    native = frappe.get_doc(doc.native_doctype, doc.native_name, for_update=lock)
    docs = [native]
    if doc.kind == "attendance":
        if not doc.native_secondary:
            frappe.throw("Missing departure checkin")
        docs.append(frappe.get_doc("Employee Checkin", doc.native_secondary, for_update=lock))
    for item in docs:
        if item.doctype == "File":
            valid = item.attached_to_doctype == "Employee" and item.attached_to_name == employee.name
        elif item.doctype == "Comment":
            valid = item.reference_doctype == "Employee" and item.reference_name == employee.name
        else:
            valid = item.employee == employee.name
            if item.doctype == "Appraisal":
                valid = valid and item.company == employee.company
        if not valid:
            frappe.throw("Native record does not belong to this employee", frappe.PermissionError)
    return docs


def revision(doc, docs):
    return fingerprint([str(doc.modified), *[[d.doctype, d.name, str(d.modified)] for d in docs]])


def editable(doc, docs):
    if doc.kind == "attendance":
        start, end = (get_datetime(d.time) for d in docs)
        return (not any(d.attendance for d in docs) and start.date() == end.date()
                and start < end and docs[0].log_type == "IN" and docs[1].log_type == "OUT")
    if doc.kind == "evaluation":
        native = docs[0]
        return (native.docstatus == 0 and native.rate_goals_manually and len(native.goals) == 1
                and float(native.goals[0].per_weightage) == 100 and not native.self_ratings
                and frappe.db.get_value("Appraisal Cycle", native.appraisal_cycle, "status") != "Completed")
    return doc.kind in {"document", "photo", "history"}


def read_record(doc, person, manager=False, include_file=True):
    if not doc.get("native_name"):
        data = json.loads(doc.payload)
        data.pop("_update", None)
        data.pop("_record_update", None)
        return {**data, "_id": doc.name, "_revision": str(doc.modified),
                "_can_edit": False, "_legacy": True}
    docs = native_documents(doc, person)
    native = docs[0]
    data = {"kind": doc.kind, "title": doc.title, "date": str(doc.record_date), "notes": doc.notes or "",
            "_id": doc.name, "_revision": revision(doc, docs), "_can_edit": bool(manager and editable(doc, docs)),
            "_native_doctype": native.doctype, "_native_name": native.name}
    if doc.kind == "attendance":
        start, end = (get_datetime(d.time) for d in docs)
        data.update(date=start.date().isoformat(), start=start.strftime("%H:%M"), end=end.strftime("%H:%M"))
        # The mobile form only represents same-day IN/OUT pairs.
        if start.date() != end.date() or start >= end or native.log_type != "IN" or docs[1].log_type != "OUT":
            data["_can_edit"] = False
    elif doc.kind == "evaluation":
        data.update(score=float(native.total_score or 0) * 20, appraisal_cycle=native.appraisal_cycle,
                    appraisal_template=native.appraisal_template)
    elif doc.kind in {"photo", "document"}:
        data["filename"] = native.file_name
        if include_file:
            if not native.is_private or not str(native.file_url).startswith("/private/files/"):
                frappe.throw("Personnel attachments must be stored as private local files")
            content = native.get_content()
            if isinstance(content, str):
                content = content.encode()
            if len(content) > 5 * 1024 * 1024:
                frappe.throw("Attachment exceeds the mobile download limit")
            data["file"] = base64.b64encode(content).decode()
    else:
        data["notes"] = strip_html(native.content or "")
    return data


def update_native(doc, person, data, expected_revision):
    docs = native_documents(doc, person, lock=True)
    if revision(doc, docs) != expected_revision:
        frappe.throw("Record changed; reload before saving", frappe.TimestampMismatchError)
    if not editable(doc, docs):
        frappe.throw("This native record cannot be edited in the simplified form")
    native = docs[0]
    if doc.kind == "attendance":
        for item, key in zip(docs, ("start", "end")):
            item.time = f"{data['date']} {data[key]}"
            item.save(ignore_permissions=True)
    elif doc.kind == "evaluation":
        if data.get("appraisal_cycle") != native.appraisal_cycle:
            frappe.throw("The appraisal cycle cannot be changed")
        evaluation_context(person, native.appraisal_cycle)
        native.goals[0].score = data["score"] / 20
        native.save(ignore_permissions=True)
    elif doc.kind in {"photo", "document"}:
        # Keep the previous File for audit/recovery; never overwrite shared bytes.
        native, _ = create_native(person, data)
    else:
        native.content = html.escape(data.get("notes") or data["title"]).replace("\n", "<br>")
        native.save(ignore_permissions=True)
    link_record(doc, native, doc.native_secondary, data)
    doc.save(ignore_permissions=True)
