import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.detail_code_service import next_detail_code


@frappe.whitelist()
def preview_next_detail_code(detail_group: str) -> dict:
    """Return the next server-generated detail code without creating a row."""
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if not frappe.db.exists("ASOUD Detail Group", detail_group):
        frappe.throw(_("Detail group does not exist"))
    settings = frappe.get_single("ASOUD Settings")
    return success(
        {
            "detail_group": detail_group,
            "detail_code": next_detail_code(
                detail_group, int(settings.detail_code_digits or 5)
            ),
        }
    )


@frappe.whitelist()
def list_floating_details(detail_group: str | None = None, search: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    filters: dict = {"disabled": 0}
    if detail_group:
        filters["detail_group"] = detail_group
    or_filters = None
    if search:
        or_filters = {"title": ["like", f"%{search}%"], "detail_code": ["like", f"%{search}%"]}
    rows = frappe.get_all(
        "ASOUD Floating Detail",
        filters=filters,
        or_filters=or_filters,
        fields=["name", "detail_code", "title", "detail_type", "detail_group", "linked_doctype", "linked_document"],
        order_by="detail_code asc",
        limit_page_length=200,
    )
    for row in rows:
        row["group_title"] = frappe.db.get_value(
            "ASOUD Detail Group", row["detail_group"], "group_name"
        )
    return success(rows)


@frappe.whitelist(methods=["POST"])
def create_floating_detail(
    title: str,
    detail_type: str,
    detail_group: str,
    linked_doctype: str | None = None,
    linked_document: str | None = None,
    detail_code: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if not title or len(title.strip()) < 3:
        frappe.throw(_("Title must contain at least 3 characters"))
    if not frappe.db.exists("ASOUD Detail Group", detail_group):
        frappe.throw(_("Detail group does not exist"))

    settings = frappe.get_single("ASOUD Settings")
    code = detail_code
    if settings.auto_generate_detail_code or not code:
        code = next_detail_code(detail_group, int(settings.detail_code_digits or 5))

    doc = frappe.get_doc(
        {
            "doctype": "ASOUD Floating Detail",
            "detail_code": code,
            "title": title.strip(),
            "detail_type": detail_type,
            "detail_group": detail_group,
            "linked_doctype": linked_doctype,
            "linked_document": linked_document,
        }
    )
    doc.insert()
    result = doc.as_dict()
    result["group_title"] = frappe.db.get_value(
        "ASOUD Detail Group", doc.detail_group, "group_name"
    )
    return success(result)


@frappe.whitelist(methods=["POST"])
def link_floating_detail(name: str, party_profile: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    if not frappe.db.exists("ASOUD Party Profile", party_profile):
        frappe.throw(_("Party profile does not exist"))
    doc = frappe.get_doc("ASOUD Floating Detail", name)
    if doc.disabled:
        frappe.throw(_("Disabled floating detail cannot be linked"))
    if doc.linked_document and (
        doc.linked_doctype != "ASOUD Party Profile"
        or doc.linked_document != party_profile
    ):
        frappe.throw(_("Floating detail is already linked to another document"))
    doc.linked_doctype = "ASOUD Party Profile"
    doc.linked_document = party_profile
    doc.save()
    return success({"name": doc.name, "linked_document": party_profile})


@frappe.whitelist(methods=["POST"])
def disable_floating_detail(name: str) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager"))
    doc = frappe.get_doc("ASOUD Floating Detail", name)
    doc.disabled = 1
    doc.save()
    return success({"name": doc.name, "disabled": True})

