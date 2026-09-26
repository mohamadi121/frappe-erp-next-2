"""Home and settings dashboard figures, read from ERPNext and Frappe records.

A figure the current user may not read is returned as ``null`` (never ``0``), so
the client can show "no data" instead of a false zero.
"""

import frappe
from frappe.utils import add_to_date, flt, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services import erp_documents
from asoud_erp.services.request_access import require_company

ONLINE_MINUTES = 15
STUCK_SYNC_MINUTES = 10


def _can_read(doctype: str) -> bool:
    return bool(frappe.has_permission(doctype, "read"))


def _sum(doctype: str, field: str, filters: dict) -> float | None:
    if not _can_read(doctype):
        return None
    rows = frappe.get_list(doctype, filters=filters, fields=[f"sum({field}) as total"])
    return flt(rows[0].total if rows else 0)


def _count(doctype: str, filters: dict) -> int | None:
    if not _can_read(doctype):
        return None
    rows = frappe.get_list(doctype, filters=filters, fields=["count(name) as total"])
    return int(rows[0].total or 0) if rows else 0


def _bank_and_cash(company: str) -> dict | None:
    from erpnext.accounts.utils import get_balance_on

    if not _can_read("Account") or not _can_read("GL Entry"):
        return None
    accounts = frappe.get_list(
        "Account",
        filters={"company": company, "is_group": 0, "disabled": 0,
                 "account_type": ["in", ["Bank", "Cash"]]},
        fields=["name", "account_name", "account_type"],
        order_by="account_type asc, account_name asc",
    )
    rows = [
        {
            "account": row.name,
            "account_name": row.account_name,
            "account_type": row.account_type,
            "balance": flt(get_balance_on(account=row.name, date=nowdate(), company=company,
                                          in_account_currency=False)),
        }
        for row in accounts
    ]
    return {"total": flt(sum(row["balance"] for row in rows)), "accounts": rows}


def _open_documents(company: str) -> dict:
    counts = {
        "unpaid_sales_invoices": _count("Sales Invoice", {
            "company": company, "docstatus": 1, "outstanding_amount": [">", 0]}),
        "unpaid_purchase_invoices": _count("Purchase Invoice", {
            "company": company, "docstatus": 1, "outstanding_amount": [">", 0]}),
        "draft_sales_invoices": _count("Sales Invoice", {"company": company, "docstatus": 0}),
        "draft_payment_entries": _count("Payment Entry", {"company": company, "docstatus": 0}),
        "draft_journal_entries": _count("Journal Entry", {"company": company, "docstatus": 0}),
        "pending_material_requests": _count("Material Request", {
            "company": company, "docstatus": 1, "status": ["in", ["Pending", "Partially Ordered"]]}),
        "my_open_tasks": frappe.db.count("ASOUD Workflow Task", {
            "assigned_to": frappe.session.user, "status": "Open"}),
    }
    known = [value for value in counts.values() if value is not None]
    return {**counts, "total": sum(known)}


@frappe.whitelist()
def get_home_summary(company: str) -> dict:
    """Figures of the home dashboard for one company, for today."""
    require_company(company)
    today = nowdate()
    return success({
        "company": company,
        "date": today,
        "currency": frappe.get_cached_value("Company", company, "default_currency"),
        "today_receipts": _sum("Payment Entry", "base_received_amount", {
            "company": company, "docstatus": 1, "payment_type": "Receive", "posting_date": today}),
        "today_payments": _sum("Payment Entry", "base_paid_amount", {
            "company": company, "docstatus": 1, "payment_type": "Pay", "posting_date": today}),
        # Credit notes are negative, so this is net sales.
        "today_sales": _sum("Sales Invoice", "base_grand_total", {
            "company": company, "docstatus": 1, "posting_date": today}),
        "bank_and_cash": _bank_and_cash(company),
        "open_documents": _open_documents(company),
    })


def _storage() -> dict:
    files = frappe.db.sql("select coalesce(sum(file_size), 0) from `tabFile` where is_folder = 0")[0][0]
    database = frappe.db.sql(
        "select coalesce(sum(data_length + index_length), 0) from information_schema.tables"
        " where table_schema = %s", frappe.conf.db_name)[0][0]
    limits = frappe.conf.get("limits") or {}
    quota_gb = limits.get("space")
    return {
        "files_bytes": int(files),
        "database_bytes": int(database),
        "used_bytes": int(files) + int(database),
        "quota_bytes": int(flt(quota_gb) * 1024**3) if quota_gb else None,
    }


@frappe.whitelist()
def get_system_summary() -> dict:
    """Site health for the settings dashboard. System Manager only."""
    erp_documents.require_roles("System Manager")
    from frappe.utils.scheduler import is_scheduler_disabled

    system_users = {"user_type": "System User", "name": ["not in", frappe.STANDARD_USERS]}
    since_online = add_to_date(now_datetime(), minutes=-ONLINE_MINUTES)
    since_day = add_to_date(now_datetime(), hours=-24)
    stuck_before = add_to_date(now_datetime(), minutes=-STUCK_SYNC_MINUTES)
    last_sync = frappe.get_all("ASOUD API Request", filters={"status": "Completed"},
                               fields=["modified"], order_by="modified desc", limit_page_length=1)
    return success({
        "users": {
            "total": frappe.db.count("User", system_users),
            "active": frappe.db.count("User", {**system_users, "enabled": 1}),
            "online": frappe.db.count("User", {**system_users, "enabled": 1,
                                               "last_active": [">=", since_online]}),
            "online_window_minutes": ONLINE_MINUTES,
        },
        "storage": _storage(),
        "pending_workflow_tasks": frappe.db.count("ASOUD Workflow Task", {"status": "Open"}),
        "errors_last_24h": frappe.db.count("Error Log", {"creation": [">=", since_day]}),
        "sync": {
            "last_completed_on": str(last_sync[0].modified) if last_sync else None,
            "stuck_requests": frappe.db.count("ASOUD API Request", {
                "status": "Processing", "modified": ["<", stuck_before]}),
        },
        "scheduler_enabled": not is_scheduler_disabled(verbose=False),
    })
