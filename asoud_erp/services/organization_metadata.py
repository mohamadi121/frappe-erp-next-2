"""Optional metadata on the native Department; no parallel organizational store."""

DESCRIPTION_FIELD = "asoud_description"


def description_value(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("توضیحات واحد باید متن باشد.")
    if len(value) > 2000:
        raise ValueError("توضیحات واحد حداکثر ۲۰۰۰ نویسه است.")
    return value.strip()


def ensure_department_description():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields({"Department": [{
        "fieldname": DESCRIPTION_FIELD, "label": "توضیحات واحد", "fieldtype": "Small Text",
        "insert_after": "disabled", "module": "ASOUD ERP",
    }]}, update=True)
