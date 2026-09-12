import json
from datetime import date

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.personnel_contract import PERSONAL_FIELDS, validate_record


def _manager():
    return bool({"System Manager", "HR Manager"}.intersection(frappe.get_roles()))


def _company(company):
    if frappe.session.user == "Guest":
        frappe.throw("Sign in required", frappe.PermissionError)
    if not frappe.get_list("Company", filters={"name": company}, pluck="name"):
        frappe.throw("Company access denied", frappe.PermissionError)


def _person(name, write=False):
    doc = frappe.get_doc("ASOUD Party Profile", name)
    _company(doc.company)
    if "Employee" not in json.loads(doc.roles_text or "[]"):
        frappe.throw("Not a personnel profile")
    if not _manager():
        if write or not doc.employee or frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user:
            frappe.throw("Personnel access denied", frappe.PermissionError)
    return doc


def _row(doc):
    return {"id": doc.name, "employee_code": str(doc.get("employee") or doc.name), "company": doc.company, "disabled": bool(doc.disabled),
            "photo_record": frappe.db.get_value("ASOUD Personnel Record", {"party": doc.name, "company": doc.company, "kind": "photo"}, "name", order_by="creation desc"),
            **{field: str(doc.get(field) or "") for field in PERSONAL_FIELDS}}


@frappe.whitelist()
def list_personnel(company):
    _company(company)
    filters = {"company": company, "roles_text": ["like", '%"Employee"%']}
    if not _manager():
        employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "company": company}, "name")
        if not employee:
            return success({"rows": [], "can_edit": False})
        filters["employee"] = employee
    names = frappe.get_all("ASOUD Party Profile", filters=filters, pluck="name", limit_page_length=0)
    return success({"rows": [_row(frappe.get_doc("ASOUD Party Profile", name)) for name in names], "can_edit": _manager()})


@frappe.whitelist()
def get_personnel(name):
    doc = _person(name)
    records = frappe.get_all("ASOUD Personnel Record", filters={"party": name, "company": doc.company},
                             fields=["name", "kind", "title", "record_date"], order_by="record_date desc, creation desc")
    return success({"profile": _row(doc), "records": records, "can_edit": _manager(), "revision": str(doc.modified)})


@frappe.whitelist(methods=["POST"])
def update_personnel(name, values, revision, request_id=None):
    doc = _person(name, write=True)
    data = json.loads(values) if isinstance(values, str) else values
    if not isinstance(data, dict) or set(data) - PERSONAL_FIELDS:
        frappe.throw("Only HR profile fields can be edited")
    fingerprint = json.dumps({"values": data, "revision": revision}, sort_keys=True, ensure_ascii=False)
    if request_id is not None:
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            frappe.throw("Invalid request ID")
        existing = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id},
                                       ["party", "payload"], as_dict=True)
        if existing:
            if existing.party != name or json.loads(existing.payload).get("_update") != fingerprint:
                frappe.throw("Request ID conflict")
            return get_personnel(name)
    if str(doc.modified) != revision:
        frappe.throw("Profile changed; reload before saving", frappe.TimestampMismatchError)
    for key, value in data.items():
        doc.set(key, value or None)
    if not str(doc.display_name or "").strip():
        frappe.throw("Name is required")
    if doc.employee:
        employee = frappe.get_doc("Employee", doc.employee)
        if employee.company != doc.company:
            frappe.throw("Employee company mismatch")
        mapping = {"display_name": "first_name", "mobile": "cell_number", "email": "personal_email",
                   "birth_date": "date_of_birth", "date_of_joining": "date_of_joining", "employee_gender": "gender"}
        for key, target in mapping.items():
            if key in data:
                employee.set(target, data[key])
        employee.save(ignore_permissions=True)
    # Authorization is explicitly enforced above; no financial fields are accepted.
    doc.save(ignore_permissions=True)
    audit = {"kind": "history", "title": "ویرایش اطلاعات پرسنلی", "date": date.today().isoformat(),
             "notes": "Updated fields: " + ", ".join(sorted(data)), "_update": fingerprint}
    frappe.get_doc({"doctype": "ASOUD Personnel Record", "company": doc.company, "party": name,
                    "kind": "history", "title": audit["title"], "record_date": audit["date"],
                    "payload": json.dumps(audit, ensure_ascii=False),
                    "request_id": request_id or frappe.generate_hash(length=24)}).insert(ignore_permissions=True)
    return get_personnel(name)


@frappe.whitelist(methods=["POST"])
def add_record(name, payload, request_id):
    person = _person(name, write=True)
    data = validate_record(json.loads(payload) if isinstance(payload, str) else payload)
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    existing = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id}, ["name", "party", "payload"], as_dict=True)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if existing:
        if existing.party != name or existing.payload != encoded:
            frappe.throw("Request ID conflict")
        return success({"id": existing.name})
    doc = frappe.get_doc({"doctype": "ASOUD Personnel Record", "company": person.company, "party": name,
                          "kind": data["kind"], "title": data["title"], "record_date": data["date"],
                          "payload": encoded, "request_id": request_id})
    frappe.db.savepoint("personnel_record_insert")
    try:
        doc.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # Another request may have committed the same idempotency key after our read.
        frappe.db.rollback(save_point="personnel_record_insert")
        existing = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id},
                                       ["name", "party", "payload"], as_dict=True)
        if not existing or existing.party != name or existing.payload != encoded:
            raise
        return success({"id": existing.name})
    return success({"id": doc.name})


@frappe.whitelist()
def get_record(name):
    doc = frappe.get_doc("ASOUD Personnel Record", name)
    person = _person(doc.party)
    if person.company != doc.company:
        frappe.throw("Company mismatch", frappe.PermissionError)
    payload = json.loads(doc.payload)
    editable = _manager() and not (payload.get("_update") or payload.get("_record_update"))
    payload.pop("_update", None)
    payload.pop("_record_update", None)
    payload.update({"_id": doc.name, "_revision": str(doc.modified), "_can_edit": editable})
    return success(payload)


@frappe.whitelist(methods=["POST"])
def update_record(name, record_name, payload, revision, request_id):
    person = _person(name, write=True)
    # Lock before loading the revision so concurrent edits cannot overwrite it.
    frappe.db.sql("select name from `tabASOUD Personnel Record` where name=%s for update", (record_name,))
    doc = frappe.get_doc("ASOUD Personnel Record", record_name)
    if doc.party != name or doc.company != person.company:
        frappe.throw("Record does not belong to this person", frappe.PermissionError)
    previous = json.loads(doc.payload)
    if previous.get("_update") or previous.get("_record_update"):
        frappe.throw("Automatic history entries cannot be edited", frappe.PermissionError)
    data = validate_record(json.loads(payload) if isinstance(payload, str) else payload)
    if data["kind"] != doc.kind:
        frappe.throw("Record kind cannot be changed")
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")
    fingerprint = json.dumps({"record": record_name, "revision": revision, "payload": data}, sort_keys=True, ensure_ascii=False)
    receipt = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id}, ["party", "payload"], as_dict=True)
    if receipt:
        if receipt.party != name or json.loads(receipt.payload).get("_record_update") != fingerprint:
            frappe.throw("Request ID conflict")
        return get_record(record_name)
    if str(doc.modified) != revision:
        frappe.throw("Record changed; reload before saving", frappe.TimestampMismatchError)
    doc.title = data["title"]
    doc.record_date = data["date"]
    doc.payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    doc.save(ignore_permissions=True)
    audit = {"kind": "history", "title": "ویرایش سابقه پرسنلی", "date": date.today().isoformat(),
             "notes": data["title"], "_record_update": fingerprint}
    frappe.get_doc({"doctype": "ASOUD Personnel Record", "company": person.company, "party": name,
                    "kind": "history", "title": audit["title"], "record_date": audit["date"],
                    "payload": json.dumps(audit, ensure_ascii=False), "request_id": request_id}).insert(ignore_permissions=True)
    return get_record(record_name)
