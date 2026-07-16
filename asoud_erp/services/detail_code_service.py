import frappe
from frappe import _


def next_detail_code(detail_group: str, digits: int) -> str:
    group = frappe.get_doc("ASOUD Detail Group", detail_group)
    prefix = str(group.group_code).strip()
    if not prefix.isdigit():
        frappe.throw(_("Detail group code must be numeric"))

    last_code = frappe.db.get_value(
        "ASOUD Floating Detail",
        {"detail_group": detail_group},
        "detail_code",
        order_by="detail_code desc",
    )
    sequence = 1
    if last_code and str(last_code).startswith(prefix):
        suffix = str(last_code)[len(prefix) :]
        sequence = int(suffix or 0) + 1

    return f"{prefix}{sequence:0{digits}d}"

