"""Integration test for the optional ``agent`` field on ASOUD Security Audit.

Runs on an installed site (CI only — no local bench). Proves that
``security_audit.record(..., agent=...)`` writes a row whose ``agent`` column
carries the value while ``actor`` stays the principal, and that the default
path (no ``agent``) leaves the column empty so existing rows and queries are
untouched.

``record`` is called with ``commit=False`` (the default), so each row lives in
the test transaction and is rolled back in ``tearDown``; unique action names
keep a run isolated from any stale row a previously interrupted run committed.
"""

import frappe

from asoud_erp.integration_tests.fixtures import APITestCase
from asoud_erp.services import security_audit


class TestSecurityAuditAgent(APITestCase):
    def test_record_with_agent_sets_agent_and_keeps_actor_principal(self):
        action = f"test.agent_row.{frappe.generate_hash(length=8)}"
        security_audit.record(action, actor="principal@example.com", agent="my-agent")
        row = frappe.get_all(
            "ASOUD Security Audit",
            filters={"action": action},
            fields=["actor", "agent", "result"],
            limit=1,
        )[0]
        self.assertEqual(row.agent, "my-agent")
        self.assertEqual(row.actor, "principal@example.com")
        self.assertEqual(row.result, "success")

    def test_record_default_leaves_agent_empty(self):
        action = f"test.agent_default.{frappe.generate_hash(length=8)}"
        security_audit.record(action, actor="principal@example.com")
        row = frappe.get_all(
            "ASOUD Security Audit",
            filters={"action": action},
            fields=["actor", "agent"],
            limit=1,
        )[0]
        self.assertEqual(row.actor, "principal@example.com")
        # No agent passed: the column must be empty (None or ""), not a stray value.
        self.assertIn(row.agent, (None, ""))
