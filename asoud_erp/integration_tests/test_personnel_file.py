import base64
from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import personnel, personnel_file
from asoud_erp.asoud_erp.doctype.asoud_personnel_record import test_asoud_personnel_record as fixtures


def _pdf() -> str:
    from pypdf import PdfWriter

    writer, buffer = PdfWriter(), BytesIO()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return base64.b64encode(buffer.getvalue()).decode()


PDF = _pdf()


def ensure(doctype: str, name: str, values: dict) -> str:
    if not frappe.db.exists(doctype, name):
        frappe.get_doc({"doctype": doctype, **values}).insert()
    return name


class TestPersonnelFile(FrappeTestCase):
    rollback_test = fixtures.TestASOUDPersonnelNative.rollback_test

    def setUp(self):
        fixtures.TestASOUDPersonnelNative.setUp(self)
        self.user = "file.employee@example.com"
        if not frappe.db.exists("User", self.user):
            frappe.get_doc({"doctype": "User", "email": self.user, "first_name": "File",
                            "send_welcome_email": 0, "roles": [{"role": "Employee"}]}).insert()
        ensure("Designation", "کارشناس فروش", {"designation_name": "کارشناس فروش"})
        ensure("Designation", "سرپرست فروش", {"designation_name": "سرپرست فروش"})
        self.department = frappe.get_doc({"doctype": "Department", "department_name": "فروش",
                                          "company": self.company}).insert().name
        self.manager = frappe.get_doc({"doctype": "Employee", "first_name": "مدیر", "last_name": "فروش",
                                       "company": self.company, "gender": "Male", "date_of_birth": "1985-01-01",
                                       "date_of_joining": "2018-01-01", "designation": "سرپرست فروش"}).insert()
        self.employee.reload()
        self.employee.update({"user_id": self.user, "designation": "کارشناس فروش", "department": self.department,
                              "reports_to": self.manager.name, "marital_status": "Married",
                              "person_to_be_contacted": "زهرا", "emergency_phone_number": "09120000000",
                              "relation": "همسر", "bank_name": "Bank Secret", "iban": "IR050170000000123456789012"})
        self.employee.append("education", {"school_univ": "دانشگاه تهران", "qualification": "کارشناسی",
                                           "level": "Graduate", "year_of_passing": 2012})
        self.employee.save()

    def test_hr_sees_a_complete_file(self):
        doc = personnel.add_record(self.person.name, {
            "kind": "document", "title": "کارت ملی", "date": "2015-05-01", "file": PDF, "filename": "id.pdf",
            "document_category": "Identity", "document_number": "0012345678",
            "expiry_date": add_days(nowdate(), 10)}, "file-doc-request-1")["data"]["id"]
        contracts = personnel_file.save_contract(self.person.name, "2026-01-01", "شرح وظایف و مزایا",
                                                 end_date="2026-12-31", is_signed=1, file=PDF,
                                                 filename="contract.pdf", submit=1)["data"]
        self.assertEqual((contracts[0]["state"], contracts[0]["file"]["filename"]), ("active", "contract.pdf"))
        promotion = personnel_file.add_promotion(self.person.name, nowdate(), designation="سرپرست فروش",
                                                 remarks="عملکرد عالی")["data"]
        self.assertEqual(promotion["docstatus"], 1)
        self.assertEqual(frappe.db.get_value("Employee", self.employee.name, "designation"), "سرپرست فروش")

        data = personnel_file.get_personnel_file(self.person.name)["data"]
        header = data["header"]
        self.assertEqual((header["employee_code"], header["designation"], header["department_name"]),
                         (self.employee.name, "سرپرست فروش", "فروش"))
        self.assertEqual(header["service_length"]["years"] >= 6, True)
        self.assertEqual(data["personal"]["emergency"], {"name": "زهرا", "phone": "09120000000", "relation": "همسر"})
        self.assertEqual(data["personal"]["education"][0]["qualification"], "کارشناسی")
        self.assertEqual(data["organization"]["reports_to"]["name"], "مدیر فروش")
        self.assertEqual(data["organization"]["department_path"], ["فروش"])
        self.assertEqual(data["employment"]["contract_end_date"], "2026-12-31")
        document = next(row for row in data["documents"] if row["id"] == doc)
        self.assertEqual((document["category"], document["document_number"], document["status"]),
                         ("Identity", "0012345678", "expiring"))
        kinds = [event["kind"] for event in data["history"]]
        self.assertIn("promotion", kinds)
        self.assertIn("contract", kinds)
        self.assertEqual(kinds[-1], "joining")
        promotion_event = next(e for e in data["history"] if e["kind"] == "promotion")
        self.assertIn("سرپرست فروش", promotion_event["details"])
        titles = [item["title"] for item in data["activity"]]
        self.assertIn("ثبت قرارداد", titles)
        self.assertIn("ثبت مدرک", titles)
        self.assertTrue(data["can_edit"])
        self.assertNotIn("Bank Secret", frappe.as_json(data))
        self.assertNotIn("IR050170000000123456789012", frappe.as_json(data))
        attachment = personnel_file.get_contract_file(contracts[0]["name"])["data"]
        self.assertEqual(base64.b64decode(attachment["content_base64"])[:5], b"%PDF-")

    def test_new_employee_fields_are_edited_on_employee(self):
        detail = personnel.get_personnel(self.person.name)["data"]
        personnel.update_personnel(self.person.name, {"blood_group": "O+", "emergency_phone": "09121111111",
                                                      "company_email": "sales@example.com"},
                                   detail["revision"], "file-update-request-1")
        values = frappe.db.get_value("Employee", self.employee.name,
                                     ["blood_group", "emergency_phone_number", "company_email"], as_dict=True)
        self.assertEqual((values.blood_group, values.emergency_phone_number, values.company_email),
                         ("O+", "09121111111", "sales@example.com"))
        with self.assertRaises(frappe.ValidationError):
            personnel.update_personnel(self.person.name, {"iban": "IR1"}, detail["revision"], "file-update-2")

    def test_employee_sees_only_their_own_file_and_cannot_change_it(self):
        personnel_file.create_announcement("جلسه عمومی", "پنجشنبه ساعت ۱۰", expire_on=add_days(nowdate(), 5))
        frappe.set_user(self.user)
        mine = personnel_file.get_my_personnel_file()["data"]
        self.assertEqual(mine["profile_id"], self.person.name)
        self.assertFalse(mine["can_edit"])
        self.assertIsNone(mine["salary"]["legacy"])
        home = personnel_file.get_my_home()["data"]
        self.assertEqual((home["employee"], home["designation"]), (self.employee.name, "کارشناس فروش"))
        self.assertIn("جلسه عمومی", [row["title"] for row in home["announcements"]])
        self.assertEqual(set(home["counts"]), {"open_requests", "open_tasks", "unread_notifications",
                                               "pending_leave_applications", "leave_remaining"})
        with self.assertRaises(frappe.PermissionError):
            personnel_file.save_contract(self.person.name, "2026-01-01", "x")
        with self.assertRaises(frappe.PermissionError):
            personnel_file.add_promotion(self.person.name, nowdate(), designation="سرپرست فروش")
        with self.assertRaises(frappe.PermissionError):
            personnel_file.create_announcement("عنوان", "متن")
        other = frappe.get_doc({"doctype": "ASOUD Party Profile", "party_type": "Individual",
                                "display_name": "Other", "company": self.company, "roles_text": '["Employee"]',
                                "employee": self.manager.name}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            personnel_file.get_personnel_file(other.name)

    def test_expired_announcements_are_hidden(self):
        personnel_file.create_announcement("قدیمی", "منقضی", expire_on=add_days(nowdate(), -1))
        titles = [row["title"] for row in personnel_file.list_announcements()["data"]]
        self.assertNotIn("قدیمی", titles)

    def test_contract_rules(self):
        with self.assertRaises(frappe.ValidationError):
            personnel_file.save_contract(self.person.name, "2026-01-01", "   ")
        with self.assertRaises(frappe.ValidationError):
            personnel_file.save_contract(self.person.name, "2026-01-01", "terms", file="bm90IGEgcGRm")
        with self.assertRaises(frappe.ValidationError):
            personnel_file.add_promotion(self.person.name, nowdate(), designation="کارشناس فروش")
