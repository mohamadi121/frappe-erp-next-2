"""Pure validation and snapshots for immutable hiring-order documents."""

import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from asoud_erp.services.digits import to_persian_digits

PERIODS = {"monthly", "yearly", "one_off"}
PERIOD_LABELS = {
    "monthly": "ماهانه",
    "yearly": "سالانه",
    "one_off": "یک‌باره",
}
MISSING_MESSAGE = "اطلاعات موجود نیست"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def default_template() -> dict:
    """The editable six-article default, keyed only by stable identifiers."""
    articles = [
        ("employee_details", "مشخصات پرسنل", "به موجب این حکم، [نام و نام خانوادگی پرسنل] با کد پرسنلی [کد پرسنلی] و مشخصات ثبت‌شده در پرونده منابع انسانی، مشمول مفاد این حکم می‌گردد."),
        ("employment_effective_date", "نوع استخدام و تاریخ اجرا", "نوع استخدام [نوع استخدام] بوده و تاریخ اجرای حکم از [تاریخ اجرای حکم] تعیین می‌شود."),
        ("organization_position", "واحد سازمانی و جایگاه شغلی", "نامبرده در [واحد سازمانی] و در جایگاه [عنوان شغلی]، در محل خدمت [محل خدمت] مشغول به کار خواهد بود."),
        ("duties", "شرح وظایف و شرایط خدمت", "شرح وظایف، مسئولیت‌ها و شرایط خدمت مطابق شرح شغل مصوب و ضوابط جاری شرکت تعیین می‌شود."),
        ("salary_benefits", "حقوق و مزایا", "حقوق و مزایای مرتبط با این حکم براساس اقلام متصل به سیستم حقوق و دستمزد و جدول زیر تعیین و نمایش داده می‌شود."),
        ("issuing_authority", "مرجع صدور و تأیید حکم", "این حکم توسط [نام نماینده قانونی] با سمت [سمت نماینده قانونی] از طرف [نام قانونی شرکت] صادر می‌شود."),
    ]
    return {
        "articles": [{"id": identifier, "title": title, "body": body} for identifier, title, body in articles],
        "payroll_rows": [{"id": "base_salary", "title": "حقوق پایه", "period": "monthly", "field_ref": "base"}],
    }


def validate_template(template: dict) -> dict:
    if not isinstance(template, dict):
        raise ValueError("ساختار قالب حکم معتبر نیست.")
    articles = template.get("articles")
    rows = template.get("payroll_rows")
    if not isinstance(articles, list) or len(articles) != 6:
        raise ValueError("قالب حکم باید شش ماده داشته باشد.")
    seen = set()
    for article in articles:
        identifier = article.get("id") if isinstance(article, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", identifier) or identifier in seen:
            raise ValueError("شناسه پایدار ماده معتبر نیست.")
        seen.add(identifier)
        if not str(article.get("title") or "").strip():
            raise ValueError("عنوان ماده را کامل کنید.")
    if not isinstance(rows, list) or not rows:
        raise ValueError("حداقل یک قلم حقوق و مزایا لازم است.")
    row_ids = set()
    for row in rows:
        identifier = row.get("id") if isinstance(row, dict) else None
        field_ref = row.get("field_ref") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", identifier) or identifier in row_ids:
            raise ValueError("شناسه پایدار ردیف حقوق معتبر نیست.")
        if not isinstance(field_ref, str) or not field_ref.strip():
            raise ValueError("شناسه پایدار فیلد حقوق را انتخاب کنید.")
        if row.get("period") not in PERIODS:
            raise ValueError("دوره پرداخت معتبر نیست.")
        row_ids.add(identifier)
    return deepcopy(template)


def normalize_search(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک")).strip().lower()


def _amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError("مبلغ حقوق معتبر نیست.") from error
    if not result.is_finite() or result < 0:
        raise ValueError("مبلغ حقوق معتبر نیست.")
    return result


def snapshot_payroll(rows: list[dict]) -> dict:
    """Copy source values, preserving absence and never mixing pay periods."""
    result, monthly_total = [], Decimal(0)
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("period") not in PERIODS:
            raise ValueError("ردیف حقوق معتبر نیست.")
        amount = _amount(raw.get("amount"))
        row = {key: raw.get(key) for key in ("id", "title", "period", "field_ref")}
        row["amount"] = float(amount) if amount is not None else None
        if amount is None:
            row.update({"state": "missing", "message": MISSING_MESSAGE})
        else:
            row["state"] = "available"
            if raw["period"] == "monthly":
                monthly_total += amount
        result.append(row)
    return {"rows": result, "monthly_total": float(monthly_total)}


def render_article_body(body: str, context: dict[str, Any]) -> str:
    """Renders article text substituting placeholders in [برچسب] and {{key}} forms."""
    if not body:
        return ""
    text = str(body)
    label_map = {
        "نام و نام خانوادگی پرسنل": context.get("employee_name") or "",
        "کد پرسنلی": context.get("employee_number") or "",
        "نوع استخدام": context.get("employment_type") or "",
        "تاریخ اجرای حکم": context.get("effective_date") or "",
        "واحد سازمانی": context.get("department") or "",
        "عنوان شغلی": context.get("designation") or "",
        "محل خدمت": context.get("location") or "",
        "نام نماینده قانونی": context.get("legal_representative") or context.get("company_name") or "",
        "سمت نماینده قانونی": context.get("legal_representative_role") or "مدیریت عامل",
        "نام قانونی شرکت": context.get("company_name") or context.get("company") or "",
    }
    for label, val in label_map.items():
        if val:
            text = text.replace(f"[{label}]", str(val))

    def _sub(match: re.Match) -> str:
        key = match.group(1).strip()
        if key in context:
            return str(context[key])
        parts = key.split(".", 1)
        if len(parts) == 2 and parts[0] in context and isinstance(context[parts[0]], dict):
            return str(context[parts[0]].get(parts[1], ""))
        return match.group(0)

    return re.sub(r"\{\{\s*([A-Za-z0-9_\.]+)\s*\}\}", _sub, text)


def format_hiring_order_print(order: dict, letterhead_html: str | None = None) -> str:
    """Produces self-contained A4 RTL HTML matching the ASOUD hiring order print specification."""
    status = order.get("status") or "draft"
    is_final = status == "final"
    raw_number = order.get("number") or ""
    number_display = to_persian_digits(raw_number) if (is_final and raw_number) else "—"
    raw_issued = order.get("issue_date") or ""
    issue_display = to_persian_digits(raw_issued) if raw_issued else "—"

    watermark = (
        ""
        if is_final
        else '<div class="watermark">پیش‌نویس ـ فاقد اعتبار نهایی</div>'
    )

    template = order.get("template_snapshot") or default_template()
    articles = template.get("articles") or []
    payroll_snapshot = order.get("payroll_snapshot") or {}
    payroll_rows = payroll_snapshot.get("rows") or []
    currency = order.get("currency") or "ریال"

    # Context for rendering placeholders
    context = {
        "employee_name": order.get("employee_name") or "",
        "employee_number": order.get("employee_number") or "",
        "employment_type": order.get("employment_type") or order.get("values", {}).get("employment") or "",
        "effective_date": order.get("effective_date") or "",
        "department": order.get("department") or order.get("values", {}).get("unit") or "",
        "designation": order.get("designation") or order.get("values", {}).get("position") or "",
        "location": order.get("location") or order.get("values", {}).get("location") or "",
        "company_name": order.get("company_name") or order.get("company") or "",
        "legal_representative": order.get("legal_representative") or order.get("company_name") or order.get("company") or "",
        "legal_representative_role": order.get("legal_representative_role") or "مدیریت عامل",
    }

    # Head / Letterhead
    company_title = escape(context["company_name"])
    if letterhead_html:
        head_content = f'<div class="letterhead">{letterhead_html}</div>'
    else:
        head_content = f"""<div class="doc-head">
          <div class="doc-logo">▤</div>
          <div class="company">
            <strong>{company_title}</strong>
            <small>احکام کارگزینی و منابع انسانی</small>
          </div>
          <div class="meta">
            شماره: {escape(number_display)}<br>
            تاریخ صدور: {escape(issue_display)}
          </div>
        </div>"""

    # Build articles HTML
    sections_html = []
    for idx, art in enumerate(articles, 1):
        art_id = art.get("id")
        art_title = escape(art.get("title") or "")
        rendered_body = escape(render_article_body(art.get("body") or "", context))
        section = f"<section><h3>ماده {to_persian_digits(idx)} ـ {art_title}</h3><p>{rendered_body}</p>"

        # If salary/benefits article, append payroll table
        if art_id == "salary_benefits" or idx == 5:
            table_rows = []
            for r_idx, prow in enumerate(payroll_rows, 1):
                p_title = escape(prow.get("title") or "")
                period_key = prow.get("period") or "monthly"
                period_label = escape(PERIOD_LABELS.get(period_key, period_key))
                amt = prow.get("amount")
                if amt is not None:
                    amt_str = to_persian_digits(f"{int(round(float(amt))):,}".replace(",", "٬"))
                else:
                    amt_str = escape(prow.get("message") or MISSING_MESSAGE)
                table_rows.append(
                    f"<tr><td>{to_persian_digits(r_idx)}</td><td>{p_title}</td>"
                    f"<td>{period_label}</td><td>{amt_str}</td></tr>"
                )

            monthly_total = payroll_snapshot.get("monthly_total")
            if monthly_total is not None and monthly_total > 0:
                monthly_str = to_persian_digits(f"{int(round(float(monthly_total))):,}".replace(",", "٬"))
            else:
                monthly_str = to_persian_digits("0")

            table_html = f"""<table class="payroll-table">
              <thead>
                <tr>
                  <th>ردیف</th>
                  <th>عنوان قلم</th>
                  <th>دوره</th>
                  <th>مبلغ ({escape(currency)})</th>
                </tr>
              </thead>
              <tbody>
                {''.join(table_rows)}
                <tr class="total-row">
                  <th colspan="3">جمع مبالغ ماهانه</th>
                  <th>{monthly_str} {escape(currency)}</th>
                </tr>
              </tbody>
            </table>"""
            section += table_html

        section += "</section>"
        sections_html.append(section)

    note_section = ""
    note = order.get("note") or order.get("values", {}).get("note")
    if note and str(note).strip():
        note_section = f"<section><h3>توضیحات تکمیلی</h3><p>{escape(str(note).strip())}</p></section>"

    html = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4 portrait; margin: 15mm 15mm 18mm; }}
body {{ font-family: Tahoma, 'Vazirmatn', Arial, sans-serif; font-size: 11pt; color: #243f60; direction: rtl; text-align: right; line-height: 2; margin: 0; padding: 0; }}
.paper {{ padding: 10px; }}
.doc-head {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #b9c7d6; padding-bottom: 12px; margin-bottom: 16px; }}
.doc-logo {{ font-size: 28px; color: #2479be; margin-left: 12px; }}
.company {{ flex: 1; }}
.company strong {{ font-size: 13pt; color: #1769aa; display: block; }}
.company small {{ font-size: 9pt; color: #74869b; }}
.meta {{ font-size: 10pt; color: #476078; text-align: left; }}
.doc-title {{ text-align: center; font-size: 16pt; color: #1769aa; margin: 12px 0 6px; }}
.watermark {{ text-align: center; color: #b05228; font-size: 11pt; font-weight: bold; background: #fff3e0; padding: 6px; border-radius: 6px; margin-bottom: 14px; border: 1px dashed #f2dfbc; }}
section {{ margin-bottom: 12px; break-inside: avoid; }}
h3 {{ font-size: 11pt; color: #243f60; margin: 8px 0 4px; font-weight: 700; }}
p {{ font-size: 10.5pt; color: #30445b; margin: 0 0 6px; text-align: justify; }}
.payroll-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9.5pt; }}
.payroll-table th, .payroll-table td {{ border: 1px solid #d3dce6; padding: 6px 8px; text-align: right; }}
.payroll-table th {{ background: #f2f5f9; color: #243f60; }}
.payroll-table .total-row th {{ background: #eaf3fd; color: #1769aa; font-weight: bold; }}
.signatures {{ display: flex; justify-content: space-between; margin-top: 28px; padding-top: 14px; font-size: 10pt; color: #476078; }}
footer {{ border-top: 1px solid #c6d1db; margin-top: 24px; padding-top: 8px; text-align: center; font-size: 9pt; color: #8795a5; }}
</style>
</head>
<body>
<article class="paper">
  {head_content}
  <h2 class="doc-title">حکم استخدام</h2>
  {watermark}
  {''.join(sections_html)}
  {note_section}
  <div class="signatures">
    <span>نام و امضای مقام صادرکننده<br>...........................</span>
    <span>مهر سازمان<br>...........................</span>
  </div>
  <footer>اطلاعات پابرگ شرکت ـ سامانه یکپارچه ابری آسود</footer>
</article>
</body>
</html>"""
    return html

