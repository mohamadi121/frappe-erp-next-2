"""Pure validation and snapshots for immutable hiring-order documents."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re


PERIODS = {"monthly", "yearly", "one_off"}
MISSING_MESSAGE = "اطلاعات موجود نیست"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def default_template() -> dict:
    """The editable six-article default, keyed only by stable identifiers."""
    articles = [
        ("employee_details", "مشخصات پرسنل"),
        ("employment_effective_date", "نوع استخدام و تاریخ اجرا"),
        ("organization_position", "واحد سازمانی و جایگاه شغلی"),
        ("duties", "شرح وظایف و شرایط خدمت"),
        ("salary_benefits", "حقوق و مزایا"),
        ("issuing_authority", "مرجع صدور و تأیید حکم"),
    ]
    return {
        "articles": [{"id": identifier, "title": title, "body": ""} for identifier, title in articles],
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
