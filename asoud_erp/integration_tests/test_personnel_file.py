import base64
from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import personnel, personnel_file
from asoud_erp.asoud_erp.doctype.asoud_personnel_record import test_asoud_personnel_record as fixtures


def _pdf(pages: int = 1) -> str:
    from pypdf import PdfWriter

    writer, buffer = PdfWriter(), BytesIO()
    for width in range(70 + pages, 71 + pages):
        writer.add_blank_page(width=width, height=72)
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

    def _other_employee(self, email: str, first_name: str):
        user = frappe.get_doc({"doctype": "User", "email": email, "first_name": first_name,
                               "send_welcome_email": 0, "roles": [{"role": "Employee"}]}).insert().name
        employee = frappe.get_doc({"doctype": "Employee", "first_name": first_name,
                                   "company": self.company, "gender": "Male", "date_of_birth": "1992-02-02",
                                   "date_of_joining": "2021-01-01", "designation": "کارشناس فروش",
                                   "user_id": user, "create_user_permission": 0}).insert()
        person = frappe.get_doc({"doctype": "ASOUD Party Profile", "party_type": "Individual",
                                 "display_name": first_name, "company": self.company,
                                 "roles_text": '["Employee"]', "employee": employee.name}).insert()
        return user, employee, person

    def _contract(self, values: dict, content: str = PDF, filename: str = "contract.pdf") -> str:
        frappe.set_user("Administrator")
        doc = frappe.get_doc(values).insert()
        frappe.get_doc({"doctype": "File", "file_name": filename, "content": base64.b64decode(content),
                        "is_private": 1, "attached_to_doctype": "Contract",
                        "attached_to_name": doc.name}).insert(ignore_permissions=True)
        return doc.name

    def test_contract_file_download_is_limited_to_its_own_employee_and_hr(self):
        secret, other_secret = _pdf(), _pdf(pages=2)
        self.assertNotEqual(base64.b64decode(secret), base64.b64decode(other_secret))
        own = personnel_file.save_contract(self.person.name, "2026-01-01", "terms", is_signed=1, file=secret,
                                           filename="mine.pdf", submit=1)["data"][0]["name"]
        other_user, _, other_person = self._other_employee("file.other@example.com", "Other")
        other = personnel_file.save_contract(other_person.name, "2026-01-01", "terms", is_signed=1,
                                             file=other_secret, filename="other.pdf",
                                             submit=1)["data"][0]["name"]
        own_file = frappe.get_doc("File", frappe.db.get_value("File", {"attached_to_doctype": "Contract",
                                                                       "attached_to_name": own,
                                                                       "is_private": 1}, "name"))

        frappe.set_user(self.user)
        downloaded = personnel_file.get_contract_file(own)["data"]
        self.assertEqual(downloaded["filename"], "mine.pdf")
        self.assertEqual(base64.b64decode(downloaded["content_base64"]), base64.b64decode(secret))
        with self.assertRaises(frappe.PermissionError) as denied:
            personnel_file.get_contract_file(other)
        self.assertIn("Personnel access denied", str(denied.exception))
        self.assertNotIn(base64.b64decode(other_secret), str(denied.exception).encode())
        self.assertNotIn("other.pdf", str(denied.exception))

        frappe.set_user(other_user)
        with self.assertRaises(frappe.PermissionError) as reversed_denial:
            personnel_file.get_contract_file(own)
        self.assertIn("Personnel access denied", str(reversed_denial.exception))
        self.assertNotIn(base64.b64decode(secret), str(reversed_denial.exception).encode())
        self.assertNotIn("mine.pdf", str(reversed_denial.exception))
        other_file = frappe.get_doc("File", frappe.db.get_value("File", {"attached_to_doctype": "Contract",
                                                                         "attached_to_name": other,
                                                                         "is_private": 1}, "name"))
        self.assertFalse(frappe.has_permission("File", "read", other_file))
        self.assertFalse(other_file.is_downloadable())

        frappe.set_user("Administrator")
        foreign = "ASOUD Foreign HR Test"
        if not frappe.db.exists("Company", foreign):
            frappe.get_doc({"doctype": "Company", "company_name": foreign, "abbr": "AFHT",
                            "default_currency": "USD", "country": "United States",
                            "chart_of_accounts": "Standard"}).insert()
        hr_user = frappe.get_doc({"doctype": "User", "email": "file.foreign.hr@example.com",
                                  "first_name": "Foreign HR", "send_welcome_email": 0,
                                  "roles": [{"role": "HR Manager"}]}).insert().name
        frappe.get_doc({"doctype": "User Permission", "user": hr_user, "allow": "Company",
                        "for_value": foreign, "apply_to_all_doctypes": 1}).insert()
        frappe.set_user(hr_user)
        with self.assertRaises(frappe.PermissionError) as hr_denied:
            personnel_file.get_contract_file(own)
        self.assertIn("Company access denied", str(hr_denied.exception))
        self.assertNotIn(base64.b64decode(secret), str(hr_denied.exception).encode())
        self.assertNotIn("mine.pdf", str(hr_denied.exception))

        supplier = frappe.db.get_value("Supplier", {"is_transporter": 0}, "name") or ensure(
            "Supplier", "file-test-supplier", {"supplier_name": "file-test-supplier",
                                               "supplier_group": "All Supplier Groups",
                                               "supplier_type": "Company"})
        orphan = frappe.db.get_value("Employee", {"company": self.company, "user_id": ("is", "not set")},
                                     "name", order_by="creation desc")
        frappe.set_user("Administrator")
        vendor_contract = self._contract({"doctype": "Contract", "party_type": "Supplier",
                                          "party_name": supplier, "start_date": "2026-01-01",
                                          "contract_terms": "vendor", "is_signed": 1,
                                          "signee": "Vendor", "signed_on": nowdate()})
        if orphan:
            orphan_contract = self._contract({"doctype": "Contract", "party_type": "Employee",
                                              "party_name": orphan, "start_date": "2026-01-01",
                                              "contract_terms": "orphan", "is_signed": 1,
                                              "signee": orphan, "signed_on": nowdate()})
        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError) as vendor:
            personnel_file.get_contract_file(vendor_contract)
        self.assertIn("Not a personnel contract", str(vendor.exception))
        self.assertNotIn(base64.b64decode(secret), str(vendor.exception).encode())
        self.assertNotIn("vendor.pdf", str(vendor.exception))
        if orphan:
            with self.assertRaises(frappe.PermissionError) as missing:
                personnel_file.get_contract_file(orphan_contract)
            self.assertIn("Employee has no personnel file", str(missing.exception))
            self.assertNotIn("orphan.pdf", str(missing.exception))

        frappe.set_user("Administrator")
        self.assertEqual(base64.b64decode(personnel_file.get_contract_file(own)["data"]["content_base64"]),
                         base64.b64decode(secret))
        self.assertTrue(frappe.has_permission("File", "read", own_file))
        self.assertTrue(own_file.is_downloadable())

    def test_contract_rules(self):
        with self.assertRaises(frappe.ValidationError):
            personnel_file.save_contract(self.person.name, "2026-01-01", "   ")
        with self.assertRaises(frappe.ValidationError):
            personnel_file.save_contract(self.person.name, "2026-01-01", "terms", file="bm90IGEgcGRm")
        with self.assertRaises(frappe.ValidationError):
            personnel_file.add_promotion(self.person.name, nowdate(), designation="کارشناس فروش")
