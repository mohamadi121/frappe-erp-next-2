"""Run on an installed Frappe/ERPNext/HRMS test site, not production."""
import json

import frappe

from asoud_erp.api.v1 import organization
from asoud_erp.integration_tests.fixtures import EMPLOYEE_USER, APITestCase


class TestOrganization(APITestCase):
    def test_assignment_history_preserves_explicit_native_manager(self):
        original_manager = frappe.db.get_value("Employee", self.records["employee"], "reports_to")
        current = organization.get_chart(self.company)["data"]
        code = "TEST-" + frappe.generate_hash(length=10)
        row = dict(code=code, title="Test position", capacity=2, occupants=[
            "employee:" + self.records["employee"], "employee:" + self.records["approver"]])
        saved = organization.save_chart(dict(company=self.company, revision=current["revision"],
            rows=[*current["rows"], row]))["data"]
        self.assertEqual(frappe.db.get_value("Employee", self.records["employee"], "reports_to"),
            original_manager)
        created = next(r for r in saved["rows"] if r["code"] == code)
        self.assertEqual(len(created["assignment_history"]), 2)
        rows = [dict(r, occupants=[]) if r["code"] == code else r for r in saved["rows"]]
        ended = organization.save_chart(dict(company=self.company, revision=saved["revision"], rows=rows))["data"]
        history = next(r for r in ended["rows"] if r["code"] == code)["assignment_history"]
        self.assertTrue(all(h["ended_at"] and h["ended_by"] == "Administrator" for h in history))
        self.assertEqual(frappe.db.get_value("Employee", self.records["employee"], "reports_to"),
            original_manager)
        with self.assertRaises(frappe.ValidationError):
            organization.save_chart(dict(company=self.company, revision=ended["revision"], rows=current["rows"]))

    def test_unit_reference_blocks_native_delete_and_rename(self):
        name = organization.save_unit(self.company, dict(
            title="Test unit " + frappe.generate_hash(length=10), is_group=True))["data"]["name"]
        current = organization.get_chart(self.company)["data"]
        organization.save_chart(dict(company=self.company, revision=current["revision"],
            rows=[*current["rows"], dict(code="TEST-"+frappe.generate_hash(length=8),
                title="Native-linked position", department_id=name, capacity=1, occupants=[])]))
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc("Department", name)
        with self.assertRaises(frappe.ValidationError):
            frappe.rename_doc("Department", name, "Changed-"+frappe.generate_hash(length=8))

    def test_employee_role_cannot_manage_structure(self):
        frappe.set_user(EMPLOYEE_USER)
        with self.assertRaises(frappe.PermissionError):
            organization.save_unit(self.company, dict(title="Unauthorized", is_group=True))

    def test_import_failure_rolls_back_native_units(self):
        current = organization.get_chart(self.company)["data"]
        title = "Import rollback " + frappe.generate_hash(length=8)
        payload = dict(units=[dict(code="U", title=title)], rows=[
            dict(code="P-"+frappe.generate_hash(length=8), title="Position",
                department_id="U", capacity=1, occupants=[])])
        preview = organization.preview_import(self.company, payload)["data"]
        unit_name = preview["units"][0]["name"]
        # Simulate a server validation failure after Department insertion.
        from unittest.mock import patch
        with patch.object(organization, "save_chart", side_effect=frappe.ValidationError("rejected")):
            with self.assertRaises(frappe.ValidationError):
                organization.apply_import(self.company, json.dumps(payload), current["revision"])
        self.assertFalse(frappe.db.exists("Department", unit_name))

    def test_employee_cannot_occupy_two_positions(self):
        current = organization.get_chart(self.company)["data"]
        employee = "employee:" + self.records["employee"]
        rows = [dict(code="TEST-" + frappe.generate_hash(length=8), title=f"Position {index}",
            capacity=1, occupants=[employee]) for index in range(2)]
        with self.assertRaises(frappe.ValidationError):
            organization.save_chart(dict(company=self.company, revision=current["revision"],
                rows=[*current["rows"], *rows]))
        self.assertEqual(organization.get_chart(self.company)["data"]["revision"], current["revision"])

    def test_title_rename_refused_while_legacy_rows_depend_on_it(self):
        title = "Legacy title " + frappe.generate_hash(length=8)
        name = organization.save_unit(self.company, dict(title=title, is_group=True))["data"]["name"]
        base = organization.get_chart(self.company)["data"]
        legacy = dict(code="TEST-" + frappe.generate_hash(length=8), title="Legacy position",
            department=title, capacity=1, occupants=[])
        organization.save_chart(dict(company=self.company, revision=base["revision"], rows=[*base["rows"], legacy]))

        def cleanup():
            chart = organization.get_chart(self.company)["data"]
            organization.save_chart(dict(company=self.company, revision=chart["revision"], rows=base["rows"]))
            unit = next(u for u in organization.list_units(self.company)["data"]["units"] if u["name"] == name)
            organization.delete_unit(self.company, name, str(unit["modified"]))

        self.addCleanup(cleanup)
        unit = next(u for u in organization.list_units(self.company)["data"]["units"] if u["name"] == name)
        with self.assertRaises(frappe.ValidationError):
            organization.save_unit(self.company, dict(name=name, modified=str(unit["modified"]),
                title="Renamed " + frappe.generate_hash(length=8), is_group=True))
        self.assertEqual(frappe.db.get_value("Department", name, "department_name"), title)

    def test_title_rename_allowed_for_id_linked_positions_and_shows_new_title(self):
        name = organization.save_unit(self.company, dict(
            title="Linked unit " + frappe.generate_hash(length=8), is_group=True))["data"]["name"]
        base = organization.get_chart(self.company)["data"]
        position = dict(code="TEST-" + frappe.generate_hash(length=8), title="Linked position",
            department_id=name, capacity=1, occupants=[])
        organization.save_chart(dict(company=self.company, revision=base["revision"], rows=[*base["rows"], position]))

        def cleanup():
            chart = organization.get_chart(self.company)["data"]
            organization.save_chart(dict(company=self.company, revision=chart["revision"], rows=base["rows"]))
            unit = next(u for u in organization.list_units(self.company)["data"]["units"] if u["name"] == name)
            organization.delete_unit(self.company, name, str(unit["modified"]))

        self.addCleanup(cleanup)
        unit = next(u for u in organization.list_units(self.company)["data"]["units"] if u["name"] == name)
        new_title = "Renamed " + frappe.generate_hash(length=8)
        organization.save_unit(self.company, dict(name=name, modified=str(unit["modified"]),
            title=new_title, is_group=True))
        chart = organization.get_chart(self.company)["data"]
        linked = next(r for r in chart["rows"] if r["code"] == position["code"])
        self.assertEqual(linked["department"], new_title)
