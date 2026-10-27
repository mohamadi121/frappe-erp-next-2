"""Pure template validation and immutable snapshots for personnel introduction letters."""

from __future__ import annotations

import re
from copy import deepcopy
from html import escape

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TOKEN = re.compile(r"{{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)}}")

DEFAULT_TEMPLATE = {
    "clauses": [
        {
            "id": "recipient_subject",
            "title": "مخاطب و موضوع معرفی‌نامه",
            "body": "مدیریت محترم {{letter.recipient}}\nموضوع: معرفی {{employee.employee_name}}",
            "enabled": True,
        },
        {
            "id": "employee_intro",
            "title": "معرفی مشخصات پرسنل",
            "body": "با سلام و احترام،\nبدین‌وسیله آقا/خانم {{employee.employee_name}} با کد ملی {{employee.national_id}} و کد پرسنلی {{employee.employee_number}} به‌عنوان یکی از کارکنان {{company.company_name}} معرفی می‌گردد.",
            "enabled": True,
        },
        {
            "id": "position_purpose",
            "title": "سمت و هدف معرفی",
            "body": "نامبرده در جایگاه {{employee.designation}} و واحد {{employee.department}} فعالیت دارد و جهت {{letter.purpose}} به آن مرجع معرفی می‌شود.",
            "enabled": True,
        },
        {
            "id": "cooperation_notes",
            "title": "درخواست همکاری و اعتبار نامه",
            "body": "خواهشمند است در حدود ضوابط آن مرجع، همکاری لازم با نامبرده به عمل آید.\n{{letter.notes}}",
            "enabled": True,
        },
        {
            "id": "authority_sign",
            "title": "مشخصات مقام صادرکننده",
            "body": "با احترام\n{{company.representative}}\n{{company.representative_position}}\n{{company.company_name}}",
            "enabled": True,
        },
    ],
    "required_recipient": True,
    "required_purpose": True,
    "has_expiry": False,
}


def normalize_search(value: object) -> str:
    return re.sub(
        r"\s+", " ", str(value or "").translate(_DIGITS).replace("ي", "ی").replace("ك", "ک")
    ).strip().lower()


def _token_value(token: str, values: dict) -> str:
    current = values
    for part in token.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return "" if current is None else escape(str(current))


def validate_template(template: dict) -> dict:
    if not isinstance(template, dict) or not isinstance(template.get("clauses"), list):
        raise ValueError("ساختار قالب معرفی‌نامه معتبر نیست.")

    required_recipient = template.get("required_recipient", True)
    required_purpose = template.get("required_purpose", True)
    has_expiry = template.get("has_expiry", False)

    if not isinstance(required_recipient, bool) or not isinstance(required_purpose, bool) or not isinstance(has_expiry, bool):
        raise ValueError("تنظیمات قالب معتبر نیست.")

    clause_ids = set()
    clauses = []
    for clause in template["clauses"]:
        if (
            not isinstance(clause, dict)
            or not isinstance(clause.get("id"), str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", clause["id"])
            or clause["id"] in clause_ids
        ):
            raise ValueError("شناسه پایدار بند معتبر نیست.")
        body = clause.get("body")
        if not isinstance(clause.get("title"), str) or not clause["title"].strip() or not isinstance(body, str):
            raise ValueError("عنوان و متن بند را کامل کنید.")
        for raw in re.findall(r"{{(.*?)}}", body):
            if not _TOKEN.fullmatch("{{" + raw + "}}"):
                raise ValueError("شناسه فیلد در متن بند معتبر نیست.")
        clause_ids.add(clause["id"])
        clauses.append({
            "id": clause["id"],
            "title": clause["title"].strip(),
            "body": body,
            "enabled": clause.get("enabled") is not False,
        })

    return {
        "clauses": clauses,
        "required_recipient": required_recipient,
        "required_purpose": required_purpose,
        "has_expiry": has_expiry,
    }


def render_snapshot(template: dict, values: dict) -> dict:
    template = validate_template(template)
    values = values if isinstance(values, dict) else {}
    blocks = []
    for clause in template["clauses"]:
        if clause["enabled"]:
            body = _TOKEN.sub(lambda match: _token_value(match.group(1), values), clause["body"])
            # Format newlines
            formatted_body = body.replace("\n", "<br>")
            blocks.append(f"<section style=\"margin-bottom: 14px;\"><h3 style=\"font-size: 13px; color: #243f60; margin: 0 0 6px 0;\">{escape(clause['title'])}</h3><p style=\"font-size: 12px; line-height: 1.9; margin: 0; color: #37475a;\">{formatted_body}</p></section>")

    return {
        "template": deepcopy(template),
        "values": deepcopy(values),
        "html": '<article dir="rtl">' + "".join(blocks) + "</article>",
    }


def build_print_html(
    rendered_html: str,
    letterhead_html: str | None = None,
    number: str = "—",
    issue_date: str = "—",
    validity_date: str = "",
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
    validity_meta = (
        f'<span>اعتبار تا: {escape(validity_date)}</span>'
        if validity_date
        else ''
    )

    return (
        f'<article dir="rtl" style="font-family: Tahoma, \'Noto Sans Arabic\', sans-serif; padding: 24px; line-height: 2; color: #202f42;">'
        f'{letterhead_section}'
        f'<hr style="border: 0; border-top: 1px solid #b8c6d3; margin: 10px 0 16px 0;">'
        f'<h2 style="text-align: center; font-size: 17px; color: #243f60; margin: 10px 0;">معرفی‌نامه پرسنل</h2>'
        f'{draft_banner}'
        f'<div style="display: flex; justify-content: space-between; font-size: 11px; color: #62768c; margin-bottom: 16px;">'
        f'<span>شماره: {escape(number)}</span>'
        f'<span>تاریخ: {escape(issue_date)}</span>'
        f'{validity_meta}'
        f'</div>'
        f'{rendered_html}'
        f'<div style="display: flex; justify-content: space-between; margin-top: 60px; font-size: 11px; padding: 0 20px;">'
        f'<span>نام و امضای مقام مجاز</span>'
        f'<span>مهر شرکت</span>'
        f'</div>'
        f'<footer style="margin-top: 50px; text-align: center; font-size: 10px; color: #748398; border-top: 1px solid #b8c6d3; padding-top: 10px;">'
        f'پابرگ و اطلاعات شرکت از تنظیمات مشترک چاپ ASOUD ERP'
        f'</footer>'
        f'</article>'
    )
