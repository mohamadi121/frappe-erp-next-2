import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.account_code_service import next_account_code
from asoud_erp.services.chart_template_service import template_rows


def _account_level(company: str, account_number: str | None, is_group: int | bool) -> str:
    if not int(is_group):
        return "Ledger"
    setup = frappe.get_doc("ASOUD Company Setup", company)
    length = len(str(account_number or ""))
    return "Group" if length <= int(setup.group_code_digits or 1) else "General"


def _resolve_parent_account(company: str, value: str | None) -> str | None:
    """Accept an ERPNext account name or its ASOUD account code for imports."""
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if frappe.db.exists("Account", {"name": candidate, "company": company, "is_group": 1}):
        return candidate
    return frappe.db.get_value(
        "Account",
        {"company": company, "account_number": candidate, "is_group": 1},
        "name",
    )


@frappe.whitelist()
def list_accounts(company: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "account_number": ["is", "set"]},
        fields=[
            "name",
            "account_number",
            "account_name",
            "parent_account",
            "root_type",
            "is_group",
            "disabled",
            "account_type",
        ],
        order_by="account_number asc",
        limit_page_length=0,
    )
    for row in rows:
        row["asoud_level"] = _account_level(company, row.account_number, row.is_group)
    return success(rows)


@frappe.whitelist()
def preview_next_code(company: str, level: str, parent_account: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    return success({"account_number": next_account_code(company, level, parent_account)})


@frappe.whitelist(methods=["POST"])
def create_account(
    company: str,
    account_name: str,
    level: str,
    parent_account: str | None = None,
    account_number: str | None = None,
    auto_code: int | bool = 1,
    root_type: str | None = None,
    account_type: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not account_name or len(account_name.strip()) < 3:
        frappe.throw(_("Account name must contain at least 3 characters"))
    if level == "Group" and not parent_account:
        parent_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": root_type or "Asset",
                "is_group": 1,
                "parent_account": ["is", "not set"],
            },
            "name",
        )
    if not parent_account:
        frappe.throw(_("A valid parent account is required"))
    if not frappe.db.exists(
        "Account", {"name": parent_account, "company": company, "is_group": 1}
    ):
        frappe.throw(_("Parent account is not a group in the selected company"))
    code = next_account_code(company, level, parent_account) if auto_code or not account_number else account_number
    is_group = 1 if level in {"Group", "General"} else 0
    doc = frappe.get_doc(
        {
            "doctype": "Account",
            "company": company,
            "account_name": account_name.strip(),
            "account_number": code,
            "parent_account": parent_account,
            "is_group": is_group,
            "root_type": root_type,
            "account_type": account_type,
        }
    )
    doc.insert()
    result = doc.as_dict()
    result["asoud_level"] = level
    return success(result)


@frappe.whitelist(methods=["POST"])
def import_accounts(company: str, rows: str | list[dict]) -> dict:
    """Import a validated batch atomically; Frappe rolls the request back on failure."""
    frappe.only_for(("System Manager", "Accounts Manager"))
    payload = json.loads(rows) if isinstance(rows, str) else rows
    if not isinstance(payload, list) or not payload or len(payload) > 500:
        frappe.throw(_("The import must contain between 1 and 500 rows"))

    created = []
    for index, row in enumerate(payload, start=2):
        if not isinstance(row, dict):
            frappe.throw(_("Invalid row at line {0}").format(index))
        level = str(row.get("level") or "").strip()
        if level not in {"Group", "General", "Ledger"}:
            frappe.throw(_("Invalid account level at line {0}").format(index))
        parent = _resolve_parent_account(company, row.get("parent_account"))
        if row.get("parent_account") and not parent:
            frappe.throw(_("Parent account was not found at line {0}").format(index))
        response = create_account(
            company=company,
            account_name=str(row.get("account_name") or ""),
            level=level,
            parent_account=parent,
            account_number=row.get("account_number"),
            auto_code=0 if row.get("account_number") else 1,
            root_type=row.get("root_type") or "Asset",
            account_type=row.get("account_type"),
        )
        created.append(response["data"])
    return success(created)


@frappe.whitelist()
def preview_chart_template(company: str, template: str = "Iran Standard") -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company does not exist"))
    try:
        rows = template_rows(template)
    except ValueError as exc:
        frappe.throw(_(str(exc)))
    return success({"company": company, "template": template, "rows": rows})


@frappe.whitelist(methods=["POST"])
def apply_chart_template(company: str, template: str = "Iran Standard") -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company does not exist"))
    rows = template_rows(template)
    created_by_key: dict[str, str] = {}
    created = []
    for row in rows:
        existing = frappe.db.exists(
            "Account", {"company": company, "account_number": row["key"]}
        )
        if existing:
            created_by_key[row["key"]] = existing
            continue
        parent = created_by_key.get(row.get("parent_key"))
        response = create_account(
            company=company,
            account_name=row["title"],
            level=row["level"],
            parent_account=parent,
            account_number=row["key"],
            auto_code=0,
            root_type=row["root_type"],
        )
        data = response["data"]
        created_by_key[row["key"]] = data["name"]
        created.append(data)
    return success(created, meta={"template": template, "created_count": len(created)})


@frappe.whitelist(methods=["POST"])
def update_account(
    company: str,
    account: str,
    account_name: str,
    parent_account: str | None = None,
    disabled: int | bool = 0,
    root_type: str | None = None,
    account_type: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    if not frappe.db.exists("Account", {"name": account, "company": company}):
        frappe.throw(_("Account does not belong to the selected company"))
    title = str(account_name or "").strip()
    if len(title) < 3:
        frappe.throw(_("Account name must contain at least 3 characters"))
    if parent_account and not frappe.db.exists(
        "Account", {"name": parent_account, "company": company, "is_group": 1}
    ):
        frappe.throw(_("Parent account is not a group in the selected company"))
    doc = frappe.get_doc("Account", account)
    doc.account_name = title
    doc.parent_account = parent_account
    doc.disabled = int(bool(disabled))
    if root_type:
        doc.root_type = root_type
    if account_type is not None:
        doc.account_type = account_type
    doc.save()
    result = doc.as_dict()
    result["asoud_level"] = _account_level(company, doc.account_number, doc.is_group)
    return success(result)
