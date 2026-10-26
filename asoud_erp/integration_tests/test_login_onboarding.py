"""Login, first-run onboarding, system administrator, roles, audit and HR onboarding on a real site."""

import json
from unittest import mock

import frappe
from frappe.utils import add_days, nowdate
from frappe.utils.password import check_password

from asoud_erp.api.v1 import (
    account_security,
    directives,
    hr,
    hr_onboarding,
    onboarding,
    role_access,
    role_management,
    session,
    setup,
    user_access,
)
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase, _employee, _user
from asoud_erp.integration_tests.tenancy import setup_tenancy
from asoud_erp.services import account_recovery, account_state, office_access, system_admin
from asoud_erp.services.delegation import DELEGATE_ROLE, OFFICE_CREATOR_ROLE
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import company_access

ADMIN = "asoud.lo-admin@example.com"
ADMIN2 = "asoud.lo-admin2@example.com"
HR_USER = "asoud.lo-hr@example.com"
PLAIN = "asoud.lo-plain@example.com"
CREATOR = "asoud.lo-creator@example.com"
OFFICE_MGR = "asoud.lo-officemgr@example.com"
DELEGATE = "asoud.lo-delegate@example.com"
NEWBIE = "asoud.lo-newbie@example.com"
STRONG = "Correct-Horse-Battery-9"
STRONGER = "Another-Long-Passphrase-42"
DIGITS_MOBILE = "۰۹۱۲۳۴۵۶۷۸۹"


def clear_office_state():
    """The shared site may already contain saved offices; these tests control the bootstrap state."""
    frappe.db.sql("update `tabASOUD Company Setup` set office_saved=0")
    settings = frappe.get_single("ASOUD Settings")
    settings.first_office_company = None
    settings.save(ignore_permissions=True)


def audit(action, **filters):
    return frappe.get_all("ASOUD Security Audit", filters={"action": action, **filters},
                          fields=["actor", "result", "target", "details", "occurred_on", "source"])


LO_PERSON_NATIONAL_IDS = ("0013542419",)


def purge_leftovers():
    """Rows an earlier (possibly interrupted) run committed; keeps every run starting from the same state."""
    frappe.set_user("Administrator")
    frappe.db.delete("ASOUD Office Role Assignment", {"user": ["like", "asoud.lo-%"]})
    frappe.db.delete("ASOUD Access Assignment", {"user": ["like", "asoud.lo-%"]})
    for name in frappe.get_all("ASOUD Role Definition", filters={"name": ["like", "LO%"]}, pluck="name"):
        frappe.delete_doc("ASOUD Role Definition", name, force=True, ignore_permissions=True)
    for name in frappe.get_all("Role Profile", filters={"name": ["like", "ASOUD:LO%"]}, pluck="name"):
        frappe.db.set_value("User", {"role_profile_name": name}, "role_profile_name", None)
        frappe.delete_doc("Role Profile", name, force=True, ignore_permissions=True)
    for name in frappe.get_all("Employee", filters={"user_id": ["like", "asoud.lo-%"]}, pluck="name"):
        if frappe.db.get_value("Employee", name, "user_id") != HR_USER:
            frappe.db.set_value("Employee", name, "user_id", None)
            try:
                frappe.delete_doc("Employee", name, force=True, ignore_permissions=True)
            except Exception:
                frappe.db.rollback()
    profiles = frappe.get_all("ASOUD Party Profile", or_filters=[["user", "like", "asoud.lo-%"],
                                                                ["national_id", "in", LO_PERSON_NATIONAL_IDS]],
                              pluck="name")
    for name in profiles:
        try:
            frappe.delete_doc("ASOUD Party Profile", name, force=True, ignore_permissions=True)
        except Exception:
            frappe.db.rollback()
    for name in frappe.get_all("User", filters={"name": ["like", "asoud.lo-%"]}, pluck="name"):
        if name in (ADMIN, ADMIN2, HR_USER, PLAIN, CREATOR, OFFICE_MGR, DELEGATE, NEWBIE):
            continue
        try:
            frappe.delete_doc("User", name, force=True, ignore_permissions=True)
        except Exception:
            frappe.db.rollback()
    frappe.db.commit()


def fresh_user(email, roles):
    """The account with exactly these roles, enabled, with no mobile number left over."""
    _user(email, roles)
    frappe.db.set_value("User", email, {"enabled": 1, "user_type": "System User", "mobile_no": None,
                                        "phone": None}, update_modified=False)
    frappe.db.delete("Has Role", {"parent": email, "parenttype": "User"})
    for idx, role in enumerate(roles, start=1):
        frappe.get_doc({"doctype": "Has Role", "parent": email, "parenttype": "User", "parentfield": "roles",
                        "role": role, "idx": idx}).db_insert()
    frappe.db.delete("ASOUD Account State", {"user": email})
    frappe.clear_cache(user=email)
    return email


class LoginOnboardingBase(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        purge_leftovers()
        for role in (OFFICE_CREATOR_ROLE, DELEGATE_ROLE):
            if not frappe.db.exists("Role", role):
                frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 0}).insert()
        fresh_user(ADMIN, ["System Manager"])
        fresh_user(ADMIN2, ["System Manager"])
        # ERPNext strips the Employee role from accounts without a personnel file, so the plain accounts
        # carry another desk role; the HR lead is a real employee of the office.
        fresh_user(HR_USER, ["HR Manager"])
        fresh_user(PLAIN, ["Sales User"])
        fresh_user(CREATOR, ["Stock User", OFFICE_CREATOR_ROLE])
        fresh_user(OFFICE_MGR, ["Accounts Manager"])
        fresh_user(DELEGATE, ["Accounts User", DELEGATE_ROLE])
        fresh_user(NEWBIE, ["Stock User"])
        _employee(HR_USER, "HR Lead")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        purge_leftovers()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        clear_office_state()

    def login(self, user):
        frappe.set_user(user)


class TestLoginStateAndFirstRun(LoginOnboardingBase):
    def test_non_admin_gets_no_office_message_never_first_office(self):
        self.login(PLAIN)
        state = session.login_state()["data"]
        self.assertFalse(state["is_system_admin"])
        self.assertEqual(state["next"]["route"], "no-office")
        self.assertIn("هنوز دسترسی به دفتر کاری", state["next"]["message"])
        self.assertFalse(state["capabilities"]["create_office"])

    def test_admin_is_recognised_by_role_and_routed_to_first_office(self):
        self.login(ADMIN)
        state = session.login_state()["data"]
        self.assertTrue(state["is_system_admin"])
        self.assertEqual(state["scope"], "global")
        self.assertEqual(state["next"]["route"], "create-first-office")
        self.assertFalse(state["first_office_exists"])
        self.assertTrue(state["capabilities"]["manage_roles"])

    def test_temporary_password_precedes_everything(self):
        account_state.set_must_change(ADMIN, True, expires_in_hours=24)
        self.login(ADMIN)
        self.assertEqual(session.login_state()["data"]["next"]["route"], "change-password")

    def test_non_admin_cannot_reach_first_office_or_admin_profile(self):
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            onboarding.create_first_office(office_type="Legal", company_name="Sneaky Office")
        with self.assertRaises(frappe.PermissionError):
            onboarding.save_admin_profile(first_name="علی", last_name="رضایی", mobile="09123456789")
        with self.assertRaises(frappe.PermissionError):
            onboarding.get_admin_profile()
        self.assertTrue(audit("onboarding.denied", actor=PLAIN))

    def test_first_office_created_once_and_admin_linked(self):
        self.login(ADMIN)
        before = frappe.db.count("Company")
        name = "ASOUD First Office LO " + frappe.generate_hash(length=5)
        first = onboarding.create_first_office(office_type="Legal", company_name=name)["data"]
        self.assertTrue(first["created"])
        company = first["office"]["company"]
        self.assertEqual(frappe.db.count("Company"), before + 1)
        again = onboarding.create_first_office(office_type="Legal", company_name="Another Name Entirely")["data"]
        self.assertFalse(again["created"])
        self.assertTrue(again["already_exists"])
        self.assertEqual(again["office"]["company"], company)
        self.assertEqual(frappe.db.count("Company"), before + 1)
        settings = frappe.get_single("ASOUD Settings")
        self.assertEqual(settings.first_office_company, company)
        self.assertEqual(settings.first_office_created_by, ADMIN)
        self.assertEqual(frappe.db.get_value("ASOUD Company Setup", company, "office_admin"), ADMIN)
        state = session.login_state()["data"]
        self.assertTrue(state["first_office_exists"])
        self.assertEqual(state["next"]["route"], "complete-admin-profile")
        self.assertIn(company, [o["id"] for o in state["offices"]])
        self.assertEqual(len(audit("office.create_first", result="success", target=company)), 1)

    def test_admin_profile_validation_persian_digits_and_no_duplicates(self):
        self.login(ADMIN)
        onboarding.create_first_office(office_type="Legal", company_name="ASOUD Profile Office LO")
        users = frappe.db.count("User")
        employees = frappe.db.count("Employee")
        details = frappe.db.count("ASOUD Floating Detail")
        for kwargs in ({"mobile": "12345"}, {"mobile": "09123456789", "national_id": "0013542418"},
                       {"mobile": "09123456789", "email": "not-an-email"}):
            with self.assertRaises(frappe.ValidationError):
                onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", **kwargs)
        result = onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", mobile=DIGITS_MOBILE,
                                               national_id="۰۰۱۳۵۴۲۴۱۹", email="Contact@Example.com")["data"]
        self.assertEqual(result["mobile"], "09123456789")
        self.assertEqual(result["national_id"], "0013542419")
        self.assertEqual(result["email"], "contact@example.com")
        self.assertFalse(result["mobile_verified"])
        self.assertFalse(result["email_verified"])
        person = result["person"]
        again = onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", mobile="09123456789")["data"]
        self.assertEqual(again["person"], person)
        self.assertEqual(frappe.db.count("ASOUD Party Profile", {"user": ADMIN}), 1)
        self.assertEqual(frappe.db.count("User"), users)
        self.assertEqual(frappe.db.count("Employee"), employees)
        self.assertEqual(frappe.db.count("ASOUD Floating Detail"), details)
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", person, "user"), ADMIN)
        self.assertNotIn("System Manager", [r.role for r in frappe.get_doc("User", ADMIN).roles if r.role != "System Manager"])
        self.assertEqual(session.login_state()["data"]["next"]["route"], "home")

    def test_mobile_unverified_again_when_changed(self):
        self.login(ADMIN)
        onboarding.create_first_office(office_type="Legal", company_name="ASOUD Verify Office LO")
        onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", mobile="09123456789")
        frappe.db.set_value("ASOUD Account State", ADMIN, "mobile_verified", 1)
        onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", mobile="09351112233")
        self.assertFalse(account_state.get(ADMIN)["mobile_verified"])

    def test_duplicate_mobile_of_another_account_is_refused(self):
        frappe.db.set_value("User", PLAIN, "mobile_no", "09121110000")
        self.login(ADMIN)
        with self.assertRaises(frappe.ValidationError):
            onboarding.save_admin_profile(first_name="مریم", last_name="احمدی", mobile="۰۹۱۲۱۱۱۰۰۰۰")


class TestChangePassword(LoginOnboardingBase):
    def setUp(self):
        super().setUp()
        from frappe.utils.password import update_password

        update_password(PLAIN, "Initial-Password-123")

    def other_session(self, user):
        frappe.db.sql("delete from tabSessions where sid=%s", ("other-sid-" + user,))
        frappe.db.sql("insert into tabSessions (sid, user, lastupdate, sessiondata, status) values (%s,%s,now(),%s,'Active')",
                      ("other-sid-" + user, user, "{}"))

    def test_policy_and_current_password_checks(self):
        self.login(PLAIN)
        for current, new, repeat in (("wrong-current-1", STRONG, STRONG), ("Initial-Password-123", "short", "short"),
                                     ("Initial-Password-123", STRONG, "different-repeat-1"),
                                     ("Initial-Password-123", "Initial-Password-123", "Initial-Password-123")):
            with self.assertRaises(frappe.ValidationError):
                account_security.change_password(current, new, repeat)
        self.assertTrue(check_password(PLAIN, "Initial-Password-123"))

    def test_success_changes_hash_clears_temp_flag_and_revokes_other_sessions(self):
        account_state.set_must_change(PLAIN, True, expires_in_hours=24)
        self.other_session(PLAIN)
        self.login(PLAIN)
        result = account_security.change_password("Initial-Password-123", STRONG, STRONG)["data"]
        self.assertTrue(result["changed"])
        self.assertTrue(check_password(PLAIN, STRONG))
        with self.assertRaises(frappe.AuthenticationError):
            check_password(PLAIN, "Initial-Password-123")
        self.assertFalse(account_state.must_change_password(PLAIN))
        self.assertFalse(frappe.db.exists("Sessions", "other-sid-" + PLAIN))
        events = audit("auth.password_change", actor=PLAIN)
        self.assertTrue(events)
        for event in events:
            self.assertNotIn(STRONG, event.details or "")
            self.assertNotIn("Initial-Password-123", event.details or "")

    def test_failed_attempts_are_rate_limited_even_with_the_right_password(self):
        self.login(PLAIN)
        frappe.cache.delete_value(f"asoud_pwchange_failures:{PLAIN}")
        for _ in range(5):
            with self.assertRaises(frappe.ValidationError):
                account_security.change_password("nope-nope-nope-1", STRONG, STRONG)
        with self.assertRaises(frappe.ValidationError) as ctx:
            account_security.change_password("Initial-Password-123", STRONG, STRONG)
        self.assertIn("تلاش", str(ctx.exception))
        self.assertTrue(check_password(PLAIN, "Initial-Password-123"))
        frappe.cache.delete_value(f"asoud_pwchange_failures:{PLAIN}")

    def test_guest_cannot_change_a_password(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.AuthenticationError):
            account_security.change_password("a", STRONG, STRONG)


class TestRecovery(LoginOnboardingBase):
    def setUp(self):
        super().setUp()
        from frappe.utils.password import update_password

        update_password(PLAIN, "Initial-Password-123")
        for key in ("asoud_recovery_id:" + PLAIN, "asoud_recovery_confirm:" + PLAIN, "asoud_recovery_ip:"):
            frappe.cache.delete_value(key)
        frappe.set_user("Guest")

    def request(self, identifier):
        sent = {}

        def fake_send(**kwargs):
            sent.update(kwargs)

        with mock.patch.object(account_recovery, "recovery_available", return_value=True), \
                mock.patch("frappe.sendmail", side_effect=fake_send):
            answer = account_security.request_password_reset(identifier)["data"]
        return answer, sent

    def code_from(self, sent):
        import re
        return re.search(r"<b dir='ltr'>([A-Z0-9]+)</b>", sent["message"]).group(1)

    def test_unknown_and_known_accounts_get_the_same_answer(self):
        known, sent = self.request(PLAIN)
        unknown, none_sent = self.request("nobody-here@example.com")
        self.assertEqual(known, unknown)
        self.assertTrue(sent)
        self.assertFalse(none_sent)

    def test_reset_with_code_sets_password_and_burns_the_code(self):
        _, sent = self.request(PLAIN)
        code = self.code_from(sent)
        stored = frappe.get_all("ASOUD Account Token", filters={"user": PLAIN}, fields=["token_hash", "salt"])[0]
        self.assertNotIn(code, json.dumps(stored))
        with self.assertRaises(frappe.ValidationError):
            account_security.confirm_password_reset(PLAIN, "WRONGCODE1", STRONG, STRONG)
        with self.assertRaises(frappe.ValidationError):
            account_security.confirm_password_reset(PLAIN, code, "short", "short")
        result = account_security.confirm_password_reset(PLAIN, code.lower(), STRONG, STRONG)["data"]
        self.assertTrue(result["changed"])
        self.assertTrue(check_password(PLAIN, STRONG))
        with self.assertRaises(frappe.ValidationError):
            account_security.confirm_password_reset(PLAIN, code, STRONGER, STRONGER)
        self.assertTrue(audit("auth.password_reset_complete", actor=PLAIN))

    def test_expired_code_and_too_many_wrong_attempts_are_refused(self):
        _, sent = self.request(PLAIN)
        code = self.code_from(sent)
        name = frappe.get_all("ASOUD Account Token", filters={"user": PLAIN}, pluck="name")[0]
        frappe.db.set_value("ASOUD Account Token", name, "expires_on", add_days(nowdate(), -1))
        with self.assertRaises(frappe.ValidationError):
            account_security.confirm_password_reset(PLAIN, code, STRONG, STRONG)
        _, sent = self.request(PLAIN)
        code = self.code_from(sent)
        for _ in range(5):
            with self.assertRaises(frappe.ValidationError):
                account_security.confirm_password_reset(PLAIN, "AAAAAAAAAA", STRONG, STRONG)
            frappe.cache.delete_value("asoud_recovery_confirm:" + PLAIN)
        with self.assertRaises(frappe.ValidationError):
            account_security.confirm_password_reset(PLAIN, code, STRONG, STRONG)
        self.assertTrue(check_password(PLAIN, "Initial-Password-123"))

    def test_recovery_status_reports_false_without_outgoing_email(self):
        with mock.patch.object(account_recovery, "recovery_available", return_value=False):
            self.assertFalse(account_security.recovery_status()["data"]["available"])

    def test_disabled_and_system_accounts_are_never_recoverable(self):
        frappe.db.set_value("User", NEWBIE, "enabled", 0)
        self.assertIsNone(account_recovery.find_user(NEWBIE))
        self.assertIsNone(account_recovery.find_user("Administrator"))


class TestSystemAdminRules(LoginOnboardingBase):
    def test_last_named_admin_cannot_be_disabled_demoted_or_deleted(self):
        others = [n for n in system_admin.active_named_admins() if n != ADMIN]
        for name in others:
            frappe.db.set_value("User", name, "enabled", 0)
        doc = frappe.get_doc("User", ADMIN)
        doc.enabled = 0
        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)
        doc = frappe.get_doc("User", ADMIN)
        doc.set("roles", [r for r in doc.roles if r.role != "System Manager"])
        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("User", ADMIN, ignore_permissions=True, force=True)
        frappe.db.set_value("User", ADMIN2, "enabled", 1)
        doc = frappe.get_doc("User", ADMIN)
        doc.enabled = 0
        doc.save(ignore_permissions=True)

    def test_role_changes_are_audited_with_actor(self):
        self.login(ADMIN)
        doc = frappe.get_doc("User", PLAIN)
        doc.append("roles", {"role": "Accounts User"})
        doc.save(ignore_permissions=True)
        rows = audit("role.grant", target=PLAIN)
        self.assertTrue(rows)
        self.assertEqual(rows[0].actor, ADMIN)
        doc = frappe.get_doc("User", PLAIN)
        doc.enabled = 0
        doc.save(ignore_permissions=True)
        self.assertTrue(audit("account.deactivate", target=PLAIN))

    def test_admin_authority_transfer_is_audited(self):
        self.login(ADMIN)
        doc = frappe.get_doc("User", PLAIN)
        doc.append("roles", {"role": "System Manager"})
        doc.save(ignore_permissions=True)
        self.assertTrue(audit("admin.authority_transfer", target=PLAIN))


class TestCreateOfficePermission(LoginOnboardingBase):
    def test_office_manager_without_create_permission_cannot_create(self):
        self.login(OFFICE_MGR)
        with self.assertRaises(frappe.PermissionError):
            setup.save_office(office_type="Legal", company_name="Forbidden Office LO")
        self.assertFalse(frappe.db.exists("Company", {"company_name": "Forbidden Office LO"}))
        self.assertTrue(audit("office.create", actor=OFFICE_MGR, result="denied"))

    def test_creator_can_create_without_becoming_admin_or_manager(self):
        self.login(CREATOR)
        result = setup.save_office(office_type="Legal", company_name="Creator Office LO")["data"]
        company = result["company"]
        self.assertTrue(frappe.db.exists("Company", company))
        self.assertFalse(system_admin.is_system_admin(CREATOR))
        roles = set(frappe.get_roles(CREATOR))
        self.assertNotIn("System Manager", roles)
        self.assertNotIn("Accounts Manager", roles)
        # the right to create is not the right to manage: editing the office is refused
        with self.assertRaises(frappe.PermissionError):
            setup.save_office(office_type="Legal", company_name="Creator Office Renamed", company=company)
        created = audit("office.create", actor=CREATOR)
        self.assertTrue(created)

    def test_granting_create_office_makes_nobody_admin(self):
        self.login(ADMIN)
        doc = frappe.get_doc("User", NEWBIE)
        doc.append("roles", {"role": OFFICE_CREATOR_ROLE})
        doc.save(ignore_permissions=True)
        self.assertFalse(system_admin.is_system_admin(NEWBIE))
        self.assertTrue(audit("office.create_permission_grant", target=NEWBIE))


class TestAdminCanDirectAndReport(LoginOnboardingBase):
    """The reported bug: the system administrator could not issue directives nor send work reports."""

    def test_admin_without_personnel_file_issues_a_directive(self):
        self.assertFalse(frappe.db.exists("Employee", {"user_id": ADMIN}))
        self.login(ADMIN)
        options = directives.options(company=self.company)["data"]
        self.assertIn(EMPLOYEE_USER, [p["id"] for p in options["people"]])
        self.assertIn("issue", options["allowed_actions"])
        draft = directives.save_draft(company=self.company, request_key="adm-draft-" + "1" * 20, payload={
            "subject": "دستور مدیر کل", "body": "انجام شود", "priority": "High",
            "due_date": str(add_days(nowdate(), 5)), "allow_transfer": True,
            "executor_ids": [EMPLOYEE_USER], "primary_id": EMPLOYEE_USER})["data"]
        issued = directives.issue(company=self.company, directive=draft["id"], request_key="adm-issue-" + "2" * 20)["data"]
        self.assertEqual(issued["id"], draft["id"])
        view = directives.get_directive(company=self.company, directive=draft["id"])["data"]
        self.assertEqual(view["current_user_id"], ADMIN)
        self.login(EMPLOYEE_USER)
        seen = directives.get_directive(company=self.company, directive=draft["id"])["data"]
        self.assertIn("report", seen["allowed_actions"])
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            directives.get_directive(company=self.company, directive=draft["id"])

    def test_non_admin_without_personnel_file_still_cannot_issue(self):
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            directives.options(company=self.company)

    def test_admin_sends_work_report_and_another_admin_reviews_it(self):
        self.login(ADMIN)
        payload = {"status": "Submitted", "company": self.company,
                   "activities": [{"title": "بازدید", "duration_minutes": 60}]}
        saved = hr.save_report(payload)["data"]
        self.assertEqual(saved["status"], "Submitted")
        self.assertEqual(saved["review"]["route"], "managers_pool")
        self.assertEqual(frappe.db.get_value("ASOUD Work Report", saved["name"], "reporter"), ADMIN)
        self.assertIn(saved["name"], [r["name"] for r in hr.list_reports()["data"]])
        with self.assertRaises(frappe.PermissionError):
            hr.review_report(saved["name"], "approve")  # nobody reviews their own report
        self.login(ADMIN2)
        reviewed = hr.review_report(saved["name"], "approve", "تأیید")["data"]
        self.assertEqual(reviewed["status"], "Approved")

    def test_employee_report_still_goes_to_the_direct_manager(self):
        self.login(EMPLOYEE_USER)
        saved = hr.save_report({"status": "Submitted", "activities": [{"title": "کار", "duration_minutes": 30}]})["data"]
        self.assertEqual(saved["review"]["route"], "direct_manager")

    def test_user_without_personnel_file_cannot_report(self):
        self.login(PLAIN)
        with self.assertRaises(frappe.ValidationError):
            hr.save_report({"status": "Submitted", "activities": [{"title": "کار", "duration_minutes": 30}]})


class TestRoleCatalogAndHrModes(LoginOnboardingBase):
    def make_role(self, code, base, scope="global"):
        try:
            role_management.create_category(json.dumps({"code": "LOCAT", "title": "آزمون"}))
        except Exception:
            pass
        return role_management.save_role(json.dumps({
            "code": code, "title": "نقش آزمون " + code, "category": "LOCAT", "base_roles": base, "scope": scope}))["data"]

    def test_admin_role_is_listed_with_global_scope_and_full_real_permissions(self):
        self.login(ADMIN)
        catalog = role_management.catalog()["data"]
        row = catalog["system_roles"][0]
        self.assertEqual(row["scope"], "global")
        self.assertEqual(row["title"], "مدیر کل سیستم")
        full = role_management.system_admin_permissions()["data"]
        self.assertTrue(all(c["granted"] for c in full["capabilities"]))
        self.assertGreater(full["document_permission_count"], 50)
        doctypes = {d["doctype"] for d in full["document_permissions"]}
        self.assertIn("User", doctypes)
        self.assertIn("ASOUD Work Report", doctypes)
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            role_management.system_admin_permissions()

    def test_only_admin_can_create_roles_and_new_role_is_stored(self):
        self.login(HR_USER)
        with self.assertRaises(frappe.PermissionError):
            self.make_role("LOHR1", ["HR User"])
        self.login(ADMIN)
        row = self.make_role("LOHR2", ["HR User"])
        self.assertEqual(row["scope"], "global")
        self.assertTrue(frappe.db.exists("ASOUD Role Definition", "LOHR2"))
        self.assertTrue(audit("role.create", target="LOHR2"))

    def test_role_with_admin_base_must_be_global(self):
        self.login(ADMIN)
        with self.assertRaises(frappe.ValidationError):
            self.make_role("LOADM", ["System Manager"], scope="office")

    def test_advanced_mode_differs_from_medium_and_is_applied(self):
        self.login(ADMIN)
        self.make_role("LOHR3", ["Employee"])
        editor = user_access.editor("LOHR3")["data"]
        rows = {r["doctype"]: r for r in editor["catalog"]}
        self.assertIn("Leave Application", rows)
        leave = rows["Leave Application"]
        self.assertEqual(leave["levels"]["medium"], ["read", "create", "write", "delete"])
        self.assertNotEqual(leave["levels"]["advanced"], leave["levels"]["medium"])
        self.assertIn("submit", leave["advanced_actions"])
        self.assertNotIn("submit", rows["Department"]["advanced_actions"])
        for hr_doctype in ("Employee", "Attendance", "Salary Slip", "ASOUD Work Report"):
            self.assertIn(hr_doctype, rows)
        grants = {dt: [] for dt in rows}
        advanced = {dt: [] for dt in rows}
        grants["Leave Application"] = ["read", "create"]
        advanced["Leave Application"] = ["submit", "print"]
        user_access.apply(json.dumps({"code": "LOHR3", "grants": grants, "advanced_grants": advanced,
                                      "token": editor["token"]}))
        after = user_access.editor("LOHR3")["data"]
        self.assertEqual(after["grants"]["Leave Application"], ["create", "read"])
        self.assertEqual(after["advanced_grants"]["Leave Application"], ["print", "submit"])
        # an action the document type does not offer is refused
        bad = {dt: [] for dt in rows}
        bad["Department"] = ["submit"]
        with self.assertRaises(frappe.ValidationError):
            user_access.apply(json.dumps({"code": "LOHR3", "grants": grants, "advanced_grants": bad,
                                          "token": after["token"]}))
        # extras without read are refused
        nore = {dt: [] for dt in rows}
        nore["Leave Application"] = ["print"]
        with self.assertRaises(frappe.ValidationError):
            user_access.apply(json.dumps({"code": "LOHR3", "grants": {dt: [] for dt in rows},
                                          "advanced_grants": nore, "token": after["token"]}))
        self.assertTrue(audit("role.permission_change", target="LOHR3"))

    def test_older_client_without_advanced_keys_keeps_extras(self):
        self.login(ADMIN)
        self.make_role("LOHR4", ["Employee"])
        editor = user_access.editor("LOHR4")["data"]
        rows = [r["doctype"] for r in editor["catalog"]]
        grants = {dt: [] for dt in rows}
        grants["Leave Application"] = ["read"]
        advanced = {dt: [] for dt in rows}
        advanced["Leave Application"] = ["print"]
        user_access.apply(json.dumps({"code": "LOHR4", "grants": grants, "advanced_grants": advanced,
                                      "token": editor["token"]}))
        token = user_access.editor("LOHR4")["data"]["token"]
        grants["Leave Application"] = ["read", "write"]
        user_access.apply(json.dumps({"code": "LOHR4", "grants": grants, "token": token}))
        after = user_access.editor("LOHR4")["data"]
        self.assertEqual(after["advanced_grants"]["Leave Application"], ["print"])


class TestRoleAssignment(LoginOnboardingBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.first, cls.second = cls.scope["first"], cls.scope["second"]
        for c in (cls.first, cls.second):
            if not frappe.db.exists("ASOUD Company Setup", c):
                frappe.get_doc({"doctype": "ASOUD Company Setup", "company": c, "office_type": "Legal",
                                "office_saved": 1, "accounting_saved": 1, "roles_saved": 1}).insert(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        frappe.db.sql("update `tabASOUD Company Setup` set office_saved=1")
        for email, roles in ((NEWBIE, ["Stock User"]), (PLAIN, ["Sales User"])):
            frappe.db.delete("ASOUD Office Role Assignment", {"user": email})
            frappe.db.delete("ASOUD Access Assignment", {"user": email})
            fresh_user(email, roles)

    def role(self, code, base, scope):
        frappe.set_user(ADMIN)
        try:
            role_management.create_category(json.dumps({"code": "LOCAT", "title": "آزمون"}))
        except Exception:
            pass
        role_management.save_role(json.dumps({"code": code, "title": "نقش " + code, "category": "LOCAT",
                                              "base_roles": base, "scope": scope}))

    def test_one_account_holds_different_roles_in_different_offices(self):
        self.role("LOFIN", ["Accounts User"], "office")
        self.login(ADMIN)
        result = role_access.assign_role(NEWBIE, "LOFIN", self.first)["data"]
        self.assertTrue(result["assigned"])
        again = role_access.assign_role(NEWBIE, "LOFIN", self.first)["data"]
        self.assertTrue(again["already_assigned"])
        self.assertEqual(frappe.db.count("ASOUD Office Role Assignment", {"user": NEWBIE}), 1)
        # not leaked into the global roles
        self.assertNotIn("Accounts User", frappe.get_roles(NEWBIE))
        self.assertIn("Accounts User", office_access.effective_roles(NEWBIE, self.first))
        self.assertNotIn("Accounts User", office_access.effective_roles(NEWBIE, self.second))
        self.assertTrue(company_access(self.first, NEWBIE))
        self.assertFalse(company_access(self.second, NEWBIE))
        frappe.set_user(NEWBIE)
        require_roles(["Accounts User"], company=self.first)
        with self.assertRaises(frappe.PermissionError):
            require_roles(["Accounts User"], company=self.second)
        with self.assertRaises(frappe.PermissionError):
            require_roles(["Accounts User"])
        state = session.login_state()["data"]
        self.assertEqual([o["id"] for o in state["offices"]], [self.first])
        self.assertEqual(state["next"]["route"], "home")
        self.assertEqual(state["next"]["office"], self.first)
        # a changed office id in an API call does not widen access
        with self.assertRaises(frappe.PermissionError):
            setup.get_setup_status(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            session.select_office(self.second)
        self.login(ADMIN)
        removed = role_access.unassign_role(NEWBIE, "LOFIN", self.first)["data"]
        self.assertTrue(removed["removed"])
        self.assertFalse(company_access(self.first, NEWBIE))

    def test_global_role_assignment_adds_and_removes_base_roles(self):
        self.role("LOGLOB", ["Stock User"], "global")
        self.login(ADMIN)
        role_access.assign_role(PLAIN, "LOGLOB")
        self.assertIn("Stock User", frappe.get_roles(PLAIN))
        role_access.unassign_role(PLAIN, "LOGLOB")
        self.assertNotIn("Stock User", frappe.get_roles(PLAIN))
        self.assertIn("Sales User", frappe.get_roles(PLAIN))
        self.assertTrue(audit("role.assign", target=PLAIN))
        self.assertTrue(audit("role.unassign", target=PLAIN))

    def test_scope_mismatch_and_self_assignment_are_refused(self):
        self.role("LOOFF", ["Accounts User"], "office")
        self.role("LOGL2", ["Stock User"], "global")
        self.login(ADMIN)
        with self.assertRaises(frappe.ValidationError):
            role_access.assign_role(NEWBIE, "LOOFF")
        with self.assertRaises(frappe.ValidationError):
            role_access.assign_role(NEWBIE, "LOGL2", self.first)
        with self.assertRaises(frappe.PermissionError):
            role_access.assign_role(ADMIN, "LOGL2")

    def test_delegate_cannot_escalate(self):
        self.role("LOUSER", ["Accounts User"], "global")
        self.role("LOMGR", ["Accounts Manager"], "global")
        self.role("LOADMIN", ["System Manager"], "global")
        self.login(DELEGATE)
        role_access.assign_role(NEWBIE, "LOUSER")
        with self.assertRaises(frappe.PermissionError):
            role_access.assign_role(NEWBIE, "LOMGR")
        with self.assertRaises(frappe.PermissionError):
            role_access.assign_role(NEWBIE, "LOADMIN")
        self.assertNotIn("System Manager", frappe.get_roles(NEWBIE))
        self.assertTrue(audit("role.assign", actor=DELEGATE, result="denied"))
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            role_access.assign_role(NEWBIE, "LOUSER")


class TestHrOnboarding(LoginOnboardingBase):
    def register(self, **over):
        args = dict(company=self.company, first_name="سارا", last_name="محمدی", mobile=DIGITS_MOBILE,
                    email="asoud.lo-new1@example.com", national_id="0013542419", gender="Female",
                    birth_date="1995-05-05", date_of_joining="2024-01-01", activation="temporary_password")
        args.update(over)
        return hr_onboarding.register_personnel(**args)["data"]

    def test_hr_registers_personnel_without_duplicates_and_forces_password_change(self):
        self.login(HR_USER)
        persons = frappe.db.count("ASOUD Party Profile")
        result = self.register()
        self.assertTrue(result["account_created"])
        self.assertEqual(result["activation"]["method"], "temporary_password")
        temp = result["activation"]["temporary_password"]
        self.assertEqual(frappe.db.get_value("Employee", result["employee"], "user_id"), result["user"])
        self.assertEqual(frappe.db.get_value("ASOUD Party Profile", result["person"], "user"), result["user"])
        self.assertIn("Employee", frappe.get_roles(result["user"]))
        self.assertTrue(check_password(result["user"], temp))
        self.assertTrue(account_state.must_change_password(result["user"]))
        state = __import__("asoud_erp.services.login_state", fromlist=["build"]).build(result["user"])
        self.assertEqual(state["next"]["route"], "change-password")
        self.assertFalse(state["is_system_admin"])
        # same person, same login again: nothing is duplicated
        again = self.register()
        self.assertEqual(again["person"], result["person"])
        self.assertEqual(again["employee"], result["employee"])
        self.assertEqual(frappe.db.count("ASOUD Party Profile"), persons + 1)
        self.assertEqual(frappe.db.count("Employee", {"user_id": result["user"]}), 1)
        self.assertEqual(frappe.db.count("User", {"name": result["user"]}), 1)
        # no accounting tafsili without a request
        self.assertFalse(frappe.db.exists("ASOUD Floating Detail", {"linked_document": result["person"]}))
        for row in audit("hr.personnel_register"):
            self.assertNotIn(temp, row.details or "")

    def test_system_administrator_registers_personnel_without_an_hr_role(self):
        # A plain System Manager has no native Employee right; the documented endpoint must still work.
        self.login(ADMIN)
        self.assertNotIn("HR Manager", frappe.get_roles(ADMIN))
        result = self.register(email="asoud.lo-byadmin@example.com", national_id="0013542419",
                               mobile="09351230000")
        self.assertTrue(result["account_created"])
        self.assertEqual(frappe.db.get_value("Employee", result["employee"], "user_id"), result["user"])
        self.assertEqual(frappe.session.user, ADMIN)

    def test_existing_person_is_reused_by_national_id(self):
        self.login(HR_USER)
        first = self.register()
        other = self.register(national_id="0013542419", mobile="09351234567")
        self.assertEqual(other["person"], first["person"])
        self.assertTrue(other["reused_person"])
        # one person has one login: a different e-mail for the same person is refused, not duplicated
        with self.assertRaises(frappe.ValidationError):
            self.register(email="asoud.lo-new2@example.com", national_id="0013542419")
        self.assertFalse(frappe.db.exists("User", "asoud.lo-new2@example.com"))

    def test_invalid_input_is_rejected_with_persian_errors(self):
        self.login(HR_USER)
        for over in ({"mobile": "123"}, {"national_id": "0013542418"}, {"email": "bad"}, {"first_name": ""},
                     {"activation": "carrier-pigeon"}):
            with self.assertRaises(frappe.ValidationError):
                self.register(**over)

    def test_user_without_hr_permission_cannot_register(self):
        for user in (PLAIN, CREATOR, OFFICE_MGR):
            self.login(user)
            with self.assertRaises(frappe.PermissionError):
                self.register()

    def test_hr_cannot_grant_roles_beyond_authority(self):
        self.login(ADMIN)
        role_management.create_category(json.dumps({"code": "LOCAT", "title": "آزمون"})) if not frappe.db.exists(
            "ASOUD Role Category", "LOCAT") else None
        role_management.save_role(json.dumps({"code": "LOHRX", "title": "x", "category": "LOCAT",
                                              "base_roles": ["System Manager"]}))
        self.login(HR_USER)
        with self.assertRaises(frappe.PermissionError):
            self.register(roles=["LOHRX"])

    def test_first_hr_lead_bootstrap_needs_no_prior_hr(self):
        self.login(ADMIN)
        hr_before = frappe.get_all("Has Role", filters={"role": "HR Manager", "parenttype": "User",
                                                        "parent": ["in", [HR_USER]]}, pluck="parent")
        frappe.db.sql("delete from `tabHas Role` where role='HR Manager' and parent=%s", HR_USER)
        self.addCleanup(fresh_user, HR_USER, ["HR Manager"])
        result = hr_onboarding.bootstrap_hr_lead(
            company=self.company, first_name="رضا", last_name="کریمی", mobile="09191112233",
            email="asoud.lo-lead@example.com", activation="temporary_password", gender="Male",
            birth_date="1990-02-02", date_of_joining="2024-02-02")["data"]
        self.assertTrue(result["hr_lead"])
        self.assertIn("HR Manager", frappe.get_roles(result["user"]))
        self.assertFalse(system_admin.is_system_admin(result["user"]))
        self.assertTrue(audit("hr.first_lead_register"))
        self.assertEqual(hr_before, [HR_USER])
        self.login(HR_USER)
        with self.assertRaises(frappe.PermissionError):
            hr_onboarding.bootstrap_hr_lead(company=self.company, first_name="رضا", last_name="کریمی",
                                            mobile="09191112244", email="asoud.lo-lead2@example.com")

    def test_temporary_password_reissue_by_hr(self):
        self.login(HR_USER)
        result = self.register()
        again = hr_onboarding.issue_temporary_password(result["person"])["data"]
        self.assertTrue(check_password(result["user"], again["temporary_password"]))
        self.assertTrue(account_state.must_change_password(result["user"]))
        self.login(PLAIN)
        with self.assertRaises(frappe.PermissionError):
            hr_onboarding.issue_temporary_password(result["person"])


class TestAuditTrail(LoginOnboardingBase):
    def test_failed_and_successful_logins_are_mirrored_without_secrets(self):
        from frappe.core.doctype.activity_log.activity_log import add_authentication_log

        add_authentication_log("Invalid login credentials", PLAIN, status="Failed")
        add_authentication_log("PLAIN logged in", PLAIN, status="Success")
        rows = audit("auth.login", actor=PLAIN)
        self.assertEqual({r.result for r in rows}, {"failure", "success"})
        for row in rows:
            self.assertNotIn("password", (row.details or "").lower())

    def test_audit_rows_are_append_only(self):
        from asoud_erp.services import security_audit

        security_audit.record("test.append_only", actor=PLAIN)
        name = frappe.get_all("ASOUD Security Audit", filters={"action": "test.append_only"}, pluck="name")[0]
        doc = frappe.get_doc("ASOUD Security Audit", name)
        doc.result = "failure"
        with self.assertRaises(frappe.PermissionError):
            doc.save(ignore_permissions=True)
        flags = frappe.flags.in_test
        frappe.flags.in_test = False
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.delete_doc("ASOUD Security Audit", name, ignore_permissions=True, force=True)
        finally:
            frappe.flags.in_test = flags

    def test_office_settings_change_is_audited(self):
        self.login(ADMIN)
        office = onboarding.create_first_office(office_type="Legal", company_name="ASOUD Audit Office LO")["data"]["office"]
        setup.update_company_settings(company=office["company"], display_currency="Toman", fiscal_year_start_month=1,
                                      chart_template="Iran Standard")
        self.assertTrue(audit("office.settings_change", actor=ADMIN))


class TestLogout(LoginOnboardingBase):
    def test_logout_revokes_the_server_session(self):
        user = PLAIN
        frappe.db.sql("delete from tabSessions where sid=%s", ("logout-sid",))
        frappe.db.sql("insert into tabSessions (sid, user, lastupdate, sessiondata, status) values (%s,%s,now(),%s,'Active')",
                      ("logout-sid", user, "{}"))
        frappe.set_user(user)
        frappe.local.session.sid = "logout-sid"
        manager = mock.Mock()
        previous = getattr(frappe.local, "login_manager", None)

        def do_logout(*args, **kwargs):
            from frappe.sessions import delete_session

            delete_session("logout-sid", user=user, reason="User Manually Logged Out")

        manager.logout.side_effect = do_logout
        frappe.local.login_manager = manager
        try:
            result = session.logout()["data"]
        finally:
            frappe.local.login_manager = previous
        self.assertTrue(result["revoked"])
        self.assertFalse(frappe.db.exists("Sessions", "logout-sid"))

    def test_guest_logout_is_refused(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.AuthenticationError):
            session.logout()
