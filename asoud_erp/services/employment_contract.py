"""Employment contracts domain service: template validation, article rendering,
salary item calculation, search normalization, and print formatting.

Pure service with no direct database dependency; safe to run under pytest.
"""

from __future__ import annotations

import html
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from asoud_erp.services.digits import to_ascii_digits, to_persian_digits

MISSING_PAYROLL_TEXT = "اطلاعات موجود نیست"
CURRENCY_LABEL = "ریال"


def mask_contract_salary(snapshot: dict) -> dict:
    """Remove persisted payroll from a response without changing its source."""
    return dict(snapshot, salary_values={}, salary_table=[], total_monthly=0,
                formatted_total_monthly="")


DEFAULT_CLAUSES = [
    {
        "id": "clause_1",
        "title": "طرفین قرارداد",
        "body": "این قرارداد میان {{company.company_name}} به نمایندگی {{company.legal_representative}} و {{personnel.employee_name}} فرزند {{personnel.father_name}} با شماره ملی {{personnel.national_id}} تنظیم می‌شود.",
        "order": 1,
    },
    {
        "id": "clause_2",
        "title": "موضوع و محل کار",
        "body": "موضوع همکاری، تصدی شغل {{personnel.job_title}} در {{personnel.department}} بوده و محل انجام کار {{contract.work_location}} تعیین می‌گردد.",
        "order": 2,
    },
    {
        "id": "clause_3",
        "title": "مدت همکاری",
        "body": "تاریخ شروع همکاری {{contract.start_date}} و تاریخ پایان در قراردادهای مدت‌معین {{contract.end_date}} است.",
        "order": 3,
    },
    {
        "id": "clause_4",
        "title": "حقوق و مزایا",
        "body": "حقوق و مزایای طرف قرارداد مطابق اقلام مندرج در جدول زیر و بر اساس ضوابط قانونی و کارکرد ماهانه تعیین و پرداخت خواهد شد.",
        "order": 4,
    },
    {
        "id": "clause_5",
        "title": "تعهدات طرفین",
        "body": "شرایط محرمانگی، حفظ اسرار تجاری و انضباط سازمانی مطابق آیین‌نامه‌های داخلی شرکت و مقررات قانون کار لازم‌الاجرا خواهد بود.",
        "order": 5,
    },
]

DEFAULT_SALARY_ROWS = [
    {"id": "row_base", "name": "حقوق پایه", "period": "monthly", "fieldRef": "payroll.base_salary"},
    {"id": "row_housing", "name": "حق مسکن", "period": "monthly", "fieldRef": "payroll.housing"},
    {"id": "row_food", "name": "بن خواربار", "period": "monthly", "fieldRef": "payroll.food"},
]

PAYROLL_CATALOG_FIELDS = [
    {"id": "payroll.base_salary", "label": "حقوق پایه", "type": "Money", "group": "حقوق"},
    {"id": "payroll.housing", "label": "حق مسکن", "type": "Money", "group": "مزایا"},
    {"id": "payroll.food", "label": "بن خواربار", "type": "Money", "group": "مزایا"},
    {"id": "payroll.child", "label": "حق اولاد", "type": "Money", "group": "مزایا"},
    {"id": "payroll.seniority", "label": "پایه سنوات", "type": "Money", "group": "حقوق"},
    {"id": "payroll.attraction", "label": "حق جذب", "type": "Money", "group": "مزایا"},
    {"id": "payroll.responsibility", "label": "حق مسئولیت", "type": "Money", "group": "مزایا"},
    {"id": "payroll.position", "label": "فوق‌العاده شغل", "type": "Money", "group": "مزایا"},
    {"id": "payroll.transport", "label": "ایاب و ذهاب", "type": "Money", "group": "مزایا"},
    {"id": "payroll.mission", "label": "حق مأموریت", "type": "Money", "group": "مزایا"},
    {"id": "payroll.overtime", "label": "اضافه‌کاری", "type": "Money", "group": "کارکرد"},
    {"id": "payroll.shift", "label": "فوق‌العاده نوبت‌کاری", "type": "Money", "group": "کارکرد"},
    {"id": "payroll.night", "label": "فوق‌العاده شب‌کاری", "type": "Money", "group": "کارکرد"},
    {"id": "payroll.bonus", "label": "پاداش", "type": "Money", "group": "مزایا"},
    {"id": "payroll.other_benefit", "label": "سایر مزایا", "type": "Money", "group": "مزایا"},
]

_PLACEHOLDER_REGEX = re.compile(r"\{\{([a-zA-Z0-9_\.]+)\}\}")
_ARABIC_TO_PERSIAN_TRANS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})


def normalize_search_term(term: Any) -> str:
    """Normalizes Persian/Arabic characters and converts Persian/Arabic numerals to ASCII."""
    if not term or not isinstance(term, str):
        return ""
    text = term.strip().translate(_ARABIC_TO_PERSIAN_TRANS)
    text = to_ascii_digits(text)
    return text.lower()


def validate_contract_template(clauses: list[dict], salary_rows: list[dict], title: str = "قالب قرارداد کار",
                               workflow: str | None = None) -> dict[str, Any]:
    """Validates and normalizes clauses and salary rows.

    - Title is required.
    - At least one clause is required.
    - Each clause must have a non-empty title and body.
    - Clauses are sorted by order; number is determined by order.
    - Salary rows must have stable id, name, period ('monthly' | 'yearly'), and fieldRef.
    """
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("عنوان قالب قرارداد الزامی است.")

    if not isinstance(clauses, list) or not clauses:
        raise ValueError("قالب قرارداد باید حداقل یک ماده داشته باشد.")

    normalized_clauses = []
    seen_clause_ids = set()
    for index, raw in enumerate(clauses):
        if not isinstance(raw, dict):
            raise ValueError("ساختار مواد قرارداد معتبر نیست.")
        c_id = str(raw.get("id") or f"clause_{index + 1}").strip()
        c_title = str(raw.get("title") or "").strip()
        c_body = str(raw.get("body") or "").strip()
        if not c_title or not c_body:
            raise ValueError("عنوان و متن تمام مواد قرارداد باید تکمیل شده باشد.")
        if len(c_body) > 10000 or len(c_title) > 500:
            raise ValueError("طول متن مادهٔ قرارداد فراتر از حد مجاز است.")
        order = int(raw.get("order") or (index + 1))
        seen_clause_ids.add(c_id)
        normalized_clauses.append({
            "id": c_id,
            "title": c_title,
            "body": c_body,
            "order": order,
        })

    normalized_clauses.sort(key=lambda c: c["order"])
    # Re-sequence orders cleanly 1..N
    for i, c in enumerate(normalized_clauses):
        c["order"] = i + 1

    normalized_rows = []
    seen_row_ids = set()
    if isinstance(salary_rows, list):
        for index, raw in enumerate(salary_rows):
            if not isinstance(raw, dict):
                raise ValueError("ساختار ردیف حقوق و مزایا معتبر نیست.")
            r_id = str(raw.get("id") or f"row_{index + 1}").strip()
            r_name = str(raw.get("name") or "").strip()
            period = str(raw.get("period") or "monthly").strip().lower()
            field_ref = str(raw.get("fieldRef") or "").strip()
            if not r_name:
                raise ValueError("نام ردیف جدول حقوق و مزایا الزامی است.")
            if period not in {"monthly", "yearly"}:
                raise ValueError("دوره پرداخت اقلام حقوقی فقط می‌تواند «ماهانه» (monthly) یا «سالانه» (yearly) باشد.")
            seen_row_ids.add(r_id)
            normalized_rows.append({
                "id": r_id,
                "name": r_name,
                "period": period,
                "fieldRef": field_ref,
            })

    res = {
        "title": clean_title,
        "clauses": normalized_clauses,
        "salary_rows": normalized_rows,
        "computed_fields": [
            {"id": "total_monthly", "name": "مجموع ناخالص ماهانه", "period": "monthly"}
        ],
    }
    if workflow is not None:
        res["workflow"] = str(workflow or "")
    return res


def render_contract_articles(clauses: list[dict], context: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Renders placeholders {{group.field}} inside clause bodies.

    Returns clauses with titles formatted by order («ماده ۱: طرفین قرارداد») and resolved bodies.
    """
    rendered = []
    for clause in clauses:
        order = clause.get("order", 1)
        raw_title = clause.get("title", "")
        # Remove any pre-existing "ماده X:" prefix so we don't duplicate it
        clean_title = re.sub(r"^ماده\s+[\d۰-۹]+\s*:\s*", "", raw_title).strip()
        formatted_title = f"ماده {to_persian_digits(order)}: {clean_title}"

        body = clause.get("body", "")

        def _replacer(match: re.Match) -> str:
            path = match.group(1).split(".", 1)
            if len(path) == 2:
                group, key = path
                val = context.get(group, {}).get(key)
                if val is not None and not isinstance(val, (list, dict)):
                    return str(val)
            return ""

        resolved_body = _PLACEHOLDER_REGEX.sub(_replacer, body)
        rendered.append({
            "id": clause.get("id"),
            "order": order,
            "title": formatted_title,
            "raw_title": clean_title,
            "body": resolved_body,
        })
    return rendered


def calculate_salary_items(salary_rows: list[dict], values_by_field_ref: dict[str, Any]) -> dict[str, Any]:
    """Calculates each salary row amount, formats values with Persian digits, and computes monthly total.

    Hard rule: Missing payroll value => explicit Persian "اطلاعات موجود نیست" state, never silently 0.
    Never sum monthly with yearly without a defined conversion.
    """
    items = []
    total_monthly = Decimal("0")

    for row in salary_rows:
        ref = row.get("fieldRef", "")
        raw_val = values_by_field_ref.get(ref) if ref else None

        has_value = False
        num_amount = None
        formatted_amount = MISSING_PAYROLL_TEXT

        if raw_val not in (None, "", "null"):
            try:
                dec = Decimal(str(to_ascii_digits(str(raw_val))).replace(",", "")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                num_amount = int(dec)
                has_value = True
                formatted_amount = f"{to_persian_digits(f'{num_amount:,}'.replace(',', '٬'))} {CURRENCY_LABEL}"
                if row.get("period") == "monthly":
                    total_monthly += dec
            except Exception:
                has_value = False
                num_amount = None
                formatted_amount = MISSING_PAYROLL_TEXT

        items.append({
            "id": row.get("id"),
            "name": row.get("name"),
            "period": "ماهانه" if row.get("period") == "monthly" else "سالانه",
            "period_raw": row.get("period"),
            "fieldRef": ref,
            "has_value": has_value,
            "amount": num_amount,
            "formatted_amount": formatted_amount,
        })

    int_total_monthly = int(total_monthly)
    formatted_total_monthly = f"{to_persian_digits(f'{int_total_monthly:,}'.replace(',', '٬'))} {CURRENCY_LABEL}"

    return {
        "items": items,
        "total_monthly": int_total_monthly,
        "formatted_total_monthly": formatted_total_monthly,
    }


def get_field_catalog(has_payroll_permission: bool = True) -> dict[str, Any]:
    """Returns catalog of insertable fields grouped by category."""
    categories = [
        {
            "key": "personnel",
            "label": "اطلاعات پرسنل",
            "authorized": True,
            "fields": [
                {"id": "personnel.employee_name", "label": "نام و نام خانوادگی", "type": "Text", "source": "Employee.employee_name"},
                {"id": "personnel.first_name", "label": "نام", "type": "Text", "source": "Employee.first_name"},
                {"id": "personnel.last_name", "label": "نام خانوادگی", "type": "Text", "source": "Employee.last_name"},
                {"id": "personnel.father_name", "label": "نام پدر", "type": "Text", "source": "Employee.father_name"},
                {"id": "personnel.national_id", "label": "کد ملی", "type": "Text", "source": "Employee.national_id"},
                {"id": "personnel.employee_number", "label": "کد پرسنلی", "type": "Text", "source": "Employee.name"},
                {"id": "personnel.department", "label": "واحد سازمانی", "type": "Text", "source": "Employee.department"},
                {"id": "personnel.job_title", "label": "عنوان شغلی", "type": "Text", "source": "Employee.designation"},
                {"id": "personnel.date_of_joining", "label": "تاریخ شروع همکاری", "type": "Date", "source": "Employee.date_of_joining"},
                {"id": "personnel.mobile", "label": "تلفن همراه", "type": "Text", "source": "Employee.cell_number"},
                {"id": "personnel.address", "label": "نشانی سکونت", "type": "Text", "source": "Employee.current_address"},
                {"id": "personnel.postal_code", "label": "کد پستی", "type": "Text", "source": "Employee.current_postal_code"},
                {"id": "personnel.education_degree", "label": "مدرک تحصیلی", "type": "Text", "source": "Employee.education_degree"},
                {"id": "personnel.insurance_number", "label": "شماره بیمه", "type": "Text", "source": "Employee.insurance_number"},
                {"id": "personnel.iban", "label": "شماره شبا", "type": "Text", "source": "Employee.iban"},
            ],
        },
        {
            "key": "company",
            "label": "اطلاعات شرکت",
            "authorized": True,
            "fields": [
                {"id": "company.company_name", "label": "نام قانونی شرکت", "type": "Text", "source": "Company.company_name"},
                {"id": "company.national_id", "label": "شناسه ملی شرکت", "type": "Text", "source": "Company.tax_id"},
                {"id": "company.legal_representative", "label": "نام نماینده قانونی", "type": "Text", "source": "Company.asoud_legal_representative"},
                {"id": "company.legal_representative_title", "label": "سمت نماینده قانونی", "type": "Text", "source": "Company.asoud_legal_representative_title"},
                {"id": "company.registration_number", "label": "شماره ثبت", "type": "Text", "source": "Company.registration_details"},
                {"id": "company.address", "label": "نشانی دفتر مرکزی", "type": "Text", "source": "Company.address"},
                {"id": "company.phone", "label": "تلفن شرکت", "type": "Text", "source": "Company.phone_no"},
                {"id": "company.email", "label": "ایمیل شرکت", "type": "Text", "source": "Company.email"},
                {"id": "company.ceo_name", "label": "نام مدیرعامل", "type": "Text", "source": "Company.asoud_ceo_name"},
            ],
        },
        {
            "key": "contract",
            "label": "مشخصات قرارداد",
            "authorized": True,
            "fields": [
                {"id": "contract.contract_type", "label": "نوع قرارداد", "type": "Select"},
                {"id": "contract.start_date", "label": "تاریخ شروع", "type": "Date"},
                {"id": "contract.end_date", "label": "تاریخ پایان", "type": "Date"},
                {"id": "contract.work_location", "label": "محل انجام کار", "type": "Text"},
                {"id": "contract.creation_date", "label": "تاریخ تنظیم قرارداد", "type": "Date"},
            ],
        },
        {
            "key": "payroll",
            "label": "اقلام حقوق و مزایا",
            "authorized": has_payroll_permission,
            "warning": None if has_payroll_permission else "مشاهده و درج اقلام حقوقی نیازمند مجوز دسترسی به حقوق و دستمزد است.",
            "fields": [
                {**f, "disabled": not has_payroll_permission} for f in PAYROLL_CATALOG_FIELDS
            ],
        },
    ]
    return {"categories": categories}


def generate_contract_print_data(
    *,
    is_draft: bool,
    contract_number: str | None,
    issue_date: str,
    employee_name: str,
    rendered_clauses: list[dict],
    salary_table: list[dict],
    total_monthly_formatted: str,
    letterhead_html: str | None = None,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Builds the complete print payload for an employment contract.

    A4 RTL layout with shared header/footer, draft banner if draft, and formal signatures.
    """
    display_number = contract_number if (not is_draft and contract_number) else "شماره پس از صدور"
    draft_banner = "«پیش‌نویس ـ فاقد اعتبار نهایی»" if is_draft else None

    # Construct clean A4 RTL HTML
    header_content = letterhead_html or f"<div style='text-align:center;'><h2>{html.escape(company_name or '')}</h2></div>"
    banner_html = f"<div class='draft-banner'>{draft_banner}</div>" if draft_banner else ""

    clauses_html = "".join(
        f"<div class='clause'><h3>{html.escape(c.get('title', ''))}</h3><p>{html.escape(c.get('body', ''))}</p></div>"
        for c in rendered_clauses
    )

    rows_html = "".join(
        f"<tr><td>{html.escape(r.get('name', ''))}</td><td>{html.escape(r.get('period', ''))}</td><td>{html.escape(r.get('formatted_amount', ''))}</td></tr>"
        for r in salary_table
    )

    salary_section_html = f"""
    <div class='salary-section'>
        <h3>جدول حقوق و مزایا</h3>
        <table class='salary-table'>
            <thead>
                <tr><th>عنوان</th><th>دوره پرداخت</th><th>مبلغ</th></tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
            <tfoot>
                <tr><th colspan='2'>مجموع ناخالص ماهانه</th><th>{html.escape(total_monthly_formatted)}</th></tr>
            </tfoot>
        </table>
    </div>
    """

    full_html = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="utf-8">
    <title>قرارداد کار - {html.escape(employee_name)}</title>
    <style>
        @page {{ size: A4; margin: 20mm 15mm; }}
        body {{
            font-family: Vazirmatn, "IRANSans", "Noto Naskh Arabic", Tahoma, sans-serif;
            direction: rtl;
            text-align: right;
            font-size: 11pt;
            line-height: 1.8;
            color: #111;
            margin: 0;
            padding: 0;
        }}
        .header {{ margin-bottom: 20px; }}
        .draft-banner {{
            text-align: center;
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeeba;
            padding: 8px;
            font-weight: bold;
            font-size: 13pt;
            margin-bottom: 15px;
            border-radius: 4px;
        }}
        .meta-bar {{
            display: flex;
            justify-content: space-between;
            border-bottom: 2px solid #ddd;
            padding-bottom: 8px;
            margin-bottom: 20px;
            font-size: 10pt;
        }}
        .clause {{ margin-bottom: 14px; text-align: justify; }}
        .clause h3 {{ font-size: 11pt; margin: 0 0 4px 0; color: #1e3a8a; }}
        .clause p {{ margin: 0; }}
        .salary-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        .salary-table th, .salary-table td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
        .salary-table th {{ background: #f8fafc; }}
        .signatures {{
            display: flex;
            justify-content: space-between;
            margin-top: 40px;
            padding-top: 20px;
            page-break-inside: avoid;
        }}
        .sig-block {{ width: 45%; text-align: center; border-top: 1px dashed #aaa; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="header">{header_content}</div>
    {banner_html}
    <div class="meta-bar">
        <span><strong>شماره قرارداد:</strong> <bdi>{html.escape(display_number)}</bdi></span>
        <span><strong>تاریخ تنظیم:</strong> {to_persian_digits(issue_date)}</span>
    </div>
    <div class="articles-container">
        {clauses_html}
    </div>
    {salary_section_html}
    <div class="signatures">
        <div class="sig-block">امضا و اثر انگشت کارمند / پرسنل</div>
        <div class="sig-block">مهر و امضای نماینده کارفرما / شرکت</div>
    </div>
</body>
</html>"""

    return {
        "is_draft": is_draft,
        "draft_banner": draft_banner,
        "contract_number": display_number,
        "issue_date_jalali": to_persian_digits(issue_date),
        "employee_name": employee_name,
        "rendered_clauses": rendered_clauses,
        "salary_table": salary_table,
        "total_monthly_formatted": total_monthly_formatted,
        "letterhead_html": letterhead_html,
        "html": full_html,
    }
