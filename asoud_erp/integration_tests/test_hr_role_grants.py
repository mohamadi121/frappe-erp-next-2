"""HR authority cannot be delegated through any public grant entry point."""

from uuid import uuid4

import frappe

from asoud_erp.api.v1 import hr_onboarding, role_access, role_management, user_access
from asoud_erp.integration_tests.fixtures import APITestCase, _employee, _user, company
from asoud_erp.integration_tests.tenancy import setup_tenancy
from asoud_erp.services.delegation import DELEGATE_ROLE


class TestHRRoleGrants(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def test_hr_grants_require_system_administrator_across_all_three_entry_points(self):
        token = uuid4().hex[:10].upper()
        if not frappe.db.exists("Role", DELEGATE_ROLE):
            frappe.get_doc({"doctype": "Role", "role_name": DELEGATE_ROLE}).insert()
        actor = _user(f"hr-granter-{token.lower()}@example.com", ["HR Manager", "HR User", DELEGATE_ROLE])
        _employee(actor, "واگذارکننده")
        category = "HG" + token
        role_management.create_category({"code": category, "title": "آزمون دسترسی منابع انسانی"})
        for scope in ("global", "office"):
            for native in ("HR User", "HR Manager"):
                with self.subTest(scope=scope, native=native):
                    frappe.set_user("Administrator")
                    code = "HG" + uuid4().hex[:10].upper()
                    role_management.save_role({"code": code, "title": "منابع انسانی", "category": category,
                                               "base_roles": [native], "scope": scope})
                    target = _user(f"hr-target-{uuid4().hex[:10]}@example.com", ["Sales User"])
                    scope_args = {"company": company()} if scope == "office" else {}
                    editor = user_access.editor(code, target)["data"]
                    payload = {"code": code, "user": target, "token": editor["token"],
                               "grants": editor["grants"], "advanced_grants": editor["advanced_grants"]}
                    mail = f"hr-register-{uuid4().hex[:10]}@example.com"
                    registration = dict(company=company(), first_name="سارا", last_name="رضایی",
                        mobile="0912" + str(int(uuid4().hex[:8], 16) % 10_000_000).zfill(7),
                        email=mail, gender="Female", birth_date="1995-01-01", date_of_joining="2024-01-01",
                        activation="temporary_password", roles=[code])
                    frappe.set_user(actor)
                    counts = {dt: frappe.db.count(dt) for dt in ("User", "Employee", "ASOUD Party Profile",
                              "ASOUD Access Assignment", "ASOUD Office Role Assignment")}
                    for call in (
                        lambda: role_access.assign_role(target, code, **scope_args),
                        lambda: user_access.apply(payload),
                        lambda: hr_onboarding.register_personnel(**registration),
                    ):
                        with self.assertRaises(frappe.PermissionError) as raised:
                            call()
                        self.assertRegex(str(raised.exception), r"[آ-ی]")
                    for dt, before in counts.items():
                        self.assertEqual(frappe.db.count(dt), before)
                    self.assertFalse(frappe.db.exists("User", mail))
                    frappe.set_user("Administrator")
                    result = role_access.assign_role(target, code, **scope_args)["data"]
                    self.assertTrue(result["assigned"])
                    if scope == "global":
                        self.assertIn(native, frappe.get_roles(target))
                        # The personal permission editor also grants through the
                        # definition's base profile, but remains administrator-only.
                        other = _user(f"hr-editor-{uuid4().hex[:10]}@example.com", ["Sales User"])
                        before = user_access.editor(code, other)["data"]
                        applied = user_access.apply({"code": code, "user": other, "token": before["token"],
                            "grants": before["grants"], "advanced_grants": before["advanced_grants"]})["data"]
                        self.assertTrue(applied["applied"])
                        self.assertIn(native, frappe.get_roles(other))
                    else:
                        self.assertTrue(frappe.db.exists("ASOUD Office Role Assignment", {
                            "user": target, "role_definition": code, "company": company()}))
                    registered = hr_onboarding.register_personnel(**registration)["data"]
                    self.assertEqual(registered["user"], mail)
                    self.assertEqual(len(registered["roles"]), 1)
