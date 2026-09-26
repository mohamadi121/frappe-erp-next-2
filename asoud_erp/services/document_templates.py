"""Document templates: how a workflow's automatic "Create Document" step fills an
ERPNext document from a request.

A template names a target DocType and maps each of its supported fields to one
value source. This module is pure: it validates templates, resolves values from
a prepared context and builds the ERPNext document dict. Inserting, permission
checks and ERPNext validation happen in `api/v1/document_templates.py`.
"""

import re
from typing import Any

SOURCES = ("fixed", "request", "user", "organization", "system")

# Module -> supported target document types. Types listed with `enabled: False`
# are shown in the app as "coming soon" and rejected on save.
MODULES: dict[str, dict[str, Any]] = {
    "Finance": {
        "label": "مالی",
        "description": "حسابداری و خزانه‌داری",
        "types": [
            {"key": "Journal Entry", "label": "سند حسابداری", "enabled": True},
            {"key": "Receipt", "label": "دریافت", "enabled": False},
            {"key": "Payment", "label": "پرداخت", "enabled": False},
        ],
    },
    "Purchase": {
        "label": "خرید",
        "description": "تأمین کالا و خدمات",
        "types": [
            {"key": "Material Request", "label": "درخواست خرید کالا", "enabled": True},
            {"key": "Purchase Order", "label": "سفارش خرید", "enabled": False},
        ],
    },
    "Selling": {"label": "فروش", "description": "مدیریت فروش و مشتریان", "types": []},
    "Stock": {"label": "انبار", "description": "مدیریت موجودی کالا", "types": []},
    "HR": {"label": "منابع انسانی", "description": "کارکنان و حقوق", "types": []},
    "Admin": {"label": "خدمات اداری", "description": "خدمات رفاهی و اداری", "types": []},
    "IT": {"label": "IT و تجهیزات", "description": "تجهیزات و زیرساخت", "types": []},
}

# Target fields per document type. `type` is also the value type the source must
# produce: Account/Cost Center/Project/Warehouse are ERPNext record names.
TARGET_FIELDS: dict[str, list[dict[str, Any]]] = {
    "Journal Entry": [
        {"key": "posting_date", "label": "تاریخ سند", "type": "Date", "required": True},
        {"key": "title", "label": "شرح سند", "type": "Text", "required": True},
        {"key": "amount", "label": "مبلغ", "type": "Currency", "required": True},
        {"key": "debit_account", "label": "حساب بدهکار", "type": "Account", "required": True},
        {"key": "credit_account", "label": "حساب بستانکار", "type": "Account", "required": True},
        {"key": "cost_center", "label": "مرکز هزینه", "type": "Cost Center", "required": False},
        {"key": "project", "label": "پروژه", "type": "Project", "required": False},
        {"key": "user_remark", "label": "توضیحات", "type": "Text", "required": False},
    ],
    "Material Request": [
        {"key": "transaction_date", "label": "تاریخ درخواست", "type": "Date", "required": True},
        {"key": "schedule_date", "label": "تاریخ نیاز", "type": "Date", "required": True},
        {"key": "items", "label": "اقلام", "type": "Item Table", "required": True},
        {"key": "set_warehouse", "label": "انبار مقصد", "type": "Warehouse", "required": False},
    ],
}

LINK_TARGETS = {"Account", "Cost Center", "Project", "Warehouse"}

# Request values every workflow request has, besides its custom form fields.
REQUEST_BASE_FIELDS = {
    "request_number": ("شماره درخواست", "Text"),
    "subject": ("عنوان درخواست", "Text"),
    "requested_on": ("تاریخ درخواست", "Date"),
    "requester": ("درخواست‌کننده", "Text"),
    "requester_department": ("واحد درخواست‌دهنده", "Text"),
    "description": ("شرح درخواست", "Text"),
}
USER_VALUES = {
    "initiator": "کاربر درخواست‌کننده",
    "initiator_name": "نام درخواست‌کننده",
    "initiator_department": "واحد درخواست‌کننده",
    "actor": "آخرین اقدام‌کننده",
}
ORGANIZATION_VALUES = {
    "company": "نام شرکت",
    "default_currency": "ارز پیش‌فرض",
    "cost_center": "مرکز هزینه پیش‌فرض",
}
SYSTEM_VALUES = {
    "today": "تاریخ روز",
    "now": "زمان جاری",
    "request_number": "شماره درخواست",
    "instance": "شماره فرایند",
}
PLACEHOLDERS = {
    "RequestNo": ("system", "request_number"),
    "Subject": ("request", "subject"),
    "Requester": ("user", "initiator_name"),
    "Today": ("system", "today"),
    "Company": ("organization", "company"),
}
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_KEY = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

# Request field types that can feed each target type.
_COMPATIBLE = {
    "Date": {"Date"},
    "Currency": {"Number", "Currency"},
    "Item Table": {"Item Table"},
}


def document_type(key: str) -> dict[str, Any] | None:
    for module_key, module in MODULES.items():
        for row in module["types"]:
            if row["key"] == key:
                return {**row, "module": module_key}
    return None


def _bool(value: Any, default: bool) -> bool:
    return default if value is None else value in (True, 1, "1", "true", "True")


def normalize_template(raw: dict[str, Any], request_fields: dict[str, str] | None = None) -> dict[str, Any]:
    """Validates a template; `request_fields` maps custom request keys to field types.

    When `request_fields` is None (no source request type) any valid key is
    accepted for the request source and checked at run time instead.
    """
    if not isinstance(raw, dict):
        raise ValueError("Template must be an object")
    title = str(raw.get("title") or "").strip()
    if not 2 <= len(title) <= 140:
        raise ValueError("Template title is required")
    module = str(raw.get("module") or "")
    target = document_type(str(raw.get("document_type") or ""))
    if module not in MODULES or not target or target["module"] != module:
        raise ValueError("Unsupported module or document type")
    if not target["enabled"]:
        raise ValueError("This document type is not available yet")
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("Field mapping must be an object")
    fields = {field["key"]: field for field in TARGET_FIELDS[target["key"]]}
    unknown = set(mapping) - set(fields)
    if unknown:
        raise ValueError(f"Unknown document field: {sorted(unknown)[0]}")
    normalized = {}
    for key, field in fields.items():
        entry = mapping.get(key)
        if entry in (None, {}):
            if field["required"]:
                raise ValueError(f"Required document field is not mapped: {key}")
            continue
        normalized[key] = _normalize_source(field, entry, request_fields)
    auto_submit = _bool(raw.get("auto_submit"), False)
    return {
        "title": title,
        "module": module,
        "document_type": target["key"],
        "description": str(raw.get("description") or "").strip()[:500],
        "mapping": normalized,
        "create_as_draft": False if auto_submit else _bool(raw.get("create_as_draft"), True),
        "auto_submit": auto_submit,
        "reusable": _bool(raw.get("reusable"), True),
        "manager_note": str(raw.get("manager_note") or "").strip()[:500],
    }


def _normalize_source(field: dict, entry: Any, request_fields: dict[str, str] | None) -> dict[str, str]:
    key = field["key"]
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid value source: {key}")
    source = entry.get("source")
    value = str(entry.get("value") or "").strip()
    if source not in SOURCES or not value or len(value) > 500:
        raise ValueError(f"Invalid value source: {key}")
    target_type = field["type"]
    if target_type == "Item Table" and source != "request":
        raise ValueError(f"Items must come from a request item table: {key}")
    if source == "request":
        if not _KEY.fullmatch(value):
            raise ValueError(f"Invalid request field: {key}")
        if value in REQUEST_BASE_FIELDS:
            value_type = REQUEST_BASE_FIELDS[value][1]
        elif request_fields is None:
            value_type = None
        elif value in request_fields:
            value_type = request_fields[value]
        else:
            raise ValueError(f"Request field does not exist: {value}")
        allowed = _COMPATIBLE.get(target_type)
        if allowed and value_type is not None and value_type not in allowed:
            raise ValueError(f"Request field type does not match: {key}")
    else:
        choices = {"user": USER_VALUES, "organization": ORGANIZATION_VALUES, "system": SYSTEM_VALUES}
        if source in choices and value not in choices[source]:
            raise ValueError(f"Invalid {source} value: {key}")
        if source == "fixed" and target_type == "Currency":
            _amount(value, key)
    return {"source": source, "value": value}


def _amount(value: Any, key: str) -> float:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid amount: {key}") from error
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        raise ValueError(f"Amount must be a positive number: {key}")
    return number


def render_placeholders(text: str, context: dict[str, dict[str, Any]]) -> str:
    """Replaces {{RequestNo}}-style placeholders and {{request_key}} values."""

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name in PLACEHOLDERS:
            section, key = PLACEHOLDERS[name]
            value = context.get(section, {}).get(key)
        else:
            value = context.get("request", {}).get(name)
        return "" if value is None or isinstance(value, (list, dict)) else str(value)

    return _PLACEHOLDER.sub(replace, text)


def resolve_values(mapping: dict[str, dict[str, str]], context: dict[str, dict[str, Any]],
                   *, transfer_values: bool = True) -> dict[str, Any]:
    """Target field -> value. Request values are skipped when `transfer_values` is off."""
    values: dict[str, Any] = {}
    for key, entry in mapping.items():
        source, name = entry["source"], entry["value"]
        if source == "fixed":
            values[key] = render_placeholders(name, context)
        elif source == "request" and not transfer_values:
            continue
        else:
            values[key] = context.get(source, {}).get(name)
    return values


def build_document(document_type_key: str, values: dict[str, Any], company: str) -> dict[str, Any]:
    """The ERPNext document dict; raises ValueError when a required value is missing."""
    fields = {field["key"]: field for field in TARGET_FIELDS[document_type_key]}
    for key, field in fields.items():
        if field["required"] and values.get(key) in (None, "", []):
            raise ValueError(f"Value for {field['label']} is missing")
    if document_type_key == "Journal Entry":
        amount = _amount(values["amount"], "amount")
        common = {
            key: values[key] for key in ("cost_center", "project") if values.get(key)
        }
        return {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": company,
            "posting_date": str(values["posting_date"]),
            "title": str(values["title"])[:140],
            "user_remark": str(values.get("user_remark") or values["title"]),
            "accounts": [
                {"account": values["debit_account"], "debit_in_account_currency": amount, **common},
                {"account": values["credit_account"], "credit_in_account_currency": amount, **common},
            ],
        }
    if document_type_key == "Material Request":
        rows = values["items"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("Value for اقلام is missing")
        schedule = str(values["schedule_date"])
        warehouse = values.get("set_warehouse") or None
        return {
            "doctype": "Material Request",
            "material_request_type": "Purchase",
            "company": company,
            "transaction_date": str(values["transaction_date"]),
            "schedule_date": schedule,
            "set_warehouse": warehouse,
            "items": [
                {
                    "item_code": row["item_code"],
                    "qty": row["qty"],
                    "uom": row.get("uom") or row.get("stock_uom"),
                    **{key: row[key] for key in ("stock_uom", "conversion_factor") if row.get(key)},
                    "schedule_date": schedule,
                    "warehouse": warehouse,
                    "description": row.get("description") or None,
                }
                for row in rows
            ],
        }
    raise ValueError("Unsupported document type")


# Ready-made starting points shown in the «الگوهای آماده» tab. Accounts are
# company-specific, so a preset is copied into a custom template before use.
PRESETS = [
    {
        "key": "purchase_expense",
        "title": "سند هزینه خرید",
        "description": "ثبت سند حسابداری بر اساس هزینه خرید",
        "icon": "cart",
        "module": "Finance",
        "document_type": "Journal Entry",
        "mapping": {
            "posting_date": {"source": "system", "value": "today"},
            "title": {"source": "fixed", "value": "هزینه خرید بر اساس درخواست {{RequestNo}}"},
        },
    },
    {
        "key": "supplier_payment",
        "title": "پرداخت به تأمین‌کننده",
        "description": "پرداخت وجه به تأمین‌کننده بر اساس سفارش خرید",
        "icon": "payment",
        "module": "Finance",
        "document_type": "Journal Entry",
        "mapping": {
            "posting_date": {"source": "system", "value": "today"},
            "title": {"source": "fixed", "value": "پرداخت بابت درخواست {{RequestNo}}"},
        },
    },
    {
        "key": "general_expense",
        "title": "سند هزینه عمومی",
        "description": "هزینه‌های اداری و عمومی",
        "icon": "chart",
        "module": "Finance",
        "document_type": "Journal Entry",
        "mapping": {
            "posting_date": {"source": "system", "value": "today"},
            "title": {"source": "fixed", "value": "هزینه عمومی {{Subject}}"},
        },
    },
    {
        "key": "shipping_cost",
        "title": "هزینه حمل و نقل",
        "description": "ثبت هزینه حمل و نقل بر اساس درخواست خرید",
        "icon": "truck",
        "module": "Finance",
        "document_type": "Journal Entry",
        "mapping": {
            "posting_date": {"source": "system", "value": "today"},
            "title": {"source": "fixed", "value": "هزینه حمل بابت درخواست {{RequestNo}}"},
        },
    },
    {
        "key": "purchase_material_request",
        "title": "درخواست خرید کالا",
        "description": "ایجاد درخواست خرید کالا در ERPNext از اقلام درخواست",
        "icon": "box",
        "module": "Purchase",
        "document_type": "Material Request",
        "mapping": {
            "transaction_date": {"source": "system", "value": "today"},
            "schedule_date": {"source": "system", "value": "today"},
        },
    },
]
