"""«فعال/غیرفعال کردن حساب»، «ارسال مجدد دعوت» و «مشاهده سوابق ورود».

The account operations of the ⋮ menu of a personnel file. They act on the
standard Frappe records only: ``User.enabled``, ``User Permission``,
``Activity Log`` and ``tabSessions``. The HR file itself (Employee and its
records) is never touched by them.
"""

import json

import frappe
from frappe.permissions import add_user_permission
from frappe.utils import now_datetime

from asoud_erp.api.v1 import auth, personnel_file
from asoud_erp.integration_tests.fixtures import APITestCase

HR_USER = "asoud.hr.ops@example.com"
OTHER_HR_USER = "asoud.otherhr.ops@example.com"
TARGET_USER = "asoud.target.ops@example.com"
OTHER_TARGET_USER = "asoud.other.target.ops@example.com"
TARGET_EMPLOYEE = "EMP-OPS-TARGET"
MANAGER_EMPLOYEE = "EMP-OPS-HR"
OTHER_TARGET_EMPLOYEE = "EMP-OPS-OTHER-TARGET"
OTHER_HR_EMPLOYEE = "EMP-OPS-OTHER-HR"
DEPARTMENT = "ASOUD Account Ops Department"
OTHER_COMPANY = "ASOUD Account Ops Co"
OTHER_COMPANY_ABBR = "AAOC"
OUTGOING_EMAIL = "asoud-hr-ops@example.com"
SID = "asoudopssessionid"
CSRF = "asoudopscsrftoken"
# A 1×1 PNG; the Employee image is read from the private File, not from the disk.
PHOTO_CONTENT = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQ"
                "AAAABJRU5ErkJggg==")


def _user(email: str, roles: list[str]) -> str:
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": role} for role in roles]}).insert(ignore_permissions=True)
    return email


def _outgoing_email_account() -> None:
    """Frappe's own outgoing account check; created inside the test transaction."""
    if not frappe.db.exists("Email Account", {"default_outgoing": 1}):
        frappe.get_doc({"doctype": "Email Account", "email_account_name": "ASOUD HR Ops",
                        "email_id": OUTGOING_EMAIL, "password": "asoud-ops",
                        "enable_outgoing": 1, "default_outgoing": 1,
                        "smtp_server": "localhost", "smtp_port": 587}).insert(
            ignore_permissions=True)


def _company(name: str, abbr: str) -> str:
    if not frappe.db.exists("Company", name):
        frappe.get_doc({"doctype": "Company", "company_name": name, "abbr": abbr,
                        "default_currency": "USD", "country": "United States",
                        "chart_of_accounts": "Standard"}).insert(ignore_permissions=True)
    return name


def _department(company: str) -> str:
    name = frappe.db.get_value("Department", {"department_name": DEPARTMENT, "company": company}, "name")
    if name:
        return name
    return frappe.get_doc({"doctype": "Department", "department_name": DEPARTMENT,
                           "company": company}).insert(ignore_permissions=True).name


def _employee(name: str, user: str, company: str, **extra) -> str:
    """A fixed Employee name, so a test run never waits on the Employee naming series."""
    existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if existing:
        return existing
    if frappe.db.exists("Employee", name):
        return name
    return frappe.get_doc({
        "doctype": "Employee", "name": name, "first_name": "کارمند", "gender": "Male",
        "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01", "company": company,
        "status": "Active", "user_id": user, "create_user_permission": 0, **extra,
    }).insert(ignore_permissions=True).name


def _purge() -> None:
    """Delete every record this module owns; a mid-test commit must not poison the next run."""
    users = [HR_USER, OTHER_HR_USER, TARGET_USER, OTHER_TARGET_USER]
    for user in users:
        frappe.db.delete("Sessions", {"user": user})
        frappe.db.delete("Activity Log", {"user": user})
        for permission in frappe.get_all("User Permission", filters={"user": user}, pluck="name"):
            frappe.delete_doc("User Permission", permission, ignore_permissions=True, force=True)
        for employee in frappe.get_all("Employee", filters={"user_id": user}, pluck="name"):
            for profile in frappe.get_all("ASOUD Party Profile", filters={"employee": employee}, pluck="name"):
                for doctype in ("ASOUD Personnel Record", "ASOUD Personnel Operation"):
                    for record in frappe.get_all(doctype, filters={"party": profile}, pluck="name"):
                        frappe.delete_doc(doctype, record, ignore_permissions=True, force=True)
                for invitation in frappe.get_all("ASOUD Employee Invitation",
                                                 filters={"party_profile": profile}, pluck="name"):
                    frappe.delete_doc("ASOUD Employee Invitation", invitation, ignore_permissions=True,
                                      force=True)
                frappe.delete_doc("ASOUD Party Profile", profile, ignore_permissions=True, force=True)
            for file_name in frappe.get_all("File", filters={"attached_to_name": employee}, pluck="name"):
                frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
            frappe.delete_doc("Employee", employee, ignore_permissions=True, force=True)
        frappe.db.set_value("User", user, {"enabled": 1, "last_login": None, "last_ip": None},
                            update_modified=False)
    for department in frappe.get_all("Department", filters={"department_name": DEPARTMENT}, pluck="name"):
        frappe.delete_doc("Department", department, ignore_permissions=True, force=True)
    for company in frappe.get_all("Company", filters={"company_name": OTHER_COMPANY}, pluck="name"):
        frappe.delete_doc("Company", company, ignore_permissions=True, force=True)
    frappe.db.commit()


def _profile(employee: str, company: str) -> str:
    name = frappe.db.get_value("ASOUD Party Profile", {"employee": employee}, "name")
    if name:
        return name
    return frappe.get_doc({"doctype": "ASOUD Party Profile", "party_type": "Individual",
                           "display_name": "کارمند آزمایشی", "company": company,
                           "roles_text": '["Employee"]', "employee": employee,
                           "employee_roles": '["employee"]'}).insert(ignore_permissions=True).name


def _session(user: str, sid: str, last_active, ip: str, device: str = "") -> None:
    sessiondata = {"data": {"user": user, "session_ip": ip, "last_updated": str(last_active)},
                   "user": user, "sid": sid, "csrf_token": CSRF}
    if device:
        sessiondata["data"]["device"] = device
    frappe.db.sql(
        "insert into `tabSessions` (`user`, `sid`, `sessiondata`, `ipaddress`, `lastupdate`, `status`)"
        " values (%s, %s, %s, %s, %s, %s)",
        (user, sid, repr(sessiondata), ip, last_active, "Active"))


def _sessions_of(user: str) -> list[str]:
    return frappe.db.sql("select `sid` from `tabSessions` where `user` = %s", (user,), pluck=True)


def _activity(user: str, when: str, operation: str, status: str, ip: str) -> None:
    name = frappe.get_doc({"doctype": "Activity Log", "user": user, "status": status,
                           "subject": f"{user} {operation}", "operation": operation}).insert(
        ignore_permissions=True, ignore_links=True).name
    frappe.db.set_value("Activity Log", name, {"creation": when, "ip_address": ip},
                        update_modified=False)


class TestAccountOps(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        _user(HR_USER, ["HR Manager", "Employee"])
        _user(OTHER_HR_USER, ["HR Manager", "Employee"])
        _user(TARGET_USER, ["Employee"])
        _user(OTHER_TARGET_USER, ["Employee"])
        company = cls.records["company"]
        department = _department(company)
        employee = _employee(TARGET_EMPLOYEE, TARGET_USER, company, department=department)
        _profile(employee, company)
        _employee(MANAGER_EMPLOYEE, HR_USER, company, department=department)
        # The seeds are committed so that no test waits on an insert lock while
        # other workers run tests on this shared site; tearDownClass removes them.
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        company = self.records["company"]
        self.company = company
        self.department = _department(company)
        self.employee = _employee(TARGET_EMPLOYEE, TARGET_USER, company, department=self.department)
        self.person = _profile(self.employee, company)
        self.manager = _employee(MANAGER_EMPLOYEE, HR_USER, company, department=self.department)
        frappe.db.set_value("Employee", self.employee, "reports_to", None, update_modified=False)
        frappe.db.delete("Sessions", {"user": TARGET_USER})
        frappe.db.delete("Activity Log", {"user": TARGET_USER})
        frappe.db.set_value("User", TARGET_USER, {"enabled": 1, "last_login": None, "last_ip": None},
                            update_modified=False)
        _outgoing_email_account()
        frappe.set_user(HR_USER)

    def tearDown(self):
        # Disabling an account clears its sessions through frappe.sessions, which commits
        # mid-test; the rows a test may have leaked are cleaned up and committed here.
        frappe.db.rollback()
        frappe.set_user("Administrator")
        frappe.db.delete("Sessions", {"user": TARGET_USER})
        frappe.db.delete("Activity Log", {"user": TARGET_USER})
        frappe.db.set_value("User", TARGET_USER, {"enabled": 1, "last_login": None, "last_ip": None},
                            update_modified=False)
        frappe.db.set_value("User", HR_USER, {"enabled": 1}, update_modified=False)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.db.rollback()
        frappe.set_user("Administrator")
        _purge()
        super().tearDownClass()

    def employee_state(self) -> dict:
        employee = frappe.get_doc("Employee", self.employee)
        return {
            "fields": {field: str(employee.get(field) or "") for field in
                       ("user_id", "status", "company", "department", "designation", "reports_to")},
            "modified": str(employee.modified),
            "records": frappe.db.count("ASOUD Personnel Record", {"party": self.person}),
            "roles": frappe.db.get_value("ASOUD Party Profile", self.person, "employee_roles"),
        }

    def test_disable_ends_the_access_without_touching_the_hr_file(self):
        before = self.employee_state()
        _session(TARGET_USER, SID, now_datetime(), "5.62.9.10")
        self.assertIn(SID, _sessions_of(TARGET_USER))

        status = auth.set_account_enabled(self.person, 0, "account-ops-disable-1")["data"]

        self.assertEqual(status["enabled"], 0)
        self.assertEqual(frappe.db.get_value("User", TARGET_USER, "enabled"), 0)
        self.assertEqual(self.employee_state(), before)
        self.assertEqual(_sessions_of(TARGET_USER), [])

    def test_enable_gives_the_access_back(self):
        frappe.db.set_value("User", TARGET_USER, "enabled", 0, update_modified=False)
        status = auth.set_account_enabled(self.person, 1, "account-ops-enable-1")["data"]
        self.assertEqual(status["enabled"], 1)
        self.assertEqual(frappe.db.get_value("User", TARGET_USER, "enabled"), 1)
        self.assertEqual(frappe.db.get_value("Employee", self.employee, "status"), "Active")

    def test_the_same_request_id_changes_the_account_once(self):
        first = auth.set_account_enabled(self.person, 0, "account-ops-replay-1")["data"]
        modified = frappe.db.get_value("User", TARGET_USER, "modified")
        again = auth.set_account_enabled(self.person, 0, "account-ops-replay-1")["data"]

        self.assertEqual((first["replayed"], again["replayed"]), (False, True))
        self.assertEqual({key: value for key, value in again.items() if key != "replayed"},
                         {key: value for key, value in first.items() if key != "replayed"})
        self.assertEqual(frappe.db.get_value("User", TARGET_USER, "modified"), modified)
        self.assertEqual(frappe.db.count("ASOUD Personnel Operation", {
            "request_id": "account-ops-replay-1", "action": "account_enabled"}), 1)

    def test_a_conflicting_reuse_of_the_request_id_is_refused(self):
        auth.set_account_enabled(self.person, 0, "account-ops-conflict-1")
        with self.assertRaises(frappe.ValidationError):
            auth.set_account_enabled(self.person, 1, "account-ops-conflict-1")

    def test_account_status_reports_roles_modules_and_data_scope(self):
        status = auth.get_account_status(self.person)["data"]
        self.assertEqual(status["user"], TARGET_USER)
        self.assertEqual((status["enabled"], status["has_logged_in"]), (1, False))
        self.assertEqual(status["can_resend_invitation"], True)
        self.assertIn("Employee", status["roles"])
        self.assertNotIn("HR Manager", status["roles"])
        self.assertIn("Accounts", status["modules"])
        self.assertIn("ASOUD ERP", status["modules"])
        access = auth.get_employee_access(self.person)["data"]
        self.assertEqual(access["roles"], ["employee"])
        self.assertEqual(access["access_level"], "user")
        self.assertEqual(access["modules"], status["modules"])
        self.assertEqual(access["data_scope"], [])

        auth.sync_employee_access(self.person, TARGET_USER, ["employee"])["data"]

        scope = auth.get_account_status(self.person)["data"]["data_scope"]
        self.assertEqual({(row["allow"], row["value"], row["apply_to_all_doctypes"]) for row in scope},
                         {("Company", self.company, 1), ("Department", self.department, 1),
                          ("Employee", self.employee, 1)})
        self.assertEqual(auth.get_account_status(self.person)["data"]["modules"], status["modules"])

    def test_a_logged_in_account_can_no_longer_be_invited(self):
        allowed = auth.send_employee_invitation(self.person, TARGET_USER, ["employee"],
                                                "account-ops-invite-1")["data"]
        self.assertEqual(allowed["status"], "Queued")
        self.assertEqual(frappe.db.count("ASOUD Employee Invitation",
                                         {"party_profile": self.person}), 1)

        frappe.db.set_value("User", TARGET_USER, "last_login", now_datetime(), update_modified=False)
        self.assertEqual(auth.get_account_status(self.person)["data"]["can_resend_invitation"], False)
        with self.assertRaises(frappe.ValidationError) as refused:
            auth.send_employee_invitation(self.person, TARGET_USER, ["employee"], "account-ops-invite-2")
        self.assertIn("ارسال مجدد دعوت", str(refused.exception))
        self.assertEqual(frappe.db.count("ASOUD Employee Invitation", {"party_profile": self.person}), 1)

    def test_a_queued_invitation_replays_instead_of_sending_twice(self):
        first = auth.send_employee_invitation(self.person, TARGET_USER, ["employee"],
                                              "account-ops-invite-3")["data"]
        again = auth.send_employee_invitation(self.person, TARGET_USER, ["employee"],
                                              "account-ops-invite-3")["data"]
        self.assertEqual(again["name"], first["name"])
        self.assertEqual(frappe.db.count("ASOUD Employee Invitation", {"party_profile": self.person}), 1)

    def test_login_history_returns_the_seeded_events_and_sessions(self):
        _activity(TARGET_USER, "2026-02-01 07:00:00", "Login", "Failed", "10.0.0.1")
        _activity(TARGET_USER, "2026-02-02 08:00:00", "Logout", "Success", "10.0.0.2")
        _activity(TARGET_USER, "2026-02-03 09:15:00", "Login", "Success", "10.0.0.3")
        active = now_datetime().replace(microsecond=0)
        _session(TARGET_USER, SID, active, "10.0.0.3", device="Chrome / Android")
        frappe.db.set_value("User", TARGET_USER, {"last_login": "2026-02-03 09:15:00",
                                                  "last_ip": "10.0.0.3"}, update_modified=False)

        history = auth.get_login_history(self.person, 20)["data"]

        self.assertEqual(history["last_login"], "2026-02-03 09:15:00")
        self.assertEqual(history["last_ip"], "10.0.0.3")
        seeded = [event for event in history["events"] if event["datetime"].startswith("2026-02-0")]
        self.assertEqual([(event["datetime"], event["operation"], event["status"], event["ip"])
                          for event in seeded], [
            ("2026-02-03 09:15:00", "Login", "Success", "10.0.0.3"),
            ("2026-02-02 08:00:00", "Logout", "Success", "10.0.0.2"),
            ("2026-02-01 07:00:00", "Login", "Failed", "10.0.0.1"),
        ])
        datetimes = [event["datetime"] for event in history["events"]]
        self.assertEqual(datetimes, sorted(datetimes, reverse=True))
        for event in history["events"]:
            self.assertEqual(set(event), {"datetime", "operation", "status", "ip"})
        self.assertEqual(history["sessions"], [{
            "device": "Chrome / Android", "ip": "10.0.0.3",
            "last_active": str(active), "status": "Active"}])
        payload = json.dumps(history, ensure_ascii=False)
        self.assertNotIn(SID, payload)
        self.assertNotIn(CSRF, payload)

    def test_login_history_of_an_account_that_never_logged_in_is_empty(self):
        history = auth.get_login_history(self.person)["data"]
        self.assertEqual(history["last_login"], "")
        self.assertEqual(history["sessions"], [])

    def test_an_employee_cannot_use_the_account_operations(self):
        frappe.set_user(TARGET_USER)
        for call in (
            lambda: auth.get_account_status(self.person),
            lambda: auth.set_account_enabled(self.person, 0, "account-ops-employee-1"),
            lambda: auth.get_login_history(self.person),
            lambda: auth.send_employee_invitation(
                self.person, TARGET_USER, ["employee"], "account-ops-employee-2"),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()
        self.assertEqual(frappe.db.get_value("User", TARGET_USER, "enabled"), 1)

    def test_an_hr_manager_of_another_company_is_refused(self):
        _company(OTHER_COMPANY, OTHER_COMPANY_ABBR)
        other_employee = _employee(OTHER_TARGET_EMPLOYEE, OTHER_TARGET_USER, OTHER_COMPANY)
        other_person = _profile(other_employee, OTHER_COMPANY)
        _employee(OTHER_HR_EMPLOYEE, OTHER_HR_USER, self.company)
        # An HR manager whose own Employee user permission would hide every other
        # Employee, so the company restriction is stated explicitly instead.
        add_user_permission("Company", self.company, OTHER_HR_USER, ignore_permissions=True)
        frappe.cache.hdel("user_permissions", OTHER_HR_USER)
        frappe.set_user(OTHER_HR_USER)

        for call in (
            lambda: auth.get_account_status(other_person),
            lambda: auth.set_account_enabled(other_person, 0, "account-ops-otherco-1"),
            lambda: auth.get_login_history(other_person),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()

    def test_the_personnel_file_shows_the_direct_manager_photo(self):
        photo = frappe.get_doc({"doctype": "File", "file_name": "manager.png",
                                "content": PHOTO_CONTENT, "is_private": 1,
                                "attached_to_doctype": "Employee", "attached_to_name": self.manager,
                                "owner": "Administrator"}).insert(ignore_permissions=True)
        frappe.db.set_value("Employee", self.manager, "image", photo.file_url)
        frappe.db.set_value("Employee", self.employee, "reports_to", self.manager)

        reports_to = personnel_file.get_personnel_file(self.person)["data"]["organization"]["reports_to"]
        self.assertEqual(reports_to["employee"], self.manager)
        self.assertEqual(reports_to["photo_record"], f"native:File:{photo.name}")

        # Without an Employee image the manager's personnel photo record is used instead.
        frappe.db.set_value("Employee", self.manager, "image", None)
        manager_person = _profile(self.manager, self.company)
        record = frappe.get_doc({"doctype": "ASOUD Personnel Record", "party": manager_person,
                                 "company": self.company, "kind": "photo", "title": "عکس مدیر",
                                 "record_date": "2026-01-01", "payload": "{}",
                                 "request_id": "account-ops-photo-1"}).insert(
            ignore_permissions=True)
        fallback = personnel_file.get_personnel_file(self.person)["data"]["organization"]["reports_to"]
        self.assertEqual(fallback["photo_record"], record.name)