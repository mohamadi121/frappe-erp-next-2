"""Pure domain service for salary and benefits change orders: template validation,
comparison calculations, search normalization, and print layout formatting.
"""

import re
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
NOT_CALCULABLE_MESSAGE = "قابل محاسبه نیست"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def default_template() -> dict:
    """The editable six-article default for salary change orders, keyed by stable identifiers."""
    articles = [
        (
            "employee_details",
            "مشخصات پرسنل و مستند تغییر",
            "به موجب این حکم، وضعیت حقوق و مزایای [نام و نام خانوادگی پرسنل] با کد پرسنلی [کد پرسنلی] در [نام قانونی شرکت] مورد بازنگری قرار می‌گیرد.",
        ),
        (
            "subject_reason",
            "موضوع و علت تغییر",
            "با توجه به [علت تغییر حقوق] و با رعایت مقررات و مصوبات معتبر، تغییرات حقوق و مزایا برای [عنوان شغلی] در [واحد سازمانی] تعیین می‌شود.",
        ),
        (
            "effective_date",
            "تاریخ اجرا و دوره اثرگذاری",
            "تغییرات از تاریخ [تاریخ اجرای تغییر] لازم‌الاجرا است. تاریخ صدور حکم [تاریخ صدور حکم] بوده و اثرگذاری مالی بر اساس دوره مربوط اعمال می‌شود.",
        ),
        (
            "salary_comparison",
            "اقلام حقوق و مزایای قبلی و جدید",
            "اقلام مشمول تغییر در جدول زیر با مبلغ قبلی، مبلغ جدید و میزان تغییر نمایش داده می‌شوند. مبالغ نهایی تنها پس از تأیید رسمی معتبرند.",
        ),
        (
            "terms",
            "سایر شرایط و مقررات",
            "سایر مفاد همکاری که صراحتاً در این حکم تغییر نکرده‌اند، مطابق قرارداد و احکام معتبر قبلی به قوت خود باقی می‌مانند.",
        ),
        (
            "issuing_authority",
            "مرجع صدور و تصویب",
            "این حکم پس از طی تأییدهای لازم توسط [نام نماینده قانونی] با سمت [سمت نماینده قانونی] صادر و ثبت خواهد شد.",
        ),
    ]

    comparison_rows = [
        {
            "id": "base_salary",
            "title": "حقوق پایه",
            "period": "monthly",
            "old_ref": "payroll.base_salary",
            "new_ref": "document.new.base_salary",
        },
        {
            "id": "housing",
            "title": "حق مسکن",
            "period": "monthly",
            "old_ref": "payroll.housing",
            "new_ref": "document.new.housing",
        },
        {
            "id": "food",
            "title": "بن خواربار",
            "period": "monthly",
            "old_ref": "payroll.food",
            "new_ref": "document.new.food",
        },
    ]

    return {
        "articles": [
            {"id": identifier, "title": title, "body": body}
            for identifier, title, body in articles
        ],
        "comparison_rows": comparison_rows,
    }


def validate_template(template: dict) -> dict:
    """Validates structure and identifiers of a salary change order template."""
    if not isinstance(template, dict):
        raise ValueError("ساختار قالب حکم معتبر نیست.")

    articles = template.get("articles")
    rows = template.get("comparison_rows")

    if not isinstance(articles, list) or len(articles) != 6:
        raise ValueError("قالب حکم باید شش ماده داشته باشد.")

    seen_articles = set()
    for article in articles:
        if not isinstance(article, dict):
            raise ValueError("ماده قالب معتبر نیست.")
        identifier = article.get("id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", identifier)
            or identifier in seen_articles
        ):
            raise ValueError("شناسه پایدار ماده معتبر نیست.")
        seen_articles.add(identifier)
        if not str(article.get("title") or "").strip():
            raise ValueError("عنوان ماده را کامل کنید.")
        if len(str(article.get("body") or "")) > 10000 or len(str(article.get("title") or "")) > 500:
            raise ValueError("طول متن مادهٔ حکم فراتر از حد مجاز است.")

    if not isinstance(rows, list) or not rows:
        raise ValueError("حداقل یک قلم حقوق و مزایا در جدول مقایسه لازم است.")

    seen_rows = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ردیف جدول مقایسه معتبر نیست.")
        row_id = row.get("id")
        if (
            not isinstance(row_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", row_id)
            or row_id in seen_rows
        ):
            raise ValueError("شناسه پایدار ردیف مقایسه معتبر نیست.")
        seen_rows.add(row_id)

        old_ref = row.get("old_ref")
        new_ref = row.get("new_ref")
        if not isinstance(old_ref, str) or not old_ref.strip():
            raise ValueError("منبع فیلد مبلغ قبلی را مشخص کنید.")
        if not isinstance(new_ref, str) or not new_ref.strip():
            raise ValueError("منبع فیلد مبلغ جدید را مشخص کنید.")
        if row.get("period") not in PERIODS:
            raise ValueError("دوره پرداخت معتبر نیست.")

    return deepcopy(template)


def normalize_search(value: object) -> str:
    """Normalizes digits and Persian/Arabic letters for unified search."""
    return re.sub(
        r"\s+",
        " ",
        str(value or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک"),
    ).strip().lower()


def _amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError("مبلغ حقوق معتبر نیست.") from error
    if not result.is_finite() or result < 0:
        raise ValueError("مبلغ حقوق معتبر نیست.")
    return result


def calculate_comparison_row(
    row_id: str,
    title: str,
    period: str,
    old_ref: str,
    new_ref: str,
    previous_amount: object,
    new_amount: object,
) -> dict:
    """Calculates difference, percentage change, and explicit states for a single row."""
    if period not in PERIODS:
        raise ValueError(f"دوره پرداخت {period} معتبر نیست.")

    prev = _amount(previous_amount)
    nxt = _amount(new_amount)

    result = {
        "id": row_id,
        "title": title,
        "period": period,
        "period_label": PERIOD_LABELS.get(period, period),
        "old_ref": old_ref,
        "new_ref": new_ref,
        "previous_amount": int(prev) if prev is not None else None,
        "new_amount": int(nxt) if nxt is not None else None,
        "difference": None,
        "percent_change": None,
        "percent_label": None,
        "state": "available",
    }

    if prev is None or nxt is None:
        result["state"] = "missing"
        result["message"] = MISSING_MESSAGE
        return result

    diff = nxt - prev
    result["difference"] = int(diff)

    if prev == 0:
        result["percent_label"] = NOT_CALCULABLE_MESSAGE
    else:
        ratio = (diff / prev) * Decimal(100)
        rounded = ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        result["percent_change"] = float(rounded)
        sign = "+" if rounded > 0 else ""
        result["percent_label"] = f"{sign}{to_persian_digits(str(rounded))}٪"

    return result


def calculate_comparison_table(rows: list[dict]) -> dict:
    """Calculates full comparison table and computes totals strictly for same-period rows."""
    processed = []
    monthly_prev = Decimal(0)
    monthly_nxt = Decimal(0)
    has_monthly = False

    for r in rows:
        row_id = r.get("id") or ""
        title = r.get("title") or r.get("name") or ""
        period = r.get("period") or "monthly"
        old_ref = r.get("old_ref") or ""
        new_ref = r.get("new_ref") or ""
        prev = r.get("previous_amount") if "previous_amount" in r else r.get("old")
        nxt = r.get("new_amount") if "new_amount" in r else r.get("new")

        row_calc = calculate_comparison_row(
            row_id=row_id,
            title=title,
            period=period,
            old_ref=old_ref,
            new_ref=new_ref,
            previous_amount=prev,
            new_amount=nxt,
        )
        processed.append(row_calc)

        if period == "monthly" and row_calc["previous_amount"] is not None and row_calc["new_amount"] is not None:
            has_monthly = True
            monthly_prev += Decimal(row_calc["previous_amount"])
            monthly_nxt += Decimal(row_calc["new_amount"])

    monthly_diff = (monthly_nxt - monthly_prev) if has_monthly else Decimal(0)

    return {
        "rows": processed,
        "monthly_previous_total": int(monthly_prev) if has_monthly else None,
        "monthly_new_total": int(monthly_nxt) if has_monthly else None,
        "monthly_difference": int(monthly_diff) if has_monthly else None,
    }


def render_article_body(body: str, context: dict[str, Any]) -> str:
    """Renders article text substituting placeholders in [برچسب] and {{key}} forms."""
    if not body:
        return ""
    text = str(body)
    label_map = {
        "نام و نام خانوادگی پرسنل": context.get("employee_name") or "",
        "کد پرسنلی": context.get("employee_number") or "",
        "علت تغییر حقوق": context.get("reason_label") or context.get("reason") or "",
        "نوع تغییر حقوق": context.get("change_type") or "افزایش / تغییر حقوق",
        "عنوان شغلی": context.get("designation") or "",
        "واحد سازمانی": context.get("department") or "",
        "تاریخ اجرای تغییر": context.get("effective_date") or "",
        "تاریخ صدور حکم": context.get("issue_date") or "",
        "نام نماینده قانونی": context.get("legal_representative") or context.get("company_name") or "",
        "سمت نماینده قانونی": context.get("legal_representative_role") or "مدیریت عامل",
        "نام قانونی شرکت": context.get("company_name") or context.get("company") or "",
    }
    for label, val in label_map.items():
        text = text.replace(f"[{label}]", str(val))
    for key, val in context.items():
        if isinstance(val, (str, int, float)):
            text = text.replace(f"{{{{{key}}}}}", str(val))
    return text


def format_salary_change_order_print(order_data: dict, letterhead_html: str | None = None) -> str:
    """Generates standard A4 print HTML with draft watermark, letterhead, and repeated table header."""
    is_final = order_data.get("status") == "final"
    watermark_html = (
        '<div style="position:fixed;top:35%;left:10%;width:80%;text-align:center;'
        'transform:rotate(-30deg);font-size:38px;color:rgba(220,53,69,0.18);'
        'font-weight:bold;pointer-events:none;z-index:9999;border:3px dashed rgba(220,53,69,0.25);'
        'padding:20px;border-radius:12px;">'
        'پیش‌نویس ـ فاقد اعتبار نهایی'
        '</div>'
        if not is_final
        else ""
    )

    letterhead = letterhead_html or (
        f'<div style="text-align:center;border-bottom:2px solid #283e5a;padding-bottom:10px;margin-bottom:16px;">'
        f'<h2 style="margin:0;color:#1e3a8a;font-size:18px;">{escape(order_data.get("company_name") or "شرکت")}</h2>'
        f'<span style="font-size:12px;color:#64748b;">سامانه یکپارچه منابع انسانی ASOUD ERP</span>'
        f'</div>'
    )

    template = order_data.get("template_snapshot") or default_template()
    articles = template.get("articles") or []
    table = order_data.get("comparison_table") or {"rows": []}
    rows = table.get("rows") or []

    rows_html = ""
    for r in rows:
        prev_disp = (
            to_persian_digits(f"{r['previous_amount']:,}")
            if r.get("previous_amount") is not None
            else MISSING_MESSAGE
        )
        nxt_disp = (
            to_persian_digits(f"{r['new_amount']:,}")
            if r.get("new_amount") is not None
            else MISSING_MESSAGE
        )
        diff_disp = (
            to_persian_digits(f"{r['difference']:+,}")
            if r.get("difference") is not None
            else "—"
        )
        pct_disp = r.get("percent_label") or "—"

        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;'>{escape(r.get('title') or '')}</td>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;text-align:center;'>{escape(r.get('period_label') or '')}</td>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{prev_disp}</td>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{nxt_disp}</td>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{diff_disp}</td>"
            f"<td style='padding:6px 8px;border:1px solid #cbd5e1;text-align:center;'>{pct_disp}</td>"
            f"</tr>"
        )

    monthly_prev = table.get("monthly_previous_total")
    monthly_nxt = table.get("monthly_new_total")
    monthly_diff = table.get("monthly_difference")

    total_row_html = ""
    if monthly_prev is not None and monthly_nxt is not None:
        total_row_html = (
            f"<tr style='background:#f8fafc;font-weight:bold;'>"
            f"<td colspan='2' style='padding:8px;border:1px solid #cbd5e1;'>جمع ماهانه اقلام</td>"
            f"<td style='padding:8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{to_persian_digits(f'{monthly_prev:,}')}</td>"
            f"<td style='padding:8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{to_persian_digits(f'{monthly_nxt:,}')}</td>"
            f"<td style='padding:8px;border:1px solid #cbd5e1;text-align:left;direction:ltr;'>{to_persian_digits(f'{monthly_diff:+,}')}</td>"
            f"<td style='padding:8px;border:1px solid #cbd5e1;text-align:center;'>—</td>"
            f"</tr>"
        )

    table_html = (
        f'<div style="margin:12px 0;">'
        f'<h4 style="margin:4px 0 8px 0;font-size:13px;color:#1e293b;">جدول مقایسه حقوق و مزایا (ارقام به ریال)</h4>'
        f'<table style="width:100%;border-collapse:collapse;font-size:11px;">'
        f'<thead style="display:table-header-group;background:#f1f5f9;">'
        f'<tr>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:right;">عنوان قلم</th>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:center;">دوره</th>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:center;">مبلغ قبلی</th>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:center;">مبلغ جدید</th>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:center;">میزان تغییر</th>'
        f'<th style="padding:6px 8px;border:1px solid #cbd5e1;text-align:center;">درصد</th>'
        f'</tr>'
        f'</thead>'
        f'<tbody>{rows_html}{total_row_html}</tbody>'
        f'</table>'
        f'</div>'
    )

    articles_html = ""
    for i, art in enumerate(articles):
        art_id = art.get("id")
        title = art.get("title") or ""
        body = render_article_body(art.get("body") or "", order_data)
        articles_html += (
            f'<div style="margin-bottom:10px;">'
            f'<h4 style="margin:0 0 4px 0;font-size:12px;color:#1e3a8a;">'
            f'ماده {to_persian_digits(str(i + 1))} ـ {escape(title)}'
            f'</h4>'
            f'<p style="margin:0;font-size:11px;line-height:1.7;color:#334155;text-align:justify;">{escape(body)}</p>'
            f'</div>'
        )
        if art_id == "salary_comparison" or i == 3:
            articles_html += table_html

    doc_number = (
        to_persian_digits(order_data.get("number") or "")
        if is_final
        else "پیش‌نویس (فاقد شماره رسمی)"
    )

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="fa">
<head>
<meta charset="utf-8">
<title>حکم افزایش یا تغییر حقوق و مزایا</title>
<style>
@page {{
  size: A4 portrait;
  margin: 15mm 12mm 15mm 12mm;
}}
body {{
  font-family: Sahel, Vazirmatn, Tahoma, sans-serif;
  color: #0f172a;
  background: #ffffff;
  margin: 0;
  padding: 0;
  direction: rtl;
}}
.paper {{
  position: relative;
  box-sizing: border-box;
}}
thead {{
  display: table-header-group;
}}
tr {{
  page-break-inside: avoid;
}}
</style>
</head>
<body>
<div class="paper">
{watermark_html}
{letterhead}
<div style="display:flex;justify-content:space-between;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-bottom:12px;font-size:11px;">
  <div>
    <strong>شماره حکم:</strong> <span>{doc_number}</span><br>
    <strong>تاریخ صدور:</strong> <span>{to_persian_digits(order_data.get("issue_date") or "—")}</span>
  </div>
  <div style="text-align:center;">
    <h3 style="margin:0;font-size:15px;color:#1e3a8a;">حکم افزایش یا تغییر حقوق و مزایا</h3>
  </div>
  <div style="text-align:left;">
    <strong>کد پرسنلی:</strong> <span>{to_persian_digits(order_data.get("employee_number") or "—")}</span><br>
    <strong>تاریخ اجرا:</strong> <span>{to_persian_digits(order_data.get("effective_date") or "—")}</span>
  </div>
</div>

<div style="background:#f8fafc;padding:8px 12px;border-radius:6px;margin-bottom:14px;font-size:11px;display:flex;justify-content:space-between;">
  <div><strong>نام و نام خانوادگی:</strong> {escape(order_data.get("employee_name") or "")}</div>
  <div><strong>واحد سازمانی:</strong> {escape(order_data.get("department") or "—")}</div>
  <div><strong>عنوان شغلی:</strong> {escape(order_data.get("designation") or "—")}</div>
</div>

{articles_html}

<div style="margin-top:24px;display:flex;justify-content:space-between;page-break-inside:avoid;padding:0 30px;font-size:11px;">
  <div style="text-align:center;">
    <strong>مقام تأییدکننده / صادرکننده</strong><br><br><br>
    <span>امضا و مهر</span>
  </div>
  <div style="text-align:center;">
    <strong>ملاحظه و اطلاع پرسنل</strong><br><br><br>
    <span>امضا و تاریخ</span>
  </div>
</div>
</div>
</body>
</html>"""
