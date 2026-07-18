import frappe
from frappe import _

from asoud_erp.api.v1.responses import success

DEFAULT_GROUPS = (
    ("10000", "مشتریان"),
    ("20000", "تأمین‌کنندگان"),
    ("30000", "پرسنل"),
    ("40000", "بانک‌ها"),
    ("50000", "صندوق‌ها"),
    ("60000", "مراکز هزینه"),
    ("70000", "پروژه‌ها"),
    ("90000", "سایر"),
)


@frappe.whitelist()
def list_detail_groups(include_disabled: int | bool = 0) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters = {} if int(include_disabled) else {"disabled": 0}
    rows = frappe.get_all(
        "ASOUD Detail Group",
        filters=filters,
        fields=["name", "group_code", "group_name", "disabled"],
        order_by="group_code asc",
        limit_page_length=0,
    )
    return success(rows)


@frappe.whitelist(methods=["POST"])
def seed_default_detail_groups() -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    created = []
    for code, title in DEFAULT_GROUPS:
        if frappe.db.exists("ASOUD Detail Group", code):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "ASOUD Detail Group",
                "group_code": code,
                "group_name": title,
            }
        )
        doc.insert()
        created.append(doc.as_dict())
    return success(created, meta={"created_count": len(created)})


@frappe.whitelist(methods=["POST"])
def save_detail_group(
    group_code: str,
    group_name: str,
    name: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    code = str(group_code or "").strip()
    title = str(group_name or "").strip()
    if not code.isdigit() or not 3 <= len(code) <= 12:
        frappe.throw(_("Detail group code must contain 3 to 12 digits"))
    if len(title) < 2:
        frappe.throw(_("Detail group name must contain at least 2 characters"))
    existing = frappe.db.exists("ASOUD Detail Group", name) if name else None
    duplicate = frappe.db.exists("ASOUD Detail Group", {"group_code": code})
    if duplicate and duplicate != existing:
        frappe.throw(_("Detail group code already exists"))
    doc = (
        frappe.get_doc("ASOUD Detail Group", existing)
        if existing
        else frappe.new_doc("ASOUD Detail Group")
    )
    doc.group_code = code
    doc.group_name = title
    doc.disabled = 0
    doc.save() if existing else doc.insert()
    return success(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def disable_detail_group(name: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("ASOUD Detail Group", name):
        frappe.throw(_("Detail group does not exist"))
    doc = frappe.get_doc("ASOUD Detail Group", name)
    doc.disabled = 1
    doc.save()
    return success(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def save_account_mapping(company: str, account: str, detail_group: str, enabled: int | bool = 1) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("Account", {"name": account, "company": company}):
        frappe.throw(_("Account does not belong to the selected company"))
    if int(frappe.db.get_value("Account", account, "is_group") or 0):
        frappe.throw(_("Floating details can only be mapped to a ledger account"))
    if not frappe.db.exists("ASOUD Detail Group", detail_group):
        frappe.throw(_("Detail group does not exist"))

    name = frappe.db.exists(
        "ASOUD Account Mapping",
        {"company": company, "account": account, "detail_group": detail_group},
    )
    doc = frappe.get_doc("ASOUD Account Mapping", name) if name else frappe.new_doc("ASOUD Account Mapping")
    doc.company = company
    doc.account = account
    doc.detail_group = detail_group
    doc.allow_floating_detail = 1
    doc.disabled = 0 if int(enabled) else 1
    doc.save() if name else doc.insert()
    return success(doc.as_dict())


@frappe.whitelist()
def list_account_mappings(company: str, account: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters = {"company": company, "disabled": 0}
    if account:
        filters["account"] = account
    rows = frappe.get_all(
        "ASOUD Account Mapping",
        filters=filters,
        fields=["name", "company", "account", "detail_group", "allow_floating_detail"],
        order_by="account asc, detail_group asc",
        limit_page_length=0,
    )
    return success(rows)
