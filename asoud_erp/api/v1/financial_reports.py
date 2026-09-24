"""ERPNext's standard financial and stock reports, run through Frappe's report runner.

`frappe.desk.query_report.run` applies each report's own role list (for example
Accounts User / Accounts Manager / Auditor for the balance sheet), so there is
no separate role table here. Rows are returned as ERPNext computes them.
"""

import frappe
from frappe import _

from asoud_erp.api.v1.responses import success
from asoud_erp.services.financial_reports import REPORTS, report_filters
from asoud_erp.services.request_access import require_company

MAX_ROWS = 2000


def _columns(columns: list) -> list[dict]:
    result = []
    for column in columns or []:
        if isinstance(column, dict):
            result.append({"fieldname": column.get("fieldname"), "label": column.get("label"),
                           "fieldtype": column.get("fieldtype"), "options": column.get("options")})
        else:  # legacy "Label:Fieldtype/Options:Width"
            label, _sep, rest = str(column).partition(":")
            result.append({"fieldname": frappe.scrub(label), "label": label,
                           "fieldtype": rest.split("/")[0].split(":")[0] or "Data", "options": None})
    return result


@frappe.whitelist()
def list_financial_reports() -> dict:
    return success([{"key": key, "report": name} for key, name in REPORTS.items()])


@frappe.whitelist()
def run_financial_report(company: str, report: str, from_date: str | None = None, to_date: str | None = None,
                         report_date: str | None = None, periodicity: str = "Yearly", party: str | None = None,
                         warehouse: str | None = None, item_code: str | None = None) -> dict:
    """Runs one of `list_financial_reports` and returns its columns and rows.

    receivable / payable need ``report_date``; the others need ``from_date`` and ``to_date``.
    """
    require_company(company)
    try:
        name, filters = report_filters(report, company, from_date=from_date, to_date=to_date,
                                       report_date=report_date, periodicity=periodicity, party=party,
                                       warehouse=warehouse, item_code=item_code)
    except ValueError as error:
        frappe.throw(_(str(error)))
    from frappe.desk.query_report import run

    data = run(name, filters=filters, ignore_prepared_report=True)
    rows = [row for row in (data.get("result") or []) if isinstance(row, dict)]
    return success({
        "report": report, "report_name": name, "filters": filters,
        "columns": _columns(data.get("columns")),
        "rows": rows[:MAX_ROWS],
        "truncated": len(rows) > MAX_ROWS,
    })
