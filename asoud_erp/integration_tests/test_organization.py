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
