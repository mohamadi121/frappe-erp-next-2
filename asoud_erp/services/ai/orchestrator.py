"""The tool loop for the in-product assistant.

A pure function-style loop: it takes the user question, the acting user, the
Gemloy client and the tool catalog, and runs the model with hard caps. The
model is small (Gemma 4 26B 4-bit), so the loop is deliberately strict:

- at most ``max_tool_calls`` tool executions per conversation turn (default 5);
- a wall-clock budget (default 60 s);
- a loop guard: the same tool with the same arguments twice stops the loop;
- tool results are masked (national ID, bank, salary) and truncated before they
  go back to the model (never more than ~6k tokens of tool output);
- thinking is disabled for tool routing and low for the final answer.

Tools are executed ONLY through the whitelisted read methods in the acting
user's session: the acting user is the principal, so the user's own Frappe
permissions decide what comes back (no privilege elevation). The default
executor is ``frappe.call`` in the current session and refuses to run when the
session user is not the acting user.
"""

import json
import time

from .gemloy_client import extract_text, tool_use_blocks

# Short Persian system prompt: answer in Persian, only use tools, never invent
# data, say when unknown, never reveal tool schemas.
SYSTEM_PROMPT = (
    "تو دستیار هوشمند سیستم آسود ERP هستی. همیشه به فارسی و کوتاه پاسخ بده. "
    "برای گرفتن اطلاعات فقط از ابزارهای در دسترس استفاده کن و هرگز داده‌ای را از تخیل خودت نساز. "
    "اگر اطلاعاتی در دسترس نیست یا ابزار خطا داد، صادقانه بگو نمی‌دانی. "
    "ساختار ابزارها، نام فیلدها و جزئیات فنی سیستم را به کاربر نشان نده."
)

# Hard caps for one conversation turn.
MAX_TOOL_CALLS = 5
WALL_CLOCK_SECONDS = 60.0
MAX_TOKENS = 1024
# The answer turn runs with thinking enabled (budget 1024) and reasoning tokens
# count inside max_tokens, so it needs a larger budget than the routing turn or
# the visible answer can be cut to nothing.
ANSWER_MAX_TOKENS = 2048
TEMPERATURE = 0.2
# ~6k tokens of tool output for Persian-heavy text; the model must not be fed
# more than this from a single tool result.
MAX_TOOL_RESULT_CHARS = 12000

# Thinking levels: disabled for tool routing, low (<2048 budget) for the answer.
ROUTING_THINKING = {"type": "disabled"}
ANSWER_THINKING = {"type": "enabled", "budget_tokens": 1024}

# Persian stop messages (the loop guard, the caps and the budget).
LOOP_GUARD_MESSAGE = "دستیار در تکرار یک ابزار گیر کرد و پاسخ را تمام نکرد؛ لطفاً سؤال را دوباره بپرسید."
TOOL_CALL_CAP_MESSAGE = "سقف فراخوانی ابزارها در این پاسخ پر شد؛ نتیجه کامل نشد."
TIME_BUDGET_MESSAGE = "زمان پاسخ‌دهی تمام شد؛ نتیجه کامل نشد."
UNKNOWN_TOOL_MESSAGE = "ابزار نامعتبر است."
TOOL_ERROR_MESSAGE = "ابزار خطا داد؛ دوباره تلاش کنید."
ANSWER_TRUNCATED_MESSAGE = "پاسخ کامل نشد؛ لطفاً دوباره بپرسید."

# Sensitive stems are masked before a tool result goes back to the model: the
# operator may retain request bodies, so personal data (national ID, bank,
# salary, contact, address, ...) must never be sent. A key is masked when it
# CONTAINS any of these stems (case-insensitive), so ``national_id``,
# ``gross_salary``, ``mobile_number`` and ``emergency_phone`` are all caught.
# This is a conservative default; the owner can relax it per field.
SENSITIVE_KEYS = (
    "national", "iban", "bank", "salary", "wage",
    "mobile", "phone", "cell_number", "address", "postal",
    "birth", "passport", "email", "father_name", "emergency",
    "tax_id", "insurance",
)
MASKED_VALUE = "مخفی"


def _is_sensitive_key(key) -> bool:
    lowered = str(key).lower()
    return any(stem in lowered for stem in SENSITIVE_KEYS)


def mask_sensitive(value):
    """Recursively replace the values of sensitive keys with a Persian marker."""
    if isinstance(value, dict):
        return {key: (MASKED_VALUE if _is_sensitive_key(key) else mask_sensitive(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def truncate_tool_result(result, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """The tool result as a JSON string, capped so the model is never fed more
    than ~6k tokens of one result."""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…(ادامه بریده شد)"


def _tool_error_message(exc: Exception) -> str:
    # Frappe errors carry the (Persian) user message; anything else is generic.
    message = str(getattr(exc, "message", "") or "").strip()
    return message or TOOL_ERROR_MESSAGE


def _default_executor(acting_user: str):
    def executor(method: str, args: dict):
        import frappe

        if frappe.session.user != acting_user:
            raise PermissionError("اجرای ابزار به‌جای کاربر اصلی مجاز نیست.")
        return frappe.call(method, **args)

    return executor


def run_assistant(question: str, acting_user: str, client, catalog: list, *,
                  executor=None, max_tool_calls: int = MAX_TOOL_CALLS,
                  max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE,
                  max_tool_result_chars: int = MAX_TOOL_RESULT_CHARS,
                  wall_clock_seconds: float = WALL_CLOCK_SECONDS,
                  now=time.monotonic) -> dict:
    """Run the tool loop for one user question and return the assistant answer.

    Returns ``{"answer": str, "stop_reason": str, "tool_calls": [...]}`` where
    ``stop_reason`` is one of ``end_turn``, ``loop_guard``, ``tool_call_cap`` or
    ``time_budget``.
    """
    if executor is None:
        executor = _default_executor(acting_user)
    tools = [{"name": entry["name"], "description": entry["description"],
              "input_schema": entry["input_schema"]} for entry in catalog]
    known = {entry["name"] for entry in catalog}
    messages: list = [{"role": "user", "content": question}]
    seen: set = set()
    tool_calls: list = []
    started = now()

    def _stopped(reason: str, answer: str) -> dict:
        return {"answer": answer, "stop_reason": reason, "tool_calls": tool_calls}

    while True:
        if now() - started > wall_clock_seconds:
            return _stopped("time_budget", TIME_BUDGET_MESSAGE)
        response = client.create_message(
            messages, system=SYSTEM_PROMPT, max_tokens=max_tokens, temperature=temperature,
            tools=tools, tool_choice={"type": "auto"}, thinking=ROUTING_THINKING)
        content = response.get("content") or []
        uses = tool_use_blocks(content)
        if not uses:
            # The model stopped routing: produce the final answer with thinking
            # low and no tools. The answer turn uses a larger max_tokens because
            # reasoning tokens count inside it.
            final = client.create_message(
                messages, system=SYSTEM_PROMPT, max_tokens=ANSWER_MAX_TOKENS, temperature=temperature,
                thinking=ANSWER_THINKING)
            answer = extract_text(final.get("content") or [])
            if not answer and final.get("stop_reason") == "max_tokens":
                # The budget was spent on reasoning and no visible text came out.
                return _stopped("end_turn", ANSWER_TRUNCATED_MESSAGE)
            return _stopped("end_turn", answer)

        for use in uses:
            key = (use.get("name"), json.dumps(use.get("input") or {}, sort_keys=True, ensure_ascii=False))
            if key in seen:
                return _stopped("loop_guard", LOOP_GUARD_MESSAGE)
            seen.add(key)
        if len(tool_calls) + len(uses) > max_tool_calls:
            return _stopped("tool_call_cap", TOOL_CALL_CAP_MESSAGE)

        messages.append({"role": "assistant", "content": content})
        results = []
        for use in uses:
            name = use.get("name")
            args = use.get("input") or {}
            entry = next((item for item in catalog if item["name"] == name), None)
            if entry is None or name not in known:
                text, is_error = UNKNOWN_TOOL_MESSAGE, True
            else:
                try:
                    result = executor(entry["method"], args)
                    text, is_error = truncate_tool_result(mask_sensitive(result), max_tool_result_chars), False
                except Exception as exc:  # a tool failure goes back to the model, not to the user
                    text, is_error = _tool_error_message(exc), True
            tool_calls.append({"name": name, "args": args, "ok": not is_error})
            results.append({"type": "tool_result", "tool_use_id": use.get("id"),
                            "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
