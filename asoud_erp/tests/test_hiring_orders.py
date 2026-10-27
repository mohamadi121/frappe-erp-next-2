import pytest

from asoud_erp.services.hiring_orders import (
    default_template,
    format_hiring_order_print,
    normalize_search,
    render_article_body,
    snapshot_payroll,
    validate_template,
)


def test_default_hiring_template_has_six_stable_articles_and_payroll_bindings():
    template = default_template()
    assert [article["id"] for article in template["articles"]] == [
        "employee_details", "employment_effective_date", "organization_position",
        "duties", "salary_benefits", "issuing_authority",
    ]
    assert template["payroll_rows"][0]["field_ref"] == "base"


def test_template_rejects_label_only_or_unknown_payroll_binding():
    template = default_template()
    template["payroll_rows"][0].pop("field_ref")
    with pytest.raises(ValueError, match="شناسه پایدار"):
        validate_template(template)


def test_payroll_snapshot_keeps_missing_explicit_and_only_sums_monthly():
    rows = snapshot_payroll([
        {"id": "base", "title": "حقوق پایه", "period": "monthly", "amount": 10},
        {"id": "bonus", "title": "پاداش", "period": "yearly", "amount": 120},
        {"id": "housing", "title": "حق مسکن", "period": "monthly", "amount": None},
    ])
    assert rows["monthly_total"] == 10
    assert rows["rows"][2]["state"] == "missing"
    assert rows["rows"][2]["message"] == "اطلاعات موجود نیست"


@pytest.mark.parametrize("raw", ["علي كد ۱۲۳", "علی کد ١٢٣", "علی کد 123"])
def test_search_normalization_equates_persian_arabic_and_latin_forms(raw):
    assert normalize_search(raw) == "علی کد 123"


def test_render_article_body_replaces_placeholders():
    body = "به موجب این حکم، [نام و نام خانوادگی پرسنل] در واحد {{department}} مشغول به کار خواهد بود."
    rendered = render_article_body(body, {
        "employee_name": "سهراب سپهری",
        "department": "اداری",
    })
    assert rendered == "به موجب این حکم، سهراب سپهری در واحد اداری مشغول به کار خواهد بود."


def test_format_hiring_order_print_shows_draft_watermark_when_not_final():
    order = {
        "status": "draft",
        "number": "ORD-1405-001",
        "employee_name": "علی رضایی",
        "employee_number": "HR-101",
        "company_name": "آسود",
        "template_snapshot": default_template(),
        "payroll_snapshot": snapshot_payroll([
            {"id": "base", "title": "حقوق پایه", "period": "monthly", "amount": 150000000},
            {"id": "housing", "title": "حق مسکن", "period": "monthly", "amount": None},
        ]),
    }
    html = format_hiring_order_print(order)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" in html
    assert "شماره: —" in html
    assert "حقوق پایه" in html
    assert "اطلاعات موجود نیست" in html
    assert "۱۵۰٬۰۰۰٬۰۰۰" in html


def test_format_hiring_order_print_omits_watermark_when_final():
    order = {
        "status": "final",
        "number": "ORD-1405-007",
        "issue_date": "1405/01/15",
        "employee_name": "علی رضایی",
        "company_name": "آسود",
        "template_snapshot": default_template(),
        "payroll_snapshot": snapshot_payroll([
            {"id": "base", "title": "حقوق پایه", "period": "monthly", "amount": 200000000},
        ]),
    }
    html = format_hiring_order_print(order)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in html
    assert "ORD-۱۴۰۵-۰۰۷" in html
    assert "۱۴۰۵/۰۱/۱۵" in html

