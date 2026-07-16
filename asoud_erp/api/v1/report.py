import frappe
from frappe import _
from frappe.utils import getdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.reporting_service import running_balance


def _validate_period(from_date: str, to_date: str):
    start = getdate(from_date)
    end = getdate(to_date)
    if start > end:
        frappe.throw(_("From date cannot be after to date"))
    return start, end


def _account_scope(company: str, account: str | None) -> list[str] | None:
    if not account:
        return None
    account_company = frappe.db.get_value("Account", account, "company")
    if account_company != company:
        frappe.throw(_("Account does not belong to the selected company"))
    return [account, *frappe.get_descendants_of("Account", account)]


def _base_filters(company: str, accounts: list[str] | None = None) -> dict:
    filters: dict = {"company": company, "is_cancelled": 0}
    if accounts:
        filters["account"] = ["in", accounts]
    return filters


@frappe.whitelist()
def trial_balance(company: str, from_date: str, to_date: str, account: str | None = None) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    start, end = _validate_period(from_date, to_date)
    accounts = _account_scope(company, account)
    account_condition = " and account in %(accounts)s" if accounts else ""
    params = {"company": company, "from_date": start, "to_date": end, "accounts": tuple(accounts or [])}
    rows = frappe.db.sql(
        f"""
        select account,
          sum(case when posting_date < %(from_date)s then debit - credit else 0 end) as opening,
          sum(case when posting_date between %(from_date)s and %(to_date)s then debit else 0 end) as debit,
          sum(case when posting_date between %(from_date)s and %(to_date)s then credit else 0 end) as credit
        from `tabGL Entry`
        where company = %(company)s and is_cancelled = 0 and posting_date <= %(to_date)s
        {account_condition}
        group by account
        order by account
        """,
        params,
        as_dict=True,
    )
    opening_debit_total = opening_credit_total = 0.0
    total_debit = total_credit = 0.0
    closing_debit_total = closing_credit_total = 0.0
    result = []
    for row in rows:
        opening = float(row.opening or 0)
        debit = float(row.debit or 0)
        credit = float(row.credit or 0)
        closing = opening + debit - credit
        opening_debit_total += max(opening, 0)
        opening_credit_total += max(-opening, 0)
        total_debit += debit
        total_credit += credit
        closing_debit_total += max(closing, 0)
        closing_credit_total += max(-closing, 0)
        result.append(
            {
                "account": row.account,
                "opening_debit": max(opening, 0),
                "opening_credit": max(-opening, 0),
                "period_debit": debit,
                "period_credit": credit,
                "closing_debit": max(closing, 0),
                "closing_credit": max(-closing, 0),
            }
        )
    return success(
        {
            "rows": result,
            "totals": {
                "opening_debit": opening_debit_total,
                "opening_credit": opening_credit_total,
                "period_debit": total_debit,
                "period_credit": total_credit,
                "closing_debit": closing_debit_total,
                "closing_credit": closing_credit_total,
            },
        }
    )


@frappe.whitelist()
def general_ledger(
    company: str,
    from_date: str,
    to_date: str,
    account: str,
    party_type: str | None = None,
    party: str | None = None,
) -> dict:
    frappe.only_for(("System Manager", "Accounts Manager", "Accounts User"))
    start, end = _validate_period(from_date, to_date)
    accounts = _account_scope(company, account) or [account]
    filters = _base_filters(company, accounts)
    if party_type:
        filters["party_type"] = party_type
    if party:
        filters["party"] = party
    opening_filters = {**filters, "posting_date": ["<", start]}
    opening_rows = frappe.get_all("GL Entry", filters=opening_filters, fields=["debit", "credit"])
    opening = sum(float(row.debit or 0) - float(row.credit or 0) for row in opening_rows)
    filters["posting_date"] = ["between", [start, end]]
    rows = frappe.get_all(
        "GL Entry",
        filters=filters,
        fields=[
            "name",
            "posting_date",
            "account",
            "party_type",
            "party",
            "voucher_type",
            "voucher_no",
            "against",
            "remarks",
            "debit",
            "credit",
            "cost_center",
            "project",
        ],
        order_by="posting_date asc, creation asc",
        limit_page_length=5000,
    )
    serialized = running_balance(opening, [dict(row) for row in rows])
    for row in serialized:
        row["posting_date"] = str(row["posting_date"])
        row["debit"] = float(row.get("debit") or 0)
        row["credit"] = float(row.get("credit") or 0)
        row["balance"] = float(row["balance"])
    return success(
        {
            "opening_balance": opening,
            "entries": serialized,
            "total_debit": sum(row["debit"] for row in serialized),
            "total_credit": sum(row["credit"] for row in serialized),
            "closing_balance": serialized[-1]["balance"] if serialized else opening,
        }
    )
