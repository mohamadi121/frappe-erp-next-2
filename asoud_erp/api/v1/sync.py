import json
from typing import Any

import frappe

from .responses import failure

_ALLOWED_PREFIX = "asoud_erp.api.v1."
_MUTATION_PREFIXES = (
    "add_",
    "apply_",
    "approve_",
    "archive_",
    "complete_",
    "connect_",
    "create_",
    "delete_",
    "disable_",
    "import_",
    "insert_",
    "link_",
    "mark_",
    "publish_",
    "reject_",
    "return_",
    "save_",
    "seed_",
    "start_",
    "submit_",
    "update_",
    "upload_",
)


@frappe.whitelist(methods=["POST"])
def execute_mutation(
    request_key: str,
    target_method: str,
    payload: str | dict[str, Any] | None = None,
) -> dict:
    """Execute a v1 mutation once and return the original API envelope."""
    key = (request_key or "").strip()
    method = (target_method or "").strip()
    if not key or len(key) > 140:
        return failure("INVALID_REQUEST_KEY", "شناسه یکتای درخواست معتبر نیست.")
    action = method.rsplit(".", 1)[-1]
    if not method.startswith(_ALLOWED_PREFIX) or not action.startswith(_MUTATION_PREFIXES):
        return failure("METHOD_NOT_ALLOWED", "این متد برای همگام‌سازی مجاز نیست.")
    if method == "asoud_erp.api.v1.sync.execute_mutation":
        return failure("METHOD_NOT_ALLOWED", "فراخوانی بازگشتی مجاز نیست.")

    existing = frappe.db.get_value(
        "ASOUD API Request",
        key,
        ["status", "response_json"],
        as_dict=True,
    )
    if existing and existing.status == "Completed":
        return json.loads(existing.response_json)
    if existing:
        return failure("REQUEST_IN_PROGRESS", "این درخواست در حال پردازش است.")

    values = _payload(payload)
    request_doc = frappe.get_doc(
        {
            "doctype": "ASOUD API Request",
            "request_key": key,
            "method": method,
            "status": "Processing",
        }
    )
    request_doc.insert(ignore_permissions=True)

    result = frappe.get_attr(method)(**values)
    if not isinstance(result, dict) or "ok" not in result:
        result = failure("INVALID_RESPONSE", "پاسخ عملیات قابل پردازش نیست.")
    request_doc.status = "Completed"
    request_doc.response_json = json.dumps(result, ensure_ascii=False, default=str)
    request_doc.save(ignore_permissions=True)
    return result


def _payload(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        frappe.throw("Mutation payload must be an object")
    return parsed
