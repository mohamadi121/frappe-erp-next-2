"""Integration tests for the LLM-facing layer (Gemloy client, tool catalog,
orchestrator) on a real site.

The pure tests (``asoud_erp/tests/test_ai_assistant.py``) cover the loop, the
caps, the masking and the request shape with a fake transport. Here we prove the
things that only a real site can prove:

- every catalog method is a real, ``@frappe.whitelisted`` read method that
  ``sync.py`` does not treat as a mutation;
- the default executor runs the whitelisted method in the acting user's session
  (the acting user is the principal) and refuses when the session user differs
  (no privilege elevation);
- the orchestrator drives a real read method end to end with a fake client.

No live model call is made: the orchestrator is driven with a fake client.
"""

import frappe

from asoud_erp.api.v1 import sync
from asoud_erp.integration_tests.fixtures import APPROVER_USER, EMPLOYEE_USER, APITestCase
from asoud_erp.services.ai import orchestrator, tool_catalog


class _FakeClient:
    """Routes one tool call, then answers. Records every call for assertions."""

    def __init__(self, tool_name):
        self.tool_name = tool_name
        self.calls = []

    def create_message(self, messages, **kwargs):
        self.calls.append(kwargs)
        if not self.calls:
            return {"content": [{"type": "tool_use", "id": "toolu_1",
                                 "name": self.tool_name, "input": {}}]}
        return {"content": [{"type": "text", "text": "پاسخ"}]}


class TestAiAssistant(APITestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user(EMPLOYEE_USER)

    def test_catalog_methods_are_real_whitelisted_read_methods(self):
        for entry in tool_catalog.catalog():
            method = entry["method"]
            module_path, _, func_name = method.rpartition(".")
            module = frappe.get_module(module_path)
            func = getattr(module, func_name, None)
            self.assertIsNotNone(func, f"{method} is not a real function")
            self.assertTrue(getattr(func, "whitelisted", False), f"{method} is not whitelisted")
            self.assertFalse(sync._is_mutation(method), f"{method} is a mutation, not read-only")
            self.assertEqual(entry["risk"], "read")

    def test_default_executor_runs_in_the_acting_users_session(self):
        # The acting user is the employee and the session user is the same, so
        # the whitelisted read method runs and returns the v1 envelope.
        executor = orchestrator._default_executor(EMPLOYEE_USER)
        result = executor("asoud_erp.api.v1.hr_self_service.get_my_leave_summary", {})
        self.assertTrue(result["ok"])
        self.assertIn("balances", result["data"])

    def test_default_executor_refuses_a_different_session_user(self):
        # The session user is the approver but the acting user is the employee:
        # the executor must refuse rather than run as the session user.
        frappe.set_user(APPROVER_USER)
        executor = orchestrator._default_executor(EMPLOYEE_USER)
        with self.assertRaises(PermissionError):
            executor("asoud_erp.api.v1.hr_self_service.get_my_leave_summary", {})

    def test_orchestrator_drives_a_real_read_method_end_to_end(self):
        # A fake client routes one tool call to a real read method (the
        # employee's own support issues) and then answers. The real default
        # executor runs it in the employee's session.
        client = _FakeClient("list_my_issues")
        result = orchestrator.run_assistant("تیکت‌های من", EMPLOYEE_USER, client,
                                            tool_catalog.catalog())
        self.assertEqual(result["stop_reason"], "end_turn")
        self.assertEqual(result["answer"], "پاسخ")
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertTrue(result["tool_calls"][0]["ok"])
        # The tool result went back to the model as a tool_result block.
        tool_result = client.calls[1]["messages"][-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertFalse(tool_result["is_error"])
