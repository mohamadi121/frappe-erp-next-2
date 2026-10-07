"""Template registry: the interface between the request engine and the template specs.

The engine (`workflow_request`, `seed`, `lifecycle`) only talks to `TemplateSpec`.
Each spec module (`purchase.py`, `supply.py`, `leave.py`) builds one `TemplateSpec`
and either calls `register(SPEC)` on import or exposes it as a module-level `SPEC`.
This module imports `frappe` lazily so the pure parts stay unit-testable.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from asoud_erp.services.jalali import current_jalali_year
from asoud_erp.services.leave_hours import MESSAGES as LEAVE_MESSAGES

if TYPE_CHECKING:
    from frappe.model.document import Document

SPEC_MODULES = ("purchase", "supply", "leave")
# Fallback when a spec module is not importable; a spec's own `number_prefix` wins.
NUMBER_PREFIXES = {"purchase": "PR", "supply": "SP", "leave": "LV"}
LEGACY_NUMBER_SERIES = "REQ-"

ERROR_MESSAGES = {
    "TEMPLATE_NOT_AVAILABLE": "این نوع درخواست برای شرکت شما فعال نیست.",
    "REQUEST_ID_CONFLICT": "این شناسه درخواست قبلاً برای درخواست دیگری استفاده شده است.",
    "REQUEST_NOT_EDITABLE": "این درخواست دیگر قابل ویرایش نیست.",
    "REQUESTER_MISMATCH": "درخواست‌کننده باید همان کاربر واردشده باشد.",
    "EMPLOYEE_NOT_FOUND": "برای شما در این شرکت پرسنل فعالی ثبت نشده است.",
    "COST_CENTER_REQUIRED": "انتخاب مرکز هزینه الزامی است.",
    "DATE_IN_PAST": "تاریخ نمی‌تواند در گذشته باشد.",
    "DELIVERY_NOT_WAREHOUSE": "برای انتقال، محل تحویل باید یک انبار باشد.",
    "ITEM_NOT_STOCKABLE": "اقلام خدماتی را نمی‌توان از انبار تأمین یا منتقل کرد.",
    "ATTACHMENT_INVALID": "پیوست نامعتبر است.",
    "EMPTY_COMMENT": "متن نظر نمی‌تواند خالی باشد.",
    "NATIVE_NOT_RETRYABLE": "ایجاد سند برای این درخواست قابل تکرار نیست.",
}
# The leave rule codes have one text, the one `preview_leave_request` and `create_request` show
# (`leave_hours.MESSAGES`); `DATE_IN_PAST` stays generic here (purchase/supply `needed_date`).
ERROR_MESSAGES.update({code: text for code, text in LEAVE_MESSAGES.items() if code != "DATE_IN_PAST"
                       and code not in ("MIN_DURATION", "INVALID_TIME")})


def _no_defaults(company: str, user: str) -> dict:
    return {}


def _always_available(company: str, user: str) -> bool:
    return True


def _passthrough(ctx: ValidationContext) -> dict:
    return ctx.values


def _no_denormalize(values: dict) -> dict:
    return {"priority": "Normal", "required_by": None, "project": "", "department": ""}


def _no_summary(values: dict, request_row: dict) -> dict:
    return {}


def _skip_native(request: Document) -> NativeResult:
    return NativeResult(status="Skipped", reason="NO_NATIVE_DOCUMENT")


@dataclass(frozen=True)
class NativeResult:
    """Outcome of `TemplateSpec.on_approved`: a native document, or nothing to create."""

    status: str  # "Created" | "Skipped"
    doctype: str | None = None
    name: str | None = None
    reason: str = ""


@dataclass
class ValidationContext:
    """What `TemplateSpec.validate` sees. `values` are already normalized.

    `request_name` is set when a request already exists (an update, or a form task
    completed after a Return) so rules such as overlap checks can exclude it.
    """

    company: str
    user: str
    employee: str | None
    values: dict
    fields: list
    is_update: bool = False
    previous: dict | None = None
    request_name: str | None = None
    definition: str | None = None
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    title: str
    short_title: str
    description: str
    number_prefix: str
    category: str
    module_key: str
    icon_key: str
    color_hex: str
    version: int
    subject_mode: str  # "input" | "generated"
    form_fields: list[dict]
    attachments: dict
    approval: dict
    available_for: Callable[[str, str], bool] = _always_available
    resolve_defaults: Callable[[str, str], dict] = _no_defaults
    validate: Callable[[ValidationContext], dict] = _passthrough
    build_subject: Callable[[dict], str] | None = None
    denormalize: Callable[[dict], dict] = _no_denormalize
    summarize: Callable[[dict, dict], dict] = _no_summary
    on_approved: Callable[[Document], NativeResult] = _skip_native


_REGISTRY: dict[str, TemplateSpec] = {}


def register(spec: TemplateSpec) -> TemplateSpec:
    """Adds (or replaces) a spec; returns it so a module can `SPEC = register(...)`."""
    if not isinstance(spec, TemplateSpec) or not spec.key:
        raise ValueError("A TemplateSpec with a key is required")
    _REGISTRY[spec.key] = spec
    return spec


def _load_spec_modules() -> None:
    for name in SPEC_MODULES:
        module_name = f"{__package__}.{name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name != module_name:
                raise
            continue
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, TemplateSpec) and spec.key not in _REGISTRY:
            register(spec)


def all_specs() -> list[TemplateSpec]:
    """Every registered spec, importing the spec modules that exist (a missing one is skipped)."""
    _load_spec_modules()
    return [_REGISTRY[key] for key in SPEC_MODULES if key in _REGISTRY] + [
        spec for key, spec in _REGISTRY.items() if key not in SPEC_MODULES
    ]


def get(key: str | None) -> TemplateSpec | None:
    """The spec for a template key, or None for custom request types."""
    if not key:
        return None
    if key not in _REGISTRY:
        _load_spec_modules()
    return _REGISTRY.get(key)


def number_prefix(key: str | None) -> str | None:
    """The request number prefix of a template, or None for custom types."""
    if not key:
        return None
    spec = get(key)
    return spec.number_prefix if spec else NUMBER_PREFIXES.get(key)


def series_key(prefix: str | None, on: date | None = None) -> str:
    """The `tabSeries` key for a prefix on a day, e.g. `PR-1405-`; `REQ-` without a prefix."""
    if not prefix:
        return LEGACY_NUMBER_SERIES
    return f"{prefix}-{current_jalali_year(on)}-"


def number_pattern(prefix: str | None, on: date | None = None) -> str:
    """The `make_autoname` pattern: `PR-1405-.####` (four digits) or `REQ-.#####`."""
    return f"{series_key(prefix, on)}.{'####' if prefix else '#####'}"


def throw_error(code: str, message: str | None = None) -> None:
    """Raises a ValidationError whose `title` is the machine-readable error code."""
    import frappe

    frappe.throw(message or ERROR_MESSAGES.get(code, code), exc=frappe.ValidationError, title=code)


def validate_form_stage_response(instance: Any, stage: Any, normalized_response: dict) -> dict:
    """Template validation for a form task completed from the cartable (e.g. after a Return).

    Returns the final values (spec.validate may add computed Auto values). Anything that
    is not the form stage of a template request is returned unchanged.
    """
    import frappe

    if getattr(instance, "reference_doctype", None) != "ASOUD Workflow Request":
        return normalized_response
    if not instance.reference_name or frappe.flags.get("asoud_request_form_validated") == instance.reference_name:
        return normalized_response
    request = frappe.db.get_value(
        "ASOUD Workflow Request", instance.reference_name,
        ["name", "company", "template_key", "workflow_definition"], as_dict=True)
    spec = get(request.template_key) if request else None
    if not spec:
        return normalized_response
    from asoud_erp.api.v1.workflow_request import _form_stage, effective_values

    definition = frappe.get_doc("ASOUD Workflow Definition", request.workflow_definition)
    form_stage = _form_stage(definition)
    if stage.name != form_stage.name:
        return normalized_response
    fields = frappe.parse_json(form_stage.config_json or "{}").get("form_fields", [])
    user = instance.started_by
    employee = frappe.db.get_value(
        "Employee", {"user_id": user, "company": request.company, "status": "Active"}, "name")
    context = ValidationContext(
        company=request.company, user=user, employee=employee, values=dict(normalized_response),
        fields=fields, is_update=True, previous=effective_values(request.name),
        request_name=request.name, definition=definition.name)
    return spec.validate(context)
