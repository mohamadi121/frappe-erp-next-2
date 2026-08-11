import json

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.api.v1.workflow_runtime import start_workflow_instance
from asoud_erp.services.purchase_request import normalize_purchase_items


def _workflow_for_company(company: str) -> str:
    names = frappe.get_all(
        "ASOUD Workflow Definition",
        filters={
            "company": company,
            "target_doctype": "Material Request",
            "module_key": "Purchase",
            "status": "Active",
            "readiness_status": "Ready",
        },
        pluck="name",
        order_by="modified desc",
        limit_page_length=2,
    )
    if not names:
        frappe.throw(_("No active purchase request workflow is available for this company"))
    if len(names) > 1:
        frappe.throw(_("More than one active purchase request workflow is configured"))
    return names[0]


def _serialize(doc, workflow_instance: str = "") -> dict:
    return {
        "name": doc.name,
        "company": doc.company,
        "transaction_date": str(doc.transaction_date),
        "schedule_date": str(doc.schedule_date),
        "status": doc.status,
        "workflow_instance": workflow_instance,
        "items": [
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "qty": float(row.qty or 0),
                "uom": row.uom,
                "warehouse": row.warehouse or "",
            }
            for row in doc.items
        ],
    }


@frappe.whitelist(methods=["POST"])
def create_purchase_request(
    company: str,
    schedule_date: str,
    items: str | list[dict],
    subject: str | None = None,
) -> dict:
    frappe.only_for(
        ("System Manager", "Purchase Manager", "Purchase User", "Accounts Manager")
    )
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company does not exist"))
    requested_date = getdate(schedule_date)
    if requested_date < getdate(nowdate()):
        frappe.throw(_("Required-by date cannot be in the past"))
    try:
        rows = normalize_purchase_items(items)
    except (ValueError, json.JSONDecodeError) as error:
        frappe.throw(_(str(error)))
    workflow = _workflow_for_company(company)
    doc = frappe.get_doc(
        {
            "doctype": "Material Request",
            "material_request_type": "Purchase",
            "company": company,
            "transaction_date": nowdate(),
            "schedule_date": requested_date,
        }
    )
    for row in rows:
        doc.append("items", {**row, "schedule_date": requested_date})
    doc.insert()
    label = (subject or "").strip() or f"درخواست خرید {doc.name}"
    result = start_workflow_instance(
        definition=workflow,
        subject=label,
        reference_doctype="Material Request",
        reference_name=doc.name,
    )
    instance = result.get("data", {}).get("name", "")
    return success(_serialize(doc, workflow_instance=instance))


@frappe.whitelist()
def purchase_request_options(company: str) -> dict:
    frappe.only_for(
        ("System Manager", "Purchase Manager", "Purchase User", "Accounts Manager")
    )
    items = frappe.get_all(
        "Item",
        filters={"disabled": 0, "is_purchase_item": 1},
        fields=["name", "item_name", "stock_uom"],
        order_by="item_name asc",
        limit_page_length=500,
    )
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"company": company, "disabled": 0, "is_group": 0},
        fields=["name", "warehouse_name"],
        order_by="warehouse_name asc",
        limit_page_length=200,
    )
    return success({"items": items, "warehouses": warehouses})


@frappe.whitelist()
def list_my_purchase_requests(company: str) -> dict:
    frappe.only_for(
        ("System Manager", "Purchase Manager", "Purchase User", "Accounts Manager")
    )
    rows = frappe.get_all(
        "Material Request",
        filters={
            "company": company,
            "material_request_type": "Purchase",
            "owner": frappe.session.user,
        },
        fields=["name", "transaction_date", "schedule_date", "status", "per_ordered"],
        order_by="creation desc",
        limit_page_length=200,
    )
    for row in rows:
        row["workflow_instance"] = frappe.db.get_value(
            "ASOUD Workflow Instance",
            {"reference_doctype": "Material Request", "reference_name": row.name},
            "name",
        ) or ""
    return success(rows, meta={"total": len(rows)})
