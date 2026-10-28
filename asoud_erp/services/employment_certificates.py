"""Pure template validation and immutable snapshots for employment certificates."""

import re
from copy import deepcopy
from html import escape

MISSING_MESSAGE = "اطلاعات موجود نیست"
PERIODS = {"monthly", "yearly", "one_off"}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TOKEN = re.compile(r"{{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)}}")

DEFAULT_TEMPLATE = {
    "clauses": [
        {
            "id": "recipient",
            "title": "مشخصات مخاطب",
            "body": "به: {{certificate.addressee_name}}\nموضوع: گواهی اشتغال به کار",
            "enabled": True,
        },
        {
            "id": "main_body",
            "title": "متن اصلی گواهی",
            "body": "بدین‌وسیله گواهی می‌شود که خانم/آقای {{employee.employee_name}} با شماره پرسنلی {{employee.employee_number}} و کد ملی {{employee.national_id}} از تاریخ {{employee.date_of_joining}} در شرکت {{company.company_name}} با سمت {{employee.designation}} مشغول به خدمت می‌باشند.",
            "enabled": True,
        },
        {
            "id": "purpose",
            "title": "هدف و اعتبار",
            "body": "این گواهی بنا به درخواست نامبرده جهت {{certificate.purpose}} صادر گردیده و فاقد هرگونه ارزش و تعهد دیگری است.",
            "enabled": True,
        },
        {
            "id": "salary",
            "title": "حقوق و مزایا",
            "body": "میزان ناخالص دریافتی ماهانه نامبرده به شرح جدول زیر است:",
            "enabled": True,
        },
    ],
    "salary_enabled": False,
    "salary_rows": [
        {"id": "base", "title": "حقوق پایه", "field_ref": "payroll.base", "period": "monthly"},
    ],
}


def build_print_html(
    rendered_html: str,
    letterhead_html: str | None = None,
    number: str = "—",
    issue_date: str = "—",
    is_final: bool = False,
) -> str:
    draft_banner = (
        ""
        if is_final
        else '<div style="text-align:center; color:#9eacbc; font-weight:700; font-size:12px; margin-bottom:12px;">پیش‌نویس ـ فاقد اعتبار نهایی</div>'
    )
    letterhead_section = (
        f'<div style="margin-bottom:12px;">{letterhead_html}</div>'
        if letterhead_html
        else '<div style="font-weight:700; font-size:12px; color:#243f60; margin-bottom:8px;">سربرگ سازمان</div>'
    )

    return (
        f'<article dir="rtl" style="font-family: Tahoma, \'Noto Sans Arabic\', sans-serif; padding: 24px; line-height: 2; color: #202f42;">'
        f'{letterhead_section}'
        f'<hr style="border: 0; border-top: 1px solid #b8c6d3; margin: 10px 0 16px 0;">'
        f'<h2 style="text-align: center; font-size: 17px; color: #243f60; margin: 10px 0;">گواهی اشتغال به کار</h2>'
        f'{draft_banner}'
        f'<div style="display: flex; justify-content: space-between; font-size: 11px; color: #62768c; margin-bottom: 16px;">'
        f'<span>شماره: {escape(str(number))}</span>'
        f'<span>تاریخ: {escape(str(issue_date))}</span>'
        f'</div>'
        f'{rendered_html}'
        f'<div style="display: flex; justify-content: space-between; margin-top: 60px; font-size: 11px; padding: 0 20px;">'
        f'<span>نام و امضای مقام مجاز</span>'
        f'<span>مهر شرکت</span>'
        f'</div>'
        f'<footer style="margin-top: 50px; text-align: center; font-size: 10px; color: #748398; border-top: 1px solid #b8c6d3; padding-top: 10px;">'
        f'پابرگ و نشانی شرکت از تنظیمات سازمان'
        f'</footer>'
        f'</article>'
    )



def normalize_search(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک")).strip().lower()


def _token_value(token: str, values: dict) -> str:
    current = values
    for part in token.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return "" if current is None else escape(str(current))


def validate_template(template: dict) -> dict:
    if not isinstance(template, dict) or not isinstance(template.get("clauses"), list):
        raise ValueError("ساختار قالب گواهی معتبر نیست.")
    enabled = template.get("salary_enabled")
    if not isinstance(enabled, bool) or not isinstance(template.get("salary_rows"), list):
        raise ValueError("تنظیمات حقوق گواهی معتبر نیست.")
    clause_ids = set()
    clauses = []
    for clause in template["clauses"]:
        if not isinstance(clause, dict) or not isinstance(clause.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", clause["id"]) or clause["id"] in clause_ids:
            raise ValueError("شناسه پایدار بند معتبر نیست.")
        body = clause.get("body")
        if not isinstance(clause.get("title"), str) or not clause["title"].strip() or not isinstance(body, str):
            raise ValueError("عنوان و متن بند را کامل کنید.")
        for raw in re.findall(r"{{(.*?)}}", body):
            if not _TOKEN.fullmatch("{{" + raw + "}}"):
                raise ValueError("شناسه فیلد در متن بند معتبر نیست.")
        clause_ids.add(clause["id"])
        clauses.append({"id": clause["id"], "title": clause["title"].strip(), "body": body, "enabled": clause.get("enabled") is not False})
    rows = []
    row_ids = set()
    for row in template["salary_rows"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in row_ids or row.get("period") not in PERIODS or not isinstance(row.get("field_ref"), str) or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", row["field_ref"]):
            raise ValueError("شناسه فیلد حقوق معتبر نیست.")
        if not isinstance(row.get("title"), str) or not row["title"].strip():
            raise ValueError("عنوان قلم حقوق را کامل کنید.")
        row_ids.add(row["id"])
        rows.append({key: row[key] for key in ("id", "title", "field_ref", "period")})
    if enabled and not rows:
        raise ValueError("برای بخش حقوق حداقل یک قلم لازم است.")
    return {"clauses": clauses, "salary_enabled": enabled, "salary_rows": rows}


def render_snapshot(template: dict, values: dict, salary_rows: list[dict] | None = None) -> dict:
    """Render only the published template; salary is unreachable when disabled."""
    template = validate_template(template)
    values = deepcopy(values) if isinstance(values, dict) else {}
    if not template["salary_enabled"]:
        values.pop("payroll", None)
    blocks = []
    for clause in template["clauses"]:
        if clause["enabled"]:
            body = _TOKEN.sub(lambda match: _token_value(match.group(1), values), escape(clause["body"]))
            blocks.append(f"<section><h3>{escape(clause['title'])}</h3><p>{body}</p></section>")
    snapshot_rows = []
    if template["salary_enabled"]:
        source = {row.get("id"): row for row in salary_rows or [] if isinstance(row, dict)}
        for definition in template["salary_rows"]:
            source_row = source.get(definition["id"], {})
            amount = source_row.get("amount")
            snapshot = {**definition, "amount": amount}
            if amount is None:
                snapshot.update({"state": "missing", "message": MISSING_MESSAGE})
            else:
                snapshot["state"] = "available"
            snapshot_rows.append(snapshot)
        cells = "".join(f"<tr><td>{escape(row['title'])}</td><td>{escape(str(row.get('amount'))) if row.get('amount') is not None else MISSING_MESSAGE}</td></tr>" for row in snapshot_rows)
        blocks.append("<table><tbody>" + cells + "</tbody></table>")
    return {"template": deepcopy(template), "values": deepcopy(values), "salary_rows": snapshot_rows, "html": "<article dir=\"rtl\">" + "".join(blocks) + "</article>"}
