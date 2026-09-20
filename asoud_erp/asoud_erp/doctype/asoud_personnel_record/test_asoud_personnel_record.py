import base64
import json
from io import BytesIO
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from pypdf import PdfWriter

from asoud_erp.api.v1 import personnel
from asoud_erp.services.personnel_migration import migrate_legacy_records


class TestASOUDPersonnelNative(FrappeTestCase):
    def setUp(self):
        self.addCleanup(self.rollback_test)
        frappe.set_user("Administrator")
        if not frappe.db.exists("Gender", "Male"):
            frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert()
        self.company = "ASOUD Native HR Test"
        if not frappe.db.exists("Company", self.company):
            frappe.get_doc({"doctype": "Company", "company_name": self.company,
                "abbr": "ANHT", "default_currency": "USD", "country": "United States",
                "chart_of_accounts": "Standard"}).insert()
        self.employee = frappe.get_doc({"doctype": "Employee", "first_name": "Native HR",
            "company": self.company, "gender": "Male", "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01", "status": "Active"}).insert()
        self.person = frappe.get_doc({"doctype": "ASOUD Party Profile", "party_type": "Individual",
            "display_name": "Old cached name", "company": self.company, "roles_text": '["Employee"]',
            "employee": self.employee.name}).insert()

    def rollback_test(self):
        frappe.db.rollback()
        frappe.db.value_cache = {}
        frappe.clear_cache()

    def add(self, payload, request="native-test-request"):
        return personnel.add_record(self.person.name, payload, request)["data"]["id"]

    def attendance(self):
        return {"kind": "attendance", "title": "Work day", "date": "2026-01-02",
                "start": "08:00", "end": "16:00"}

    def test_attendance_uses_checkins_and_retries_once(self):
        payload = self.attendance()
        name = self.add(payload)
        self.assertEqual(self.add(payload), name)
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee.name}), 2)
        link = frappe.get_doc("ASOUD Personnel Record", name)
        self.assertEqual(link.payload, "{}")
        self.assertEqual(link.native_doctype, "Employee Checkin")
        value = personnel.get_record(name)["data"]
        self.assertEqual(value["start"], "08:00")
        edited = personnel.update_record(self.person.name, name, {**payload, "end": "17:00"},
                                        value["_revision"], "native-edit-request")["data"]
        self.assertEqual(edited["end"], "17:00")
        personnel.update_record(self.person.name, name, {**payload, "end": "17:00"},
                                value["_revision"], "native-edit-request")
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee.name}), 2)
        self.assertEqual(frappe.db.count("ASOUD Personnel Operation", {"party": self.person.name}), 1)

    def test_external_checkin_edit_invalidates_mobile_revision(self):
        payload = self.attendance()
        name = self.add(payload)
        value = personnel.get_record(name)["data"]
        link = frappe.get_doc("ASOUD Personnel Record", name)
        checkin = frappe.get_doc("Employee Checkin", link.native_secondary)
        checkin.time = "2026-01-02 18:00:00"
        checkin.save()
        with self.assertRaises(frappe.TimestampMismatchError):
            personnel.update_record(self.person.name, name, {**payload, "end": "17:00"},
                                    value["_revision"], "native-stale-request")
        self.assertEqual(personnel.get_record(name)["data"]["end"], "18:00")

    def test_processed_checkins_are_not_editable(self):
        name = self.add(self.attendance())
        link = frappe.get_doc("ASOUD Personnel Record", name)
        attendance = frappe.get_doc({"doctype": "Attendance", "employee": self.employee.name,
            "company": self.company, "attendance_date": "2026-01-02", "status": "Present"}).insert()
        attendance.submit()
        frappe.db.set_value("Employee Checkin", link.native_name, "attendance", attendance.name)
        self.assertFalse(personnel.get_record(name)["data"]["_can_edit"])

    def test_employee_is_authoritative_and_external_edits_conflict(self):
        before = personnel.get_personnel(self.person.name)["data"]
        self.assertEqual(before["profile"]["display_name"], "Native HR")
        self.employee.cell_number = "09121234567"
        self.employee.save()
        after = personnel.get_personnel(self.person.name)["data"]
        self.assertEqual(after["profile"]["mobile"], "09121234567")
        self.assertNotEqual(after["revision"], before["revision"])
        with self.assertRaises(frappe.TimestampMismatchError):
            personnel.update_personnel(self.person.name, {"mobile": "09121111111"},
                                       before["revision"], "profile-stale-request")

    def test_private_file_owns_bytes_and_standard_records_are_listed(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = BytesIO()
        writer.write(buffer)
        raw = buffer.getvalue()
        name = self.add({"kind": "document", "title": "Contract", "date": "2026-01-02",
                         "filename": "contract.pdf", "file": base64.b64encode(raw).decode()})
        link = frappe.get_doc("ASOUD Personnel Record", name)
        file = frappe.get_doc("File", link.native_name)
        self.assertEqual(file.attached_to_name, self.employee.name)
        self.assertTrue(file.is_private)
        self.assertEqual(file.get_content(), raw)
        self.assertEqual(link.payload, "{}")
        self.assertEqual(base64.b64decode(personnel.get_record(name)["data"]["file"]), raw)
        checkin = frappe.get_doc({"doctype": "Employee Checkin", "employee": self.employee.name,
                                  "time": "2026-01-03 08:00", "log_type": "IN"}).insert()
        ids = [r["name"] for r in personnel.get_personnel(self.person.name)["data"]["records"]]
        self.assertIn(f"native:Employee Checkin:{checkin.name}", ids)

    def test_profile_write_updates_employee_and_retry_has_one_receipt(self):
        revision = personnel.get_personnel(self.person.name)["data"]["revision"]
        values = {"display_name": "Updated full name", "mobile": "09121234567"}
        result = personnel.update_personnel(self.person.name, values, revision, "profile-write-request")
        self.employee.reload()
        self.assertEqual(self.employee.employee_name, "Updated full name")
        self.assertEqual(result["data"]["profile"]["mobile"], self.employee.cell_number)
        personnel.update_personnel(self.person.name, values, revision, "profile-write-request")
        self.assertEqual(frappe.db.count("ASOUD Personnel Operation", {"party": self.person.name}), 1)
        self.assertFalse(frappe.db.count("ASOUD Personnel Record", {"party": self.person.name}))

    def test_tampered_link_cannot_read_another_employee_record(self):
        name = self.add(self.attendance())
        other = frappe.get_doc({"doctype": "Employee", "first_name": "Other employee",
            "company": self.company, "gender": "Male", "date_of_birth": "1991-01-01",
            "date_of_joining": "2020-01-01", "status": "Active"}).insert()
        checkin = frappe.get_doc({"doctype": "Employee Checkin", "employee": other.name,
                                  "time": "2026-01-02 08:00", "log_type": "IN"}).insert()
        frappe.db.set_value("ASOUD Personnel Record", name, "native_name", checkin.name)
        with self.assertRaises(frappe.PermissionError):
            personnel.get_record(name)

    def make_cycle(self):
        if not frappe.db.exists("KRA", "Overall performance"):
            frappe.get_doc({"doctype": "KRA", "title": "Overall performance"}).insert()
        template = frappe.get_doc({"doctype": "Appraisal Template", "template_title": frappe.generate_hash(),
            "goals": [{"key_result_area": "Overall performance", "per_weightage": 100}]}).insert()
        cycle = frappe.get_doc({"doctype": "Appraisal Cycle", "cycle_name": frappe.generate_hash(),
            "company": self.company, "start_date": "2026-01-01", "end_date": "2026-12-31",
            "kra_evaluation_method": "Manual Rating", "status": "In Progress",
            "appraisees": [{"employee": self.employee.name, "appraisal_template": template.name}]}).insert()
        return cycle

    def test_appraisal_uses_assigned_cycle_and_native_score_calculation(self):
        cycle = self.make_cycle()
        options = personnel.get_record_options(self.person.name)["data"]["appraisal_cycles"]
        self.assertIn(cycle.name, [row["name"] for row in options])
        name = self.add({"kind": "evaluation", "title": "Review", "date": "2026-06-01",
                         "score": 80, "appraisal_cycle": cycle.name})
        link = frappe.get_doc("ASOUD Personnel Record", name)
        appraisal = frappe.get_doc("Appraisal", link.native_name)
        self.assertEqual(appraisal.employee, self.employee.name)
        self.assertEqual(appraisal.docstatus, 0)
        self.assertEqual(appraisal.total_score, 4)
        self.assertNotEqual(appraisal.final_score, 80)
        self.assertEqual(personnel.get_record(name)["data"]["score"], 80)

    def test_legacy_migration_preserves_original_and_is_resumable(self):
        payload = json.dumps(self.attendance())
        legacy = frappe.get_doc({"doctype": "ASOUD Personnel Record", "company": self.company,
            "party": self.person.name, "kind": "attendance", "title": "Old day",
            "record_date": "2026-01-02", "payload": payload, "request_id": "old-attendance-request"}).insert()
        dry = migrate_legacy_records(self.company)
        self.assertEqual(dry["records"][0]["status"], "ready_for_validation")
        self.assertFalse(frappe.db.count("Employee Checkin", {"employee": self.employee.name}))
        with patch.object(frappe.db, "commit"):
            result = migrate_legacy_records(self.company, dry_run=False)
            again = migrate_legacy_records(self.company, dry_run=False)
        self.assertEqual(result["records"][0]["status"], "migrated")
        self.assertEqual(again["records"][0]["status"], "already_linked")
        self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee.name}), 2)
        legacy.reload()
        self.assertEqual(legacy.payload, payload)
        self.assertEqual(self.add(self.attendance(), "old-attendance-request"), legacy.name)
