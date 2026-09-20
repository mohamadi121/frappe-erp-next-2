import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.personnel_contract import (
    FINANCIAL_FIELDS,
    PERSONAL_FIELDS,
    validate_record,
)


def _manager():
    return bool({"System Manager", "HR Manager"}.intersection(frappe.get_roles()))


def _company(company):
    if frappe.session.user == "Guest":
        frappe.throw("Sign in required", frappe.PermissionError)
    if not frappe.get_list("Company", filters={"name": company}, pluck="name"):
        frappe.throw("Company access denied", frappe.PermissionError)


def _person(name, write=False):
    doc = frappe.get_doc("ASOUD Party Profile", name, for_update=write)
    _company(doc.company)
    if "Employee" not in json.loads(doc.roles_text or "[]"):
        frappe.throw("Not a personnel profile")
    if not _manager():
        if write or not doc.employee or frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user:
            frappe.throw("Personnel access denied", frappe.PermissionError)
    return doc


def _row(doc, include_financial=False):
    row = {"id": doc.name, "employee_code": str(doc.get("employee") or doc.name), "company": doc.company, "disabled": bool(doc.disabled),
            "photo_record": frappe.db.get_value("ASOUD Personnel Record", {"party": doc.name, "company": doc.company, "kind": "photo"}, "name", order_by="creation desc"),
            **{field: str(doc.get(field) or "") for field in PERSONAL_FIELDS}}
    if include_financial:
        row.update({field: str(doc.get(field) or "") for field in FINANCIAL_FIELDS})
        try:
            row["employee_roles"] = json.loads(doc.get("employee_roles") or "[]")
        except (TypeError, ValueError):
            row["employee_roles"] = []
        try:
            row["access_permissions"] = json.loads(doc.get("access_permissions") or "{}")
        except (TypeError, ValueError):
            row["access_permissions"] = {}
    from asoud_erp.services.personnel_employee import shared_values

    row.update(shared_values(doc))
    if doc.get("employee"):
        image = frappe.db.get_value("Employee", doc.employee, "image")
        photo = frappe.db.get_value("File", {"attached_to_doctype": "Employee",
            "attached_to_name": doc.employee, "file_url": image, "is_private": 1}, "name") if image else None
        if photo:
            row["photo_record"] = f"native:File:{photo}"
    return row


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
    from asoud_erp.services.personnel_employee import profile_revision
    from asoud_erp.services.personnel_native import external_records, read_record

    doc = _person(name)
    records = []
    linked = set()
    for record_name in frappe.get_all("ASOUD Personnel Record", filters={"party": name, "company": doc.company},
                                      pluck="name", order_by="record_date desc, creation desc"):
        record = frappe.get_doc("ASOUD Personnel Record", record_name)
        if record.native_name:
            linked.add((record.native_doctype, record.native_name))
            if record.native_secondary:
                linked.add(("Employee Checkin", record.native_secondary))
        data = read_record(record, doc, include_file=False)
        records.append({"name": record.name, "kind": record.kind, "title": data["title"],
                        "record_date": data["date"], "legacy": data.get("_legacy", False)})
    records.extend(external_records(doc, linked))
    records.sort(key=lambda row: str(row["record_date"]), reverse=True)
    return success({"profile": _row(doc, include_financial=_manager()), "records": records,
                    "can_edit": _manager(), "revision": profile_revision(doc)})


@frappe.whitelist()
def get_profile_options(name):
    from asoud_erp.services.personnel_employee import profile_options

    return success(profile_options(_person(name, write=True).company))


@frappe.whitelist()
def get_record_options(name):
    from asoud_erp.services.personnel_native import options

    return success(options(_person(name, write=True)))


def _lock_person(name):
    frappe.db.sql("select name from `tabASOUD Party Profile` where name=%s for update", (name,))
    return _person(name, write=True)


def _request(request_id):
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
        frappe.throw("Invalid request ID")


def _receipt(person, request_id, action, digest):
    existing = frappe.db.get_value("ASOUD Personnel Operation", {"request_id": request_id},
                                   ["party", "action", "fingerprint"], as_dict=True, for_update=True)
    if existing:
        if existing.party != person.name or existing.action != action or existing.fingerprint != digest:
            frappe.throw("Request ID conflict")
        return True
    return False


def _save_receipt(person, request_id, action, digest):
    frappe.get_doc({"doctype": "ASOUD Personnel Operation", "party": person.name,
                    "request_id": request_id, "action": action, "fingerprint": digest}).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def update_personnel(name, values, revision, request_id=None):
    # Reject unauthorized fields before acquiring locks or consulting receipts.
    person = _person(name, write=True)
    data = json.loads(values) if isinstance(values, str) else values
    allowed = PERSONAL_FIELDS | (FINANCIAL_FIELDS if _manager() else set())
    if not isinstance(data, dict) or set(data) - allowed:
        frappe.throw("Only authorized HR profile fields can be edited")
    from asoud_erp.services.personnel_contract import validate_financial

    validate_financial(data)
    _request(request_id)
    # Existing queued requests may have a receipt from the old implementation.
    legacy = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id},
                                 ["party", "payload"], as_dict=True)
    old_fingerprint = json.dumps({"values": data, "revision": revision}, sort_keys=True, ensure_ascii=False)
    if legacy:
        if legacy.party != name or json.loads(legacy.payload).get("_update") != old_fingerprint:
            frappe.throw("Request ID conflict")
        return get_personnel(name)
    from asoud_erp.services.personnel_employee import (
        employee_for,
        profile_revision,
        shared_values,
        write_shared,
    )
    from asoud_erp.services.personnel_native import fingerprint

    person = _lock_person(name)
    digest = fingerprint({"values": data, "revision": revision})
    if _receipt(person, request_id, "profile", digest):
        return get_personnel(name)
    if person.employee:
        employee_for(person, lock=True)
    if profile_revision(person, lock=True) != revision:
        frappe.throw("Profile changed; reload before saving", frappe.TimestampMismatchError)
    if "display_name" in data and not str(data["display_name"] or "").strip():
        frappe.throw("Name is required")
    if person.employee:
        write_shared(person, data)
    for key, value in data.items():
        person.set(key, value if value not in (None, "") else None)
    for key, value in shared_values(person).items():
        person.set(key, value or None)
    person.save(ignore_permissions=True)
    # Native Version handles document changes; the receipt contains no HR data.
    _save_receipt(person, request_id, "profile", digest)
    return get_personnel(name)


@frappe.whitelist(methods=["POST"])
def add_record(name, payload, request_id):
    from asoud_erp.services.personnel_native import create_native, fingerprint, link_record

    _person(name, write=True)
    data = validate_record(json.loads(payload) if isinstance(payload, str) else payload)
    _request(request_id)
    person = _lock_person(name)
    digest = fingerprint(data)
    existing = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id},
                                   ["name", "party", "payload", "request_fingerprint"], as_dict=True, for_update=True)
    if existing:
        previous = existing.request_fingerprint or fingerprint(json.loads(existing.payload))
        if existing.party != name or previous != digest:
            frappe.throw("Request ID conflict")
        return success({"id": existing.name})
    if frappe.db.exists("ASOUD Personnel Operation", {"request_id": request_id}):
        frappe.throw("Request ID conflict")
    native, secondary = create_native(person, data)
    doc = frappe.get_doc({"doctype": "ASOUD Personnel Record", "company": person.company, "party": name,
                          "kind": data["kind"], "payload": "{}", "request_id": request_id,
                          "request_fingerprint": digest})
    link_record(doc, native, secondary, data)
    doc.insert(ignore_permissions=True)
    return success({"id": doc.name})


@frappe.whitelist()
def get_record(name):
    from asoud_erp.services.personnel_native import external_owner, read_external, read_record

    if name.startswith("native:"):
        native, employee = external_owner(name)
        company = frappe.db.get_value("Employee", employee, "company")
        profile = frappe.db.get_value("ASOUD Party Profile", {"employee": employee, "company": company}, "name")
        if not profile:
            frappe.throw("Employee has no linked personnel profile", frappe.PermissionError)
        person = _person(profile)
        if native.doctype in {"Appraisal", "Attendance"} and native.company != person.company:
            frappe.throw("Company mismatch", frappe.PermissionError)
        return success(read_external(native))
    doc = frappe.get_doc("ASOUD Personnel Record", name)
    person = _person(doc.party)
    if person.company != doc.company:
        frappe.throw("Company mismatch", frappe.PermissionError)
    return success(read_record(doc, person, manager=_manager()))


@frappe.whitelist(methods=["POST"])
def update_record(name, record_name, payload, revision, request_id):
    from asoud_erp.services.personnel_native import fingerprint, update_native

    _person(name, write=True)
    person = _lock_person(name)
    frappe.db.sql("select name from `tabASOUD Personnel Record` where name=%s for update", (record_name,))
    doc = frappe.get_doc("ASOUD Personnel Record", record_name, for_update=True)
    if doc.party != name or doc.company != person.company:
        frappe.throw("Record does not belong to this person", frappe.PermissionError)
    data = validate_record(json.loads(payload) if isinstance(payload, str) else payload)
    if data["kind"] != doc.kind:
        frappe.throw("Record kind cannot be changed")
    _request(request_id)
    digest = fingerprint({"record": record_name, "revision": revision, "payload": data})
    legacy = frappe.db.get_value("ASOUD Personnel Record", {"request_id": request_id},
                                 ["party", "payload"], as_dict=True, for_update=True)
    if legacy:
        old_fingerprint = json.dumps({"record": record_name, "revision": revision, "payload": data},
                                     sort_keys=True, ensure_ascii=False)
        if legacy.party != name or json.loads(legacy.payload).get("_record_update") != old_fingerprint:
            frappe.throw("Request ID conflict")
        return get_record(record_name)
    if _receipt(person, request_id, "record", digest):
        return get_record(record_name)
    if not doc.get("native_name"):
        frappe.throw("Legacy records are read-only until migration to HRMS is complete")
    update_native(doc, person, data, revision)
    _save_receipt(person, request_id, "record", digest)
    return get_record(record_name)
