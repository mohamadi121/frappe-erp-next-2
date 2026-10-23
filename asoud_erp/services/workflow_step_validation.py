"""Pure validation for workflow step responses bound to request values."""

from decimal import Decimal, InvalidOperation

NUMERIC_TYPES = {"Number", "Currency"}


def _number(value, label):
    try:
        result = Decimal(str(value).strip())
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"مقدار «{label}» باید عدد معتبر باشد.") from None


def request_values_for_instance(frappe, instance):
    if instance.reference_doctype != "ASOUD Workflow Request" or not instance.reference_name:
        return {}
    raw = frappe.db.get_value("ASOUD Workflow Request", instance.reference_name, "values_json") or "{}"
    return frappe.parse_json(raw) if isinstance(raw, str) else raw


def project_request_rows(fields, request_values, response):
    """Seed and protect request-derived table rows while retaining handler values."""
    result = dict(response or {})
    for field in fields:
        source_key = field.get("rows_from_request")
        if field.get("type") != "Table" or not source_key:
            continue
        source_rows = request_values.get(source_key)
        if not isinstance(source_rows, list) or any(not isinstance(row, dict) for row in source_rows):
            raise ValueError(f"ردیف‌های درخواست برای «{field.get('label', field.get('key'))}» معتبر نیستند.")
        supplied = result.get(field["key"])
        if supplied is None:
            supplied = [{} for _ in source_rows]
        if not isinstance(supplied, list) or len(supplied) != len(source_rows):
            raise ValueError(f"تعداد ردیف‌های «{field.get('label', field.get('key'))}» نباید تغییر کند.")
        request_columns = {
            column["key"] for column in field.get("columns", [])
            if column.get("readonly") is True and column.get("key")
        }
        projected = []
        for index, source_row in enumerate(source_rows):
            if not isinstance(supplied[index], dict):
                raise ValueError("ساختار ردیف پاسخ معتبر نیست.")
            row = dict(supplied[index])
            for key in request_columns:
                if key not in source_row:
                    raise ValueError(f"ستون «{key}» در ردیف درخواست وجود ندارد.")
                if key in row and row[key] != source_row[key]:
                    raise ValueError("اطلاعات فقط‌خواندنی درخواست قابل تغییر نیست.")
                row[key] = source_row[key]
            projected.append(row)
        result[field["key"]] = projected
    return result


def validate_request_bounds(fields, request_values, response):
    response = project_request_rows(fields, request_values, response)
    for field in fields:
        label = field.get("label", field.get("key", "فیلد"))
        value = response.get(field.get("key"))
        if field.get("type") in NUMERIC_TYPES and value not in (None, ""):
            numeric = _number(value, label)
            if "min_value_exclusive" in field:
                minimum = _number(field["min_value_exclusive"], label)
                if numeric <= minimum:
                    raise ValueError(f"مقدار «{label}» باید بیشتر از {field['min_value_exclusive']} باشد.")
            request_key = field.get("max_from_request")
            if request_key and numeric > _number(request_values.get(request_key), label):
                raise ValueError(f"مقدار «{label}» نباید از مقدار درخواست‌شده بیشتر باشد.")
            reason_key = field.get("reason_required_if_less_than")
            if reason_key and numeric < _number(request_values.get(reason_key), label):
                reason = response.get(field.get("reason_field"))
                if not isinstance(reason, str) or not reason.strip():
                    raise ValueError("ثبت علت کاهش الزامی است.")
        if field.get("type") != "Table" or not field.get("rows_from_request"):
            continue
        rows = response[field["key"]]
        source_rows = request_values[field["rows_from_request"]]
        for index, row in enumerate(rows):
            for column in field.get("columns", []):
                source_column = column.get("max_from_row")
                column_value = row.get(column.get("key"))
                if source_column and column_value not in (None, ""):
                    column_label = f"{column.get('label', column.get('key'))} در ردیف {index + 1}"
                    if _number(column_value, column_label) > _number(source_rows[index].get(source_column), column_label):
                        raise ValueError(f"مقدار «{column_label}» نباید از مقدار درخواست‌شده بیشتر باشد.")
    return response
