"""Pure tests for the LLM-facing layer (Gemloy client, tool catalog, orchestrator).

Everything runs against a fake transport and a fake executor: no network, no
Frappe site, no live model call. The catalog cross-check reads the real
``asoud_erp/api/v1`` sources (AST) and the real ``sync.py`` mutation rules, so
a renamed, un-whitelisted or write method in the catalog fails CI.
"""

import ast
import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

from asoud_erp.services.ai import gemloy_client, orchestrator, tool_catalog

REPO = Path(__file__).resolve().parents[2]


class FakeTransport:
    """Returns canned (status, headers, body) tuples, one per call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return self.responses.pop(0)


class ScriptedClient:
    """A GemloyClient stand-in that returns canned message responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create_message(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.responses.pop(0)


def _executor(result):
    calls = []

    def executor(method, args):
        calls.append((method, args))
        return result

    executor.calls = calls
    return executor


def _tool_use(name, tool_id, args=None):
    return {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args or {}}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------- the client


def test_create_message_builds_the_anthropic_request_shape():
    transport = FakeTransport([(200, {}, json.dumps(
        {"id": "msg_1", "content": [{"type": "text", "text": "سلام"}]}).encode())])
    client = gemloy_client.GemloyClient("https://gemma.example/", "key-123", transport=transport)
    client.create_message(
        [{"role": "user", "content": "سلام"}],
        system="سیستم", max_tokens=512, temperature=0.2,
        tools=[{"name": "t", "description": "d", "input_schema": {"type": "object"}}],
        tool_choice={"type": "auto"}, thinking={"type": "disabled"})
    call = transport.calls[0]
    assert call["url"] == "https://gemma.example/v1/messages"  # trailing slash stripped
    assert call["headers"]["x-api-key"] == "key-123"
    assert call["headers"]["content-type"] == "application/json"
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call["headers"]["request-id"])
    payload = json.loads(call["body"])
    assert payload["model"] == "gemma4-26b"
    assert payload["messages"] == [{"role": "user", "content": "سلام"}]
    assert payload["max_tokens"] == 512
    assert payload["temperature"] == 0.2
    assert payload["system"] == "سیستم"
    assert payload["tool_choice"] == {"type": "auto"}
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tools"][0]["name"] == "t"


def test_count_tokens_posts_to_the_count_endpoint():
    transport = FakeTransport([(200, {}, b'{"input_tokens": 42}')])
    client = gemloy_client.GemloyClient("https://gemma.example", "k", transport=transport)
    assert client.count_tokens([{"role": "user", "content": "سلام"}]) == 42
    assert transport.calls[0]["url"] == "https://gemma.example/v1/messages/count_tokens"


def test_extract_text_skips_a_leading_thinking_block():
    content = [
        {"type": "thinking", "thinking": "let me think", "signature": ""},
        {"type": "text", "text": "پاسخ"},
    ]
    assert gemloy_client.extract_text(content) == "پاسخ"
    assert gemloy_client.extract_text([{"type": "thinking", "thinking": "x"}]) == ""
    assert gemloy_client.extract_text([]) == ""
    assert gemloy_client.tool_use_blocks(content) == []


def test_429_rate_limit_error_retries_with_retry_after():
    sleeps = []
    transport = FakeTransport([
        (429, {"Retry-After": "3"},
         b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}'),
        (200, {}, json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()),
    ])
    client = gemloy_client.GemloyClient("https://x", "k", transport=transport, sleep=sleeps.append)
    result = client.create_message([{"role": "user", "content": "hi"}])
    assert result["content"][0]["text"] == "ok"
    assert len(transport.calls) == 2
    assert sleeps == [3.0]


def test_529_overloaded_error_retries():
    transport = FakeTransport([
        (529, {"Retry-After": "5"},
         b'{"type":"error","error":{"type":"overloaded_error","message":"loading"}}'),
        (200, {}, json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()),
    ])
    client = gemloy_client.GemloyClient("https://x", "k", transport=transport, sleep=lambda s: None)
    assert client.create_message([{"role": "user", "content": "hi"}])["content"][0]["text"] == "ok"
    assert len(transport.calls) == 2


def test_quota_exceeded_error_is_never_retried():
    transport = FakeTransport([
        (429, {}, b'{"type":"error","error":{"type":"quota_exceeded_error","message":"quota"}}'),
    ])
    client = gemloy_client.GemloyClient("https://x", "k", transport=transport, sleep=lambda s: None)
    with pytest.raises(gemloy_client.GemloyError) as exc:
        client.create_message([{"role": "user", "content": "hi"}])
    assert "سقف اعتبار" in str(exc.value)
    assert len(transport.calls) == 1  # no retry


def test_error_messages_are_persian_and_never_leak_the_key():
    transport = FakeTransport([(401, {},
                                b'{"type":"error","error":{"type":"authentication_error","message":"bad key-123"}}')])
    client = gemloy_client.GemloyClient("https://x", "key-123", transport=transport)
    with pytest.raises(gemloy_client.GemloyError) as exc:
        client.create_message([{"role": "user", "content": "hi"}])
    assert "key-123" not in str(exc.value)
    assert str(exc.value) == gemloy_client._UNAUTHORIZED


def test_from_site_config_without_a_key_raises_the_persian_error(monkeypatch):
    fake = types.ModuleType("frappe")
    fake.conf = {}
    monkeypatch.setitem(sys.modules, "frappe", fake)
    with pytest.raises(ValueError, match="دستیار هوشمند پیکربندی نشده است"):
        gemloy_client.GemloyClient.from_site_config()


def test_from_site_config_reads_the_site_config_keys(monkeypatch):
    fake = types.ModuleType("frappe")
    fake.conf = {"gemloy_base_url": "https://gemma.example", "gemloy_api_key": "k-1"}
    monkeypatch.setitem(sys.modules, "frappe", fake)
    client = gemloy_client.GemloyClient.from_site_config()
    assert client._base_url == "https://gemma.example"
    assert client._api_key == "k-1"


# ---------------------------------------------------------------- the catalog


def test_catalog_entries_are_valid_and_read_only():
    entries = tool_catalog.catalog()
    assert 1 <= len(entries) <= 12
    names = [entry["name"] for entry in entries]
    assert len(names) == len(set(names))
    for entry in entries:
        assert re.fullmatch(tool_catalog.TOOL_NAME_PATTERN, entry["name"])
        assert entry["risk"] == "read"
        assert entry["method"].startswith("asoud_erp.api.v1.")
        assert entry["description"]
        schema = entry["input_schema"]
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)
        assert isinstance(schema.get("required"), list)
        for key in schema["required"]:
            assert key in schema["properties"]
    # The pilot is read-only: support.create_issue is a write and must not be here.
    assert "asoud_erp.api.v1.support.create_issue" not in {entry["method"] for entry in entries}


def test_catalog_methods_exist_are_whitelisted_and_read_only():
    """Cross-check against the real sources: the method exists, is
    ``@frappe.whitelisted`` in the real file, and ``sync.py`` does not treat it
    as a mutation."""
    stub = types.ModuleType("frappe")
    stub.whitelist = lambda **kwargs: (lambda fn: fn)
    # Importing the real sync module binds it to this minimal frappe stub and
    # leaves it in sys.modules (and as an attribute on the v1 package). Both
    # must be restored exactly, or a later test that re-imports sync (e.g.
    # test_sync.py) would reuse this stub, which has no `throw`.
    saved_frappe = sys.modules.get("frappe")
    saved_sync = sys.modules.get("asoud_erp.api.v1.sync")
    parent = importlib.import_module("asoud_erp.api.v1")
    saved_attr = parent.__dict__.get("sync")
    sys.modules["frappe"] = stub
    try:
        sync = importlib.import_module("asoud_erp.api.v1.sync")
    finally:
        if saved_frappe is not None:
            sys.modules["frappe"] = saved_frappe
        else:
            sys.modules.pop("frappe", None)
        if saved_sync is not None:
            sys.modules["asoud_erp.api.v1.sync"] = saved_sync
        else:
            sys.modules.pop("asoud_erp.api.v1.sync", None)
        if saved_attr is not None:
            parent.sync = saved_attr
        else:
            parent.__dict__.pop("sync", None)

    for entry in tool_catalog.catalog():
        module_path, _, func_name = entry["method"].rpartition(".")
        _, _, leaf = module_path.rpartition(".")
        file = REPO / "asoud_erp" / "api" / "v1" / f"{leaf}.py"
        assert file.exists(), f"{entry['method']}: module file missing"
        tree = ast.parse(file.read_text(encoding="utf-8"))
        func = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == func_name), None)
        assert func is not None, f"{entry['method']}: function missing"
        whitelisted = any(
            isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "whitelist"
            and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "frappe"
            for dec in func.decorator_list)
        assert whitelisted, f"{entry['method']}: not @frappe.whitelisted"
        assert not sync._is_mutation(entry["method"]), \
            f"{entry['method']}: sync.py treats it as a mutation"


def test_anthropic_tools_shape_matches_the_wire_format():
    tools = tool_catalog.anthropic_tools()
    assert len(tools) == len(tool_catalog.catalog())
    for tool in tools:
        assert set(tool) == {"name", "description", "input_schema"}


# ------------------------------------------------------------- the orchestrator


def test_tool_use_round_trip_feeds_the_result_back():
    client = ScriptedClient([
        _tool_use("get_my_leave_summary", "toolu_1"),
        _text("routing done"),
        _text("پاسخ نهایی"),
    ])
    executor = _executor({"ok": True, "data": {"remaining": 5}})
    result = orchestrator.run_assistant("مجازیم چقدر است؟", "user@example.com",
                                        client, tool_catalog.catalog(), executor=executor)
    assert result["stop_reason"] == "end_turn"
    assert result["answer"] == "پاسخ نهایی"
    assert executor.calls == [("asoud_erp.api.v1.hr_self_service.get_my_leave_summary", {})]
    # The second model call must carry the assistant tool_use and the user tool_result.
    messages = client.calls[1]["messages"]
    assert messages[-2] == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_1", "name": "get_my_leave_summary", "input": {}}]}
    tool_result = messages[-1]["content"][0]
    assert messages[-1]["role"] == "user"
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["is_error"] is False
    assert "5" in tool_result["content"]
    # The first call routes with tools; the final answer call has no tools.
    assert client.calls[0]["tools"]
    assert not client.calls[2].get("tools")


def test_same_tool_and_args_twice_stops_with_the_persian_message():
    client = ScriptedClient([
        _tool_use("get_my_leave_summary", "toolu_1"),
        _tool_use("get_my_leave_summary", "toolu_2"),
    ])
    executor = _executor({"ok": True})
    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    assert result["stop_reason"] == "loop_guard"
    assert result["answer"] == orchestrator.LOOP_GUARD_MESSAGE
    assert len(executor.calls) == 1  # the duplicate was never executed


def test_same_tool_with_different_args_is_allowed():
    client = ScriptedClient([
        _tool_use("get_leave_balance", "toolu_1", {"company": "آ", "date": "2026-01-01"}),
        _tool_use("get_leave_balance", "toolu_2", {"company": "آ", "date": "2026-01-02"}),
        _text("routing done"),
        _text("پاسخ"),
    ])
    executor = _executor({"ok": True})
    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    assert result["stop_reason"] == "end_turn"
    assert len(executor.calls) == 2


def test_more_than_five_tool_calls_stops():
    responses = [_tool_use("get_leave_balance", f"toolu_{i}",
                           {"company": "آ", "date": f"2026-01-{i + 1:02d}"}) for i in range(7)]
    client = ScriptedClient(responses)
    executor = _executor({"ok": True})
    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    assert result["stop_reason"] == "tool_call_cap"
    assert result["answer"] == orchestrator.TOOL_CALL_CAP_MESSAGE
    assert len(executor.calls) == 5


def test_wall_clock_budget_stops_the_loop():
    client = ScriptedClient([_tool_use("get_my_leave_summary", "toolu_1")])
    executor = _executor({"ok": True})
    clock = [0.0]

    def now():
        clock[0] += 100.0
        return clock[0]

    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(),
                                        executor=executor, now=now)
    assert result["stop_reason"] == "time_budget"
    assert result["answer"] == orchestrator.TIME_BUDGET_MESSAGE
    assert executor.calls == []
    assert client.calls == []


def test_tool_result_is_truncated_before_it_goes_to_the_model():
    big = {"rows": [{"n": i, "text": "داده" * 50} for i in range(200)]}
    client = ScriptedClient([
        _tool_use("list_my_issues", "toolu_1"),
        _text("routing done"),
        _text("پاسخ"),
    ])
    executor = _executor(big)
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert len(tool_result["content"]) <= orchestrator.MAX_TOOL_RESULT_CHARS + 20
    assert tool_result["content"].endswith("…(ادامه بریده شد)")


def test_sensitive_fields_are_masked_before_the_model_sees_them():
    payload = {"national_id": "0012345678", "iban": "IR1234", "salary": 5000000,
               "nested": {"bank_name": "بانک ملی", "name": "علی"},
               "list": [{"net_salary": 1}]}
    masked = orchestrator.mask_sensitive(payload)
    assert masked["national_id"] == "مخفی"
    assert masked["iban"] == "مخفی"
    assert masked["salary"] == "مخفی"
    assert masked["nested"]["bank_name"] == "مخفی"
    assert masked["nested"]["name"] == "علی"
    assert masked["list"][0]["net_salary"] == "مخفی"


def test_every_sensitive_stem_masks_a_value_under_it():
    # A key is masked when it CONTAINS any sensitive stem (case-insensitive).
    sensitive = {
        "national_id": "001", "national_code": "002",
        "iban": "IR1", "bank_account": "acc", "bank_name": "بانک",
        "salary": 1, "gross_salary": 2, "wage": 3,
        "mobile": "0912", "phone": "021", "cell_number": "0935",
        "address": "تهران", "postal_code": "12345",
        "birth_date": "1990-01-01", "passport_number": "P1",
        "email": "a@b.c", "company_email": "c@d.e", "father_name": "علی",
        "emergency_phone": "0912", "emergency_contact_name": "فانی",
        "tax_id": "T1", "insurance_number": "I1",
    }
    masked = orchestrator.mask_sensitive(sensitive)
    for key, value in sensitive.items():
        assert masked[key] == "مخفی", f"{key} was not masked"


def test_harmless_keys_are_not_masked():
    # Business/structural keys that do not contain a sensitive stem stay intact.
    payload = {
        "status": "Open", "title": "درخواست مرخصی", "leave_type": "سالانه",
        "name": "REQ-0001", "request_name": "درخواست", "subject": "تیکت",
        "opening_date": "2026-11-28", "due_on": "2026-12-01", "as_of": "2026-11-28",
        "company": "شرکت آسود", "employee": "HR-EMP-0001", "total": 3,
        "remaining": 5.5, "available": 4.0, "category": "annual",
        "workflow_stage": "تأیید", "assigned_to": "user@example.com",
    }
    masked = orchestrator.mask_sensitive(payload)
    assert masked == payload


def test_masking_applies_to_the_tool_result_in_the_round_trip():
    client = ScriptedClient([
        _tool_use("get_my_personnel_file", "toolu_1"),
        _text("routing done"),
        _text("پاسخ"),
    ])
    executor = _executor({"national_id": "0012345678", "name": "علی"})
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert "0012345678" not in tool_result["content"]
    assert "مخفی" in tool_result["content"]
    assert "علی" in tool_result["content"]


def test_unknown_tool_name_is_reported_as_an_error_to_the_model():
    client = ScriptedClient([
        _tool_use("delete_everything", "toolu_1"),
        _text("routing done"),
        _text("پاسخ"),
    ])
    executor = _executor({"ok": True})
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == orchestrator.UNKNOWN_TOOL_MESSAGE
    assert executor.calls == []


def test_tool_exception_becomes_a_persian_tool_result():
    class PermissionError_(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.message = message

    def executor(method, args):
        raise PermissionError_("دسترسی شما کافی نیست.")

    client = ScriptedClient([
        _tool_use("get_request", "toolu_1", {"name": "REQ-1"}),
        _text("routing done"),
        _text("پاسخ"),
    ])
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == "دسترسی شما کافی نیست."


def test_exception_without_a_message_uses_the_generic_persian_fallback():
    def executor(method, args):
        raise RuntimeError("boom")

    client = ScriptedClient([
        _tool_use("get_request", "toolu_1", {"name": "REQ-1"}),
        _text("routing done"),
        _text("پاسخ"),
    ])
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=executor)
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert tool_result["content"] == orchestrator.TOOL_ERROR_MESSAGE


def test_thinking_disabled_for_routing_and_low_for_the_answer():
    client = ScriptedClient([_text("routing done"), _text("پاسخ نهایی")])
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=_executor({}))
    assert client.calls[0]["thinking"] == {"type": "disabled"}
    assert client.calls[0]["tool_choice"] == {"type": "auto"}
    assert client.calls[0]["temperature"] == 0.2
    assert client.calls[0]["max_tokens"] == orchestrator.MAX_TOKENS
    # The answer turn runs with thinking (budget 1024) and a larger max_tokens,
    # because reasoning tokens count inside max_tokens.
    assert client.calls[1]["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert client.calls[1]["max_tokens"] == orchestrator.ANSWER_MAX_TOKENS
    assert client.calls[1]["max_tokens"] > orchestrator.MAX_TOKENS
    assert not client.calls[1].get("tools")


def test_answer_turn_uses_a_larger_max_tokens_than_routing():
    client = ScriptedClient([_text("routing done"), _text("پاسخ")])
    orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=_executor({}))
    assert client.calls[0]["max_tokens"] == orchestrator.MAX_TOKENS
    assert client.calls[1]["max_tokens"] == orchestrator.ANSWER_MAX_TOKENS
    assert orchestrator.ANSWER_MAX_TOKENS >= 2048


def test_max_tokens_stop_with_no_text_yields_the_persian_message():
    # The answer budget was spent on reasoning: stop_reason max_tokens and no
    # text block. The user must get a Persian message, not an empty string.
    client = ScriptedClient([
        _text("routing done"),
        {"content": [{"type": "thinking", "thinking": "...", "signature": ""}],
         "stop_reason": "max_tokens"},
    ])
    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=_executor({}))
    assert result["stop_reason"] == "end_turn"
    assert result["answer"] == orchestrator.ANSWER_TRUNCATED_MESSAGE
    assert result["answer"] != ""


def test_max_tokens_stop_with_some_text_keeps_the_text():
    # A partial answer is still better than nothing: keep the text that came out.
    client = ScriptedClient([
        _text("routing done"),
        {"content": [{"type": "text", "text": "پاسخ ناقص"}], "stop_reason": "max_tokens"},
    ])
    result = orchestrator.run_assistant("x", "u", client, tool_catalog.catalog(), executor=_executor({}))
    assert result["answer"] == "پاسخ ناقص"


def test_default_executor_calls_the_whitelisted_method_in_the_session(monkeypatch):
    calls = []
    stub = types.ModuleType("frappe")
    stub.session = types.SimpleNamespace(user="user@example.com")
    stub.call = lambda method, **kwargs: calls.append((method, kwargs)) or {"ok": True, "data": 1}
    monkeypatch.setitem(sys.modules, "frappe", stub)
    executor = orchestrator._default_executor("user@example.com")
    assert executor("asoud_erp.api.v1.support.list_my_issues", {"status": "Open"}) == {"ok": True, "data": 1}
    assert calls == [("asoud_erp.api.v1.support.list_my_issues", {"status": "Open"})]


def test_default_executor_refuses_to_run_as_another_user(monkeypatch):
    calls = []
    stub = types.ModuleType("frappe")
    stub.session = types.SimpleNamespace(user="other@example.com")
    stub.call = lambda method, **kwargs: calls.append(method) or {"ok": True}
    monkeypatch.setitem(sys.modules, "frappe", stub)
    executor = orchestrator._default_executor("user@example.com")
    with pytest.raises(PermissionError):
        executor("asoud_erp.api.v1.support.list_my_issues", {})
    assert calls == []
