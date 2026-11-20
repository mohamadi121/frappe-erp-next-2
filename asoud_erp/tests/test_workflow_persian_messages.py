"""PA-047 regression: every hardcoded user-facing error message in the workflow
controllers must be a Persian sentence, never a raw English string.

The old code shipped dozens of ``frappe.throw(_("..."))`` calls with English text
(e.g. ``"A decision comment is required"``) that reached the Iranian client
untranslated. This test parses the three workflow API modules and fails if any
hardcoded ``frappe.throw`` message still contains English letters.

Dynamic messages (``frappe.throw(str(error))`` / ``frappe.throw(_(message))``)
are not hardcoded strings and are intentionally skipped.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "asoud_erp/api/v1/workflow.py",
    "asoud_erp/api/v1/workflow_request.py",
    "asoud_erp/api/v1/workflow_runtime.py",
)


def _hardcoded_throw_message(node: ast.AST):
    """Return the hardcoded string literal passed to ``frappe.throw``, or None.

    Covers ``frappe.throw("...")`` and ``frappe.throw(_("..."))``. Anything else
    (a variable, ``str(error)``, a conditional) is not a hardcoded literal and
    returns None.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "throw" and node.args):
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
            and arg.func.id == "_" and arg.args
            and isinstance(arg.args[0], ast.Constant)
            and isinstance(arg.args[0].value, str)):
        return arg.args[0].value
    return None


def _has_english(text: str) -> bool:
    return any(ch.isascii() and ch.isalpha() for ch in text)


def test_workflow_error_messages_are_persian():
    offenders = []
    for rel in FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            message = _hardcoded_throw_message(node)
            if message is not None and _has_english(message):
                offenders.append(f"{rel}:{node.lineno}: {message!r}")
    assert not offenders, "English error messages found:\n" + "\n".join(offenders)


def test_known_messages_are_now_persian_sentences():
    """Spot-check the messages the audit named, so a regression back to English
    (or to a bare word) is caught even if the scanner is ever narrowed."""
    workflow = (ROOT / "asoud_erp/api/v1/workflow.py").read_text(encoding="utf-8")
    runtime = (ROOT / "asoud_erp/api/v1/workflow_runtime.py").read_text(encoding="utf-8")
    request = (ROOT / "asoud_erp/api/v1/workflow_request.py").read_text(encoding="utf-8")

    # The exact English strings from the audit must be gone.
    for gone in (
        "Workflow title must contain at least 3 characters",
        "Invalid workflow stage type",
        "A decision comment is required",
        "Only an active workflow can be started",
        "Only the requester can change this request",
    ):
        assert gone not in workflow + runtime + request, f"English message still present: {gone}"

    # And the replacement Persian sentences are present.
    assert "عنوان گردش‌کار باید دست‌کم ۳ نویسه باشد" in workflow
    assert "نوع مرحلهٔ گردش‌کار نامعتبر است" in workflow
    assert "ثبت نظر برای تصمیم‌گیری الزامی است" in runtime
    assert "فقط گردش‌کار فعال قابل شروع است" in runtime
    assert "فقط درخواست‌کننده می‌تواند این درخواست را تغییر دهد" in request
