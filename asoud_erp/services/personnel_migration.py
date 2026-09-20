"""Explicit, resumable migration. Never run automatically in after_migrate.

bench --site SITE execute asoud_erp.services.personnel_migration.migrate_legacy_records
    --kwargs '{"company":"...","dry_run":true}'

Pass evaluation_cycles={legacy_record_name: existing_cycle_name} for appraisals.
No source rows are deleted and no Employee is created or matched by display name.
"""
import json

import frappe

from asoud_erp.services.personnel_contract import validate_record
from asoud_erp.services.personnel_employee import employee_for
from asoud_erp.services.personnel_native import (
    create_native,
    evaluation_context,
    fingerprint,
    link_record,
    require_hrms,
)


def migrate_legacy_records(company, dry_run=True, evaluation_cycles=None):
    frappe.only_for("System Manager")
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a JSON boolean")
    if not company or not frappe.db.exists("Company", company):
        raise ValueError("A valid company is required")
    evaluation_cycles = evaluation_cycles or {}
    if not isinstance(evaluation_cycles, dict):
        raise ValueError("evaluation_cycles must map record names to existing cycles")
    require_hrms()
    report = []
    names = frappe.get_all("ASOUD Personnel Record", filters={"company": company},
                           pluck="name", order_by="creation asc", limit_page_length=0)
    for name in names:
        try:
            # Same lock order as API writes; avoids migrating during an edit.
            party = frappe.db.get_value("ASOUD Personnel Record", name, "party")
            if not dry_run:
                frappe.db.sql("select name from `tabASOUD Party Profile` where name=%s for update", (party,))
                frappe.db.sql("select name from `tabASOUD Personnel Record` where name=%s for update", (name,))
            doc = frappe.get_doc("ASOUD Personnel Record", name)
            if doc.native_name:
                report.append({"name": name, "status": "already_linked"})
                continue
            raw = json.loads(doc.payload)
            if raw.get("_update") or raw.get("_record_update"):
                report.append({"name": name, "status": "audit_preserved"})
                continue
            person = frappe.get_doc("ASOUD Party Profile", party)
            if person.company != company:
                raise ValueError("Profile company mismatch")
            employee_for(person)
            data = validate_record(raw)
            if data["kind"] == "evaluation":
                data["appraisal_cycle"] = evaluation_cycles.get(name)
                cycle, _ = evaluation_context(person, data["appraisal_cycle"])
                if frappe.db.exists("Appraisal", {"employee": person.employee,
                        "appraisal_cycle": cycle.name, "docstatus": ["!=", 2]}):
                    raise ValueError("An appraisal already exists; reconcile manually")
            if data["kind"] == "attendance":
                for field in ("start", "end"):
                    if frappe.db.exists("Employee Checkin", {"employee": person.employee,
                            "time": f"{data['date']} {data[field]}"}):
                        raise ValueError("A checkin already exists; reconcile manually")
            if dry_run:
                report.append({"name": name, "status": "ready_for_validation"})
                continue
            native, secondary = create_native(person, data)
            link_record(doc, native, secondary, data)
            # Preserve the original request identity AND the original archive.
            doc.request_fingerprint = fingerprint(validate_record(raw))
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            report.append({"name": name, "status": "migrated", "doctype": native.doctype,
                           "native_name": native.name})
        except Exception as exc:
            if not dry_run:
                # Full rollback invokes File cleanup hooks, unlike a SQL savepoint.
                frappe.db.rollback()
            report.append({"name": name, "status": "needs_review", "reason": str(exc)})
    if not dry_run:
        frappe.db.commit()
    return {"dry_run": dry_run, "records": report}
