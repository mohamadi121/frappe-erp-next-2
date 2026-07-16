import json

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.detail_code_service import next_detail_code
from asoud_erp.services.party_validation import (
    is_valid_iranian_legal_id,
    is_valid_iranian_mobile,
    is_valid_iranian_national_code,
    normalize_optional,
)

ALLOWED_ROLES = {"Customer", "Supplier", "Employee", "Shareholder", "Other"}
ROLE_DETAIL_GROUP = {"Customer": "10000", "Supplier": "20000", "Employee": "30000"}


def _parse_roles(roles: str | list[str]) -> list[str]:
    values = json.loads(roles) if isinstance(roles, str) else roles
    normalized = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    invalid = set(normalized) - ALLOWED_ROLES
    if invalid or not normalized:
        frappe.throw(_("Select at least one valid party role"))
    return normalized


def _ensure_customer(title: str, party_type: str, national_id: str | None) -> str:
    existing = frappe.db.exists("Customer", {"tax_id": national_id}) if national_id else None
    if existing:
        return str(existing)
    doc = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": title,
            "customer_type": "Individual" if party_type == "Individual" else "Company",
            "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group"),
            "territory": frappe.db.get_single_value("Selling Settings", "territory"),
            "tax_id": national_id,
        }
    )
    doc.insert()
    return doc.name


def _ensure_supplier(title: str, party_type: str, national_id: str | None) -> str:
    existing = frappe.db.exists("Supplier", {"tax_id": national_id}) if national_id else None
    if existing:
        return str(existing)
    doc = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": title,
            "supplier_type": "Individual" if party_type == "Individual" else "Company",
            "supplier_group": frappe.db.get_single_value("Buying Settings", "supplier_group"),
            "tax_id": national_id,
        }
    )
    doc.insert()
    return doc.name


def _sync_floating_details(profile_name: str, title: str, roles: list[str]) -> None:
    settings = frappe.get_single("ASOUD Settings")
    digits = int(settings.detail_code_digits or 5)
    for role, group in ROLE_DETAIL_GROUP.items():
        if role not in roles or not frappe.db.exists("ASOUD Detail Group", group):
            continue
        exists = frappe.db.exists(
            "ASOUD Floating Detail",
            {"linked_doctype": "ASOUD Party Profile", "linked_document": profile_name, "detail_group": group},
        )
        if exists:
            frappe.db.set_value("ASOUD Floating Detail", exists, "title", title)
            continue
        frappe.get_doc(
            {
                "doctype": "ASOUD Floating Detail",
                "detail_code": next_detail_code(group, digits),
                "title": title,
                "detail_type": role,
                "detail_group": group,
                "linked_doctype": "ASOUD Party Profile",
                "linked_document": profile_name,
            }
        ).insert()


@frappe.whitelist()
def list_parties(search: str | None = None, role: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters = {"disabled": 0}
    if role:
        filters["roles_text"] = ["like", f'%"{role}"%']
    or_filters = None
    if search:
        term = f"%{search}%"
        or_filters = {"display_name": ["like", term], "national_id": ["like", term], "mobile": ["like", term]}
    rows = frappe.get_all(
        "ASOUD Party Profile",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "party_type",
            "display_name",
            "national_id",
            "mobile",
            "email",
            "roles_text",
            "customer",
            "supplier",
            "employee",
            "disabled",
        ],
        order_by="modified desc",
        limit_page_length=200,
    )
    for row in rows:
        row["roles"] = json.loads(row.pop("roles_text") or "[]")
    return success(rows)


@frappe.whitelist(methods=["POST"])
def save_party(
    party_type: str,
    display_name: str,
    roles: str | list[str],
    national_id: str | None = None,
    mobile: str | None = None,
    email: str | None = None,
    name: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if party_type not in {"Individual", "Organization"}:
        frappe.throw(_("Party type must be Individual or Organization"))
    if not display_name or len(display_name.strip()) < 3:
        frappe.throw(_("Display name must contain at least 3 characters"))
    selected_roles = _parse_roles(roles)
    national_id = normalize_optional(national_id)
    mobile = normalize_optional(mobile)
    email = normalize_optional(email)
    if national_id and party_type == "Individual" and not is_valid_iranian_national_code(national_id):
        frappe.throw(_("Iranian national code is not valid"))
    if national_id and party_type == "Organization" and not is_valid_iranian_legal_id(national_id):
        frappe.throw(_("Iranian legal entity ID must contain 11 valid digits"))
    if mobile and not is_valid_iranian_mobile(mobile):
        frappe.throw(_("Iranian mobile number is not valid"))

    if name:
        doc = frappe.get_doc("ASOUD Party Profile", name)
    else:
        duplicate = frappe.db.exists("ASOUD Party Profile", {"national_id": national_id}) if national_id else None
        if duplicate:
            frappe.throw(_("A party with this national ID already exists"))
        doc = frappe.new_doc("ASOUD Party Profile")

    title = display_name.strip()
    doc.party_type = party_type
    doc.display_name = title
    doc.national_id = national_id
    doc.mobile = mobile
    doc.email = email
    doc.roles_text = json.dumps(selected_roles)
    if "Customer" in selected_roles and not doc.customer:
        doc.customer = _ensure_customer(title, party_type, national_id)
    if "Supplier" in selected_roles and not doc.supplier:
        doc.supplier = _ensure_supplier(title, party_type, national_id)
    doc.save() if name else doc.insert()
    _sync_floating_details(doc.name, title, selected_roles)

    result = doc.as_dict()
    result["roles"] = selected_roles
    result.pop("roles_text", None)
    return success(result)
