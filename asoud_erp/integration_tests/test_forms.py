"""Versioned forms and calendar records remain inside the caller's company."""

import json

import frappe
from frappe.utils import now_datetime

from asoud_erp.api.v1 import calendar, forms
from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.integration_tests.tenancy import MANAGER_USER, setup_tenancy


def schema(title="فرم آزمایشی"):
    return {
        "kind": "Request",
        "title": title,
        "sections": [{"id": "main", "title": "اصلی", "fields": [
            {"key": "amount", "label": "مبلغ", "type": "Money", "required": True},
            {"key": "priority", "label": "اولویت", "type": "Select", "required": True,
             "options": [{"id": "normal", "label": "عادی"}, {"id": "urgent", "label": "فوری"}]},
        ]}],
    }


def document_schema(title="سند آزمایشی"):
    return {
        "kind": "Document",
        "target": "Journal Entry",
        "title": title,
        "sections": [{
            "id": "main",
            "title": "اصلی",
            "fields": [
                {"key": "posting_date", "label": "تاریخ ثبت", "type": "Date", "native_key": "posting_date"},
                {"key": "accounts", "label": "ردیف‌ها", "type": "Table", "native_key": "accounts", "columns": [
                    {"key": "debit", "label": "مبلغ", "type": "Money", "native_key": "debit_in_account_currency"},
                ]},
            ],
        }],
    }


class TestForms(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope = setup_tenancy()
        cls.second = cls.scope["second"]

    def test_draft_publish_revision_and_entry_are_company_scoped(self):
        created = forms.save_form(company=self.company, schema=schema(), client_id="a" * 24)["data"]
        self.assertEqual(created["status"], "Draft")
        self.assertEqual(forms.list_forms(company=self.company, manage=1)["data"][0]["name"], created["name"])

        published = forms.transition(name=created["name"], action="publish", expected_version=1)["data"]
        first_revision = published["active_revision"]
        self.assertEqual(published["version"], 1)

        updated_schema = schema("فرم بازبینی‌شده")
        revised = forms.save_form(name=created["name"], company=self.company, schema=updated_schema,
                                  expected_version=published["draft_version"])["data"]
        published = forms.transition(name=created["name"], action="publish",
                                     expected_version=revised["draft_version"])["data"]
        self.assertNotEqual(published["active_revision"], first_revision)
        self.assertEqual(forms.get_form(name=created["name"])["data"]["revision"], published["active_revision"])

        frappe.set_user(MANAGER_USER)
        entry = forms.submit_form(name=created["name"], revision_name=published["active_revision"],
                                  subject="ثبت آزمایشی", values={"amount": "125", "priority": "normal"},
                                  request_key="b" * 24)["data"]
        self.assertEqual(forms.get_entry(entry["name"])["data"]["values"]["priority"], "normal")
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.second)

    def test_form_extensions_validate_submission_and_employee_defaults(self):
        employee_user = "asoud.form-extensions@example.com"
        if not frappe.db.exists("User", employee_user):
            frappe.get_doc({
                "doctype": "User", "email": employee_user, "first_name": "Form extensions",
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Employee"}],
            }).insert(ignore_permissions=True)
        employee_name = frappe.db.get_value("Employee", {"user_id": employee_user, "company": self.company}, "name")
        if not employee_name:
            employee_name = frappe.get_doc({
                "doctype": "Employee", "first_name": "Form extensions", "gender": "Male",
                "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-02",
                "company": self.company, "status": "Active", "user_id": employee_user,
                "create_user_permission": 0,
            }).insert(ignore_permissions=True).name
        frappe.db.set_value("Employee", employee_name, "designation", "کارشناس منابع انسانی")

        extension_schema = {
            "kind": "Request", "title": "فرم امکانات جدید", "schema_version": 2,
            "sections": [{
                "id": "main", "title": "اصلی", "description": "راهنمای بخش", "icon": "event",
                "color": "blue", "background_color": "#e3f2fd", "collapsible": True,
                "collapsed": False,
                "fields": [
                    {"key": "designation", "label": "سمت", "type": "Text", "readonly": True,
                     "default_source": "designation", "help": "از پرونده پرسنلی"},
                    {"key": "joining_date", "label": "تاریخ استخدام", "type": "Date", "readonly": True,
                     "default_source": "joining_date"},
                    {"key": "start_date", "label": "تاریخ شروع", "type": "Date", "required": True},
                    {"key": "end_date", "label": "تاریخ پایان", "type": "Date", "required": True,
                     "after_or_equal": "start_date"},
                    {"key": "priority", "label": "اولویت", "type": "Select", "style": "radio",
                     "options": [{"id": "normal", "label": "عادی"}, {"id": "urgent", "label": "فوری"}]},
                    {"key": "items", "label": "اقلام", "type": "Table", "required": True, "min_rows": 2,
                     "columns": [{"key": "name", "label": "نام", "type": "Text", "required": True}]},
                ],
            }],
        }
        frappe.set_user("Administrator")
        created = forms.save_form(company=self.company, schema=extension_schema, client_id="e" * 24)["data"]
        published = forms.transition(name=created["name"], action="publish", expected_version=1)["data"]

        frappe.set_user(employee_user)
        consumed = forms.get_form(name=created["name"])["data"]["schema"]["sections"][0]["fields"]
        defaults = {field["key"]: field.get("default") for field in consumed}
        self.assertEqual(defaults["designation"], "کارشناس منابع انسانی")
        self.assertEqual(defaults["joining_date"], "2020-01-02")

        with self.assertRaisesRegex(frappe.ValidationError, "حداقل 2 ردیف لازم است"):
            forms.submit_form(
                name=created["name"], revision_name=published["active_revision"], subject="ثبت نامعتبر",
                values={"start_date": "2026-10-23", "end_date": "2026-10-23", "priority": "normal",
                        "items": [{"name": "الف"}]}, request_key="e" * 24,
            )
        with self.assertRaisesRegex(frappe.ValidationError, "تاریخ پایان نباید قبل از تاریخ شروع باشد"):
            forms.submit_form(
                name=created["name"], revision_name=published["active_revision"], subject="ثبت ترتیب نامعتبر",
                values={"start_date": "2026-10-23", "end_date": "2026-10-22", "priority": "normal",
                        "items": [{"name": "الف"}, {"name": "ب"}]}, request_key="g" * 24,
            )
        entry = forms.submit_form(
            name=created["name"], revision_name=published["active_revision"], subject="ثبت معتبر",
            values={"start_date": "2026-10-23", "end_date": "2026-10-23", "priority": "normal",
                    "items": [{"name": "الف"}, {"name": "ب"}]}, request_key="f" * 24,
        )["data"]
        self.assertIsNotNone(entry["name"])

    def test_employee_consumption_and_permission_boundaries(self):
        # 1. Active employee with only the Employee role
        emp_user = "asoud.form-employee@example.com"
        if not frappe.db.exists("User", emp_user):
            frappe.get_doc({
                "doctype": "User", "email": emp_user, "first_name": "Form employee",
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Employee"}],
            }).insert(ignore_permissions=True)
        if not frappe.db.exists("Employee", {"user_id": emp_user}):
            frappe.get_doc({
                "doctype": "Employee", "first_name": "Form employee", "gender": "Male",
                "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01",
                "company": self.company, "status": "Active", "user_id": emp_user,
                "create_user_permission": 0,
            }).insert(ignore_permissions=True)

        # 2. User without an active Employee record in this company
        stranger_user = "asoud.form-stranger@example.com"
        if not frappe.db.exists("User", stranger_user):
            frappe.get_doc({
                "doctype": "User", "email": stranger_user, "first_name": "Form stranger",
                "send_welcome_email": 0, "user_type": "System User",
                "roles": [{"role": "Employee"}],
            }).insert(ignore_permissions=True)

        # 3. Publish a Request form and a Document form as Administrator
        frappe.set_user("Administrator")
        req_form = forms.save_form(company=self.company, schema=schema("فرم درخواست پرسنلی"), client_id="r" * 24)["data"]
        published_req = forms.transition(name=req_form["name"], action="publish", expected_version=1)["data"]

        doc_form = forms.save_form(company=self.company, schema=document_schema("فرم سند حسابداری"), client_id="d" * 24)["data"]
        published_doc = forms.transition(name=doc_form["name"], action="publish", expected_version=1)["data"]

        # 4. As an Employee-only user:
        frappe.set_user(emp_user)

        # a) CAN list published forms
        published_req_names = [f["name"] for f in forms.list_forms(company=self.company, kind="Request")["data"]]
        self.assertIn(req_form["name"], published_req_names)

        published_doc_names = [f["name"] for f in forms.list_forms(company=self.company, kind="Document")["data"]]
        self.assertIn(doc_form["name"], published_doc_names)

        # b) CAN submit a Request form and read own entries
        entry = forms.submit_form(
            name=req_form["name"],
            revision_name=published_req["active_revision"],
            subject="درخواست اداری پرسنل",
            values={"amount": "250", "priority": "urgent"},
            request_key="k" * 24,
        )["data"]
        self.assertIsNotNone(entry["name"])

        read_entry = forms.get_entry(entry["name"])["data"]
        self.assertEqual(read_entry["subject"], "درخواست اداری پرسنل")
        self.assertEqual(read_entry["values"]["amount"], "250")

        my_entries = [e["name"] for e in forms.list_my_entries(company=self.company)["data"]]
        self.assertIn(entry["name"], my_entries)

        # c) CAN use the personal calendar
        cal_res = calendar.save_personal(
            company=self.company,
            payload={
                "id": "1" * 24, "mutation_id": "2" * 24, "kind": "Reminder",
                "title": "یادآوری کارمند", "date": "2026-10-22",
            },
        )
        self.assertTrue(cal_res["data"]["saved"])
        cal_items = calendar.get_calendar(company=self.company, start="2026-10-22", end="2026-10-22")["data"]["items"]
        self.assertTrue(any(item["id"] == "1" * 24 for item in cal_items))

        # d) CANNOT call designer/management operations
        with self.assertRaises(frappe.PermissionError):
            forms.save_form(company=self.company, schema=schema("فرم غیرمجاز"), client_id="x" * 24)
        with self.assertRaises(frappe.PermissionError):
            forms.transition(name=req_form["name"], action="disable", expected_version=1)
        with self.assertRaises(frappe.PermissionError):
            forms.get_history(name=req_form["name"])
        with self.assertRaises(frappe.PermissionError):
            calendar.save_holiday(company=self.company, payload={"id": "3" * 24, "title": "تعطیلی", "date": "2026-10-22"})

        # e) CANNOT read another company's forms
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.second)
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.second, start="2026-10-22", end="2026-10-22")

        # f) For document forms: employee without native permission on target DocType is refused by ERPNext
        with self.assertRaises(frappe.PermissionError):
            forms.submit_form(
                name=doc_form["name"],
                revision_name=published_doc["active_revision"],
                subject="ثبت سند مالی",
                values={
                    "posting_date": "2026-10-22",
                    "accounts": [{"debit": "100"}],
                },
                request_key="doc-k-" + "4" * 20,
            )

        # 5. A user who is not an active employee of the company is refused
        frappe.set_user(stranger_user)
        with self.assertRaises(frappe.PermissionError):
            forms.list_forms(company=self.company)
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.company, start="2026-10-22", end="2026-10-22")

    def test_legacy_schema_migrated_on_read_and_revisions_stay_immutable(self):
        legacy_schema = {
            "kind": "Request",
            "title": "فرم قدیمی",
            "schema_version": 1,
            "sections": [{"id": "main", "title": "اصلی", "fields": [
                {"key": "amount", "label": "مبلغ", "type": "Money", "required": True},
                {"key": "priority", "label": "اولویت", "type": "Select", "required": True,
                 "options": ["عادی", "فوری"]},
            ]}],
        }
        form_name = "test_legacy_form_migrate"
        if frappe.db.exists("ASOUD Form", form_name):
            frappe.db.delete("ASOUD Form Revision", {"form": form_name})
            frappe.db.delete("ASOUD Form", {"name": form_name})
        form_doc = frappe.get_doc({
            "doctype": "ASOUD Form",
            "name": form_name,
            "company": self.company,
            "title": "فرم قدیمی",
            "kind": "Request",
            "module_key": "General",
            "draft_version": 1,
            "draft_json": json.dumps(legacy_schema, ensure_ascii=False),
        })
        form_doc.flags.form_service = True
        form_doc.insert(ignore_permissions=True, set_name=form_name)

        rev = frappe.get_doc({
            "doctype": "ASOUD Form Revision",
            "form": form_doc.name,
            "version": 1,
            "schema_json": json.dumps(legacy_schema, ensure_ascii=False),
            "published_by": "Administrator",
            "published_on": now_datetime(),
        })
        rev.flags.form_service = True
        rev.insert(ignore_permissions=True)
        form_doc.active_revision = rev.name
        form_doc.save(ignore_permissions=True)

        read_form = forms.get_form(name=form_doc.name)["data"]
        self.assertEqual(read_form["schema"]["schema_version"], 2)
        options = read_form["schema"]["sections"][0]["fields"][1]["options"]
        self.assertEqual(options, [
            {"id": "option_0_1_0", "label": "عادی"},
            {"id": "option_0_1_1", "label": "فوری"},
        ])

        managed = forms.list_forms(company=self.company, manage=1)["data"]
        legacy_row = next(r for r in managed if r["name"] == form_doc.name)
        self.assertEqual(legacy_row["schema"]["schema_version"], 2)

        frappe.set_user(MANAGER_USER)
        entry_doc = frappe.get_doc({
            "doctype": "ASOUD Form Entry",
            "form": form_doc.name,
            "revision": rev.name,
            "company": self.company,
            "subject": "ثبت قدیمی",
            "values_json": json.dumps({"amount": "200", "priority": "عادی"}, ensure_ascii=False),
            "request_key": "c" * 32,
            "fingerprint": "d" * 32,
        })
        entry_doc.flags.form_service = True
        entry_doc.insert(ignore_permissions=True)

        read_entry = forms.get_entry(entry_doc.name)["data"]
        self.assertEqual(read_entry["schema"]["schema_version"], 2)
        self.assertEqual(read_entry["values"]["priority"], "option_0_1_0")

        rev_db = frappe.get_doc("ASOUD Form Revision", rev.name)
        self.assertEqual(json.loads(rev_db.schema_json)["sections"][0]["fields"][1]["options"], ["عادی", "فوری"])
        entry_db = frappe.get_doc("ASOUD Form Entry", entry_doc.name)
        self.assertEqual(json.loads(entry_db.values_json)["priority"], "عادی")

    def test_saving_legacy_schema_stores_version_two(self):
        legacy_schema = {
            "kind": "Request",
            "title": "فرم ذخیره قدیمی",
            "schema_version": 1,
            "sections": [{"id": "main", "title": "اصلی", "fields": [{
                "key": "priority", "label": "اولویت", "type": "Select",
                "options": ["عادی", "فوری"],
            }]}],
        }
        saved = forms.save_form(
            company=self.company,
            schema=legacy_schema,
            client_id="legacy-save-" + "s" * 20,
        )["data"]
        stored = json.loads(frappe.get_doc("ASOUD Form", saved["name"]).draft_json)
        self.assertEqual(stored["schema_version"], 2)
        self.assertEqual(stored["sections"][0]["fields"][0]["options"], [
            {"id": "option_0_0_0", "label": "عادی"},
            {"id": "option_0_0_1", "label": "فوری"},
        ])



class TestCalendarCompanyScope(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.second = setup_tenancy()["second"]

    def test_personal_scope_is_private_and_second_company_is_refused(self):
        frappe.set_user(MANAGER_USER)
        calendar.save_personal(company=self.company, payload={
            "id": "1" * 24, "mutation_id": "2" * 24, "kind": "Reminder", "title": "پیگیری آزمایشی",
            "date": "2026-10-20", "time": "09:00",
        })
        items = calendar.get_calendar(company=self.company, start="2026-10-20", end="2026-10-20")["data"]["items"]
        self.assertEqual([(item["id"], item["title"]) for item in items if item["id"] == "1" * 24],
                         [("1" * 24, "پیگیری آزمایشی")])
        with self.assertRaises(frappe.PermissionError):
            calendar.get_calendar(company=self.second, start="2026-10-20", end="2026-10-20")


def _scope_user(email, first_name):
    from asoud_erp.integration_tests.fixtures import _employee, _user
    _user(email, ["Employee"])
    return _employee(email, first_name)


class TestFormRecordSources(APITestCase):
    """Record sources are scoped to the signed-in Employee (contract C8-C14)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_tenancy()

    def setUp(self):
        super().setUp()
        self.me_user = "asoud.src-me@example.com"
        self.other_user = "asoud.src-other@example.com"
        self.me = _scope_user(self.me_user, "Src Me")
        self.other = _scope_user(self.other_user, "Src Other")

    def attendance(self, employee, day, **extra):
        doc = frappe.get_doc({"doctype": "Attendance", "employee": employee, "status": "Present",
                              "attendance_date": day, "company": self.company, **extra})
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Attendance", doc.name, "docstatus", 1)
        return doc.name

    def asset(self, custodian, label):
        item = frappe.get_all("Item", pluck="name", limit=1)[0]
        location = frappe.db.exists("Location", "ASOUD Src Location") or frappe.get_doc(
            {"doctype": "Location", "location_name": "ASOUD Src Location"}).insert(ignore_permissions=True).name
        doc = frappe.get_doc({"doctype": "Asset", "asset_name": label, "item_code": item, "company": self.company,
                              "location": location, "custodian": custodian, "purchase_date": "2026-01-01",
                              "available_for_use_date": "2026-01-01", "gross_purchase_amount": 100})
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Asset", doc.name, "docstatus", 1)
        return doc.name

    def publish(self, fields):
        frappe.set_user("Administrator")
        self.published = getattr(self, "published", 0) + 1
        created = forms.save_form(company=self.company, client_id=f"s{self.published}".ljust(24, "s"), schema={
            "kind": "Request", "title": "منابع رکورد", "schema_version": 2,
            "sections": [{"id": "main", "title": "اصلی", "fields": fields}]})["data"]
        published = forms.transition(name=created["name"], action="publish", expected_version=1)["data"]
        return created["name"], published["active_revision"]

    def submit(self, name, revision, values, key):
        return forms.submit_form(name=name, revision_name=revision, subject="ثبت منبع", values=values, request_key=key)

    def link(self, key, source, **extra):
        return {"key": key, "label": key, "type": "Link", "source": source, **extra}

    def test_attendance_scope_extra_and_submit_rejection(self):
        mine = self.attendance(self.me, "2026-09-01", in_time="2026-09-01 08:15:00")
        theirs = self.attendance(self.other, "2026-09-02")
        name, rev = self.publish([self.link("att", "Attendance"),
            {"key": "in_t", "label": "ورود", "type": "Time", "readonly": True, "fetch_from": "att.in_time"}])
        frappe.set_user(self.me_user)
        rows = forms.get_link_options(company=self.company, source="Attendance", form=name)["data"]
        self.assertEqual([r["name"] for r in rows], [mine])
        self.assertEqual(rows[0]["extra"]["status"], "Present")
        self.assertEqual(rows[0]["extra"]["in_time"], "2026-09-01T08:15:00")
        self.assertEqual(rows[0]["extra"]["attendance_date"], "2026-09-01")
        with self.assertRaisesRegex(frappe.ValidationError, "محدوده مجاز شما نیست"):
            self.submit(name, rev, {"att": theirs}, "a" * 24)
        entry = self.submit(name, rev, {"att": mine, "in_t": "23:00:00"}, "b" * 24)["data"]["name"]
        # the client-supplied derived value is replaced by the database value
        self.assertEqual(forms.get_entry(entry)["data"]["values"]["in_t"], "08:15:00")

    def test_no_employee_user_gets_empty_list_with_reason(self):
        name, rev = self.publish([self.link("att", "Attendance"), self.link("ast", "Asset")])
        # Administrator has no Employee record, like many managers
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.exists("Employee", {"user_id": "Administrator", "company": self.company}))
        att = forms.get_link_options(company=self.company, source="Attendance", form=name)
        self.assertEqual((att["data"], att["meta"]["reason"]), ([], "no_employee"))
        result = forms.get_link_options(company=self.company, source="Asset", form=name)
        self.assertEqual(result["data"], [])
        self.assertEqual(result["meta"]["reason"], "no_employee")

    def test_asset_custodian_scope(self):
        mine = self.asset(self.me, "لپ‌تاپ من")
        theirs = self.asset(self.other, "لپ‌تاپ دیگری")
        name, rev = self.publish([self.link("ast", "Asset"),
            {"key": "loc", "label": "مکان", "type": "Text", "readonly": True, "fetch_from": "ast.asset_name"}])
        frappe.set_user(self.me_user)
        rows = forms.get_link_options(company=self.company, source="Asset", form=name)["data"]
        self.assertEqual([r["name"] for r in rows], [mine])
        self.assertEqual(rows[0]["extra"]["asset_name"], "لپ‌تاپ من")
        with self.assertRaisesRegex(frappe.ValidationError, "محدوده مجاز شما نیست"):
            self.submit(name, rev, {"ast": theirs}, "c" * 24)
        entry = self.submit(name, rev, {"ast": mine}, "d" * 24)["data"]["name"]
        self.assertEqual(forms.get_entry(entry)["data"]["values"]["loc"], "لپ‌تاپ من")

    def test_training_event_future_scheduled_only_and_shift_type(self):
        def event(title, status, days):
            start = frappe.utils.add_days(frappe.utils.now_datetime(), days)
            doc = frappe.get_doc({"doctype": "Training Event", "event_name": title, "event_status": status,
                "type": "Seminar", "location": "تهران", "introduction": "x", "company": self.company,
                "start_time": start, "end_time": frappe.utils.add_days(start, 1),
                "employees": [{"employee": self.me}]})
            doc.flags.ignore_validate = True
            return doc.insert(ignore_permissions=True, ignore_mandatory=True).name
        future = event("دوره آینده", "Scheduled", 5)
        past = event("دوره گذشته", "Scheduled", -5)
        done = event("دوره تمام‌شده", "Completed", 5)
        shift = frappe.get_doc({"doctype": "Shift Type", "name": "ASOUD Src Shift", "start_time": "08:00:00",
                                "end_time": "16:30:00"}).insert(ignore_permissions=True).name
        name, rev = self.publish([self.link("ev", "Training Event"), self.link("sh", "Shift Type")])
        frappe.set_user(self.me_user)
        names = [r["name"] for r in forms.get_link_options(company=self.company, source="Training Event", form=name)["data"]]
        self.assertIn(future, names)
        self.assertNotIn(past, names)
        self.assertNotIn(done, names)
        with self.assertRaisesRegex(frappe.ValidationError, "محدوده مجاز شما نیست"):
            self.submit(name, rev, {"ev": past}, "e" * 24)
        shifts = {r["name"]: r for r in forms.get_link_options(company=self.company, source="Shift Type", form=name)["data"]}
        self.assertEqual(shifts[shift]["extra"], {"start_time": "08:00:00", "end_time": "16:30:00"})

    def test_exclude_self_not_equal_and_unique(self):
        plain_name, _ = self.publish([self.link("pick", "Employee")])
        name, rev = self.publish([
            self.link("boss", "Employee", exclude_self=True),
            {"key": "old", "label": "قدیم", "type": "Text"},
            {"key": "new", "label": "جدید", "type": "Text", "not_equal": "old"},
            {"key": "num", "label": "پرسنلی", "type": "Text", "readonly": True, "default_source": "employee_number"},
            {"key": "rows", "label": "ردیف", "type": "Table", "columns": [{"key": "n", "label": "نام", "type": "Text", "unique": True}]}])
        frappe.set_user(self.me_user)
        options = [r["name"] for r in forms.get_link_options(company=self.company, source="Employee", form=name, exclude_self=1)["data"]]
        self.assertNotIn(self.me, options)
        self.assertIn(self.other, options)
        with self.assertRaisesRegex(frappe.ValidationError, "حذف خود را پشتیبانی نمی"):
            forms.get_link_options(company=self.company, source="Employee", form=plain_name, exclude_self=1)
        with self.assertRaisesRegex(frappe.ValidationError, "نمی‌توانید خودتان را انتخاب کنید"):
            self.submit(name, rev, {"boss": self.me}, "f" * 24)
        with self.assertRaisesRegex(frappe.ValidationError, "مقدار جدید نباید با مقدار فعلی یکسان باشد"):
            self.submit(name, rev, {"old": "x", "new": "x"}, "g" * 24)
        with self.assertRaisesRegex(frappe.ValidationError, "ردیف تکراری: نام"):
            self.submit(name, rev, {"rows": [{"n": "a"}, {"n": "a"}]}, "h" * 24)
        entry = self.submit(name, rev, {"boss": self.other, "old": "x", "new": "y", "rows": [{"n": "a"}, {"n": "b"}]}, "i" * 24)["data"]["name"]
        self.assertEqual(forms.get_entry(entry)["data"]["values"]["boss"], self.other)
        self.assertTrue(forms.get_entry(entry)["data"]["values"]["num"])
