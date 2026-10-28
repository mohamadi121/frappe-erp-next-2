"""Unit tests for pure salary-change order domain logic and calculations."""

import pytest

from asoud_erp.services.digits import to_persian_digits
from asoud_erp.services.salary_change_orders import (
    MISSING_MESSAGE,
    NOT_CALCULABLE_MESSAGE,
    calculate_comparison_row,
    calculate_comparison_table,
    default_template,
    format_salary_change_order_print,
    normalize_search,
    render_article_body,
    validate_template,
)


def test_default_template_has_six_stable_articles_and_comparison_rows():
    template = default_template()
    assert isinstance(template, dict)
    articles = template["articles"]
    assert len(articles) == 6
    expected_ids = [
        "employee_details",
        "subject_reason",
        "effective_date",
        "salary_comparison",
        "terms",
        "issuing_authority",
    ]
    assert [a["id"] for a in articles] == expected_ids
    assert all(a["title"].strip() for a in articles)
    assert all(a["body"].strip() for a in articles)

    rows = template["comparison_rows"]
    assert len(rows) >= 3
    for row in rows:
        assert row["id"]
        assert row["title"]
        assert row["period"] in ("monthly", "yearly", "one_off")
        assert row["old_ref"].startswith("payroll.")
        assert row["new_ref"].startswith("document.new.")


def test_validate_template_rejects_invalid_articles_or_rows():
    # Must have exactly 6 articles
    with pytest.raises(ValueError, match="شش ماده"):
        validate_template({"articles": [{"id": "a1", "title": "t1", "body": "b1"}], "comparison_rows": []})

    valid = default_template()
    assert validate_template(valid) == valid
    # Invalid ID
    bad_id = default_template()
    bad_id["articles"][0]["id"] = "Invalid-ID!"
    with pytest.raises(ValueError, match="شناسه پایدار ماده"):
        validate_template(bad_id)

    # Empty rows
    bad_rows = default_template()
    bad_rows["comparison_rows"] = []
    with pytest.raises(ValueError, match="حداقل یک قلم"):
        validate_template(bad_rows)


def test_calculate_comparison_row_difference_and_percentage():
    # Normal case: base 200,000 to 250,000 (+25%)
    res = calculate_comparison_row(
        row_id="base",
        title="حقوق پایه",
        period="monthly",
        old_ref="payroll.base_salary",
        new_ref="document.new.base_salary",
        previous_amount=200000000,
        new_amount=250000000,
    )
    assert res["previous_amount"] == 200000000
    assert res["new_amount"] == 250000000
    assert res["difference"] == 50000000
    assert res["percent_change"] == 25.0
    assert res["state"] == "available"

    # Previous is zero => percent change is NOT calculable, no zero-division
    res_zero = calculate_comparison_row(
        row_id="bonus",
        title="پاداش",
        period="monthly",
        old_ref="payroll.bonus",
        new_ref="document.new.bonus",
        previous_amount=0,
        new_amount=10000000,
    )
    assert res_zero["difference"] == 10000000
    assert res_zero["percent_change"] is None
    assert res_zero["percent_label"] == NOT_CALCULABLE_MESSAGE

    # Missing previous amount => explicit missing state, never 0
    res_missing = calculate_comparison_row(
        row_id="housing",
        title="حق مسکن",
        period="monthly",
        old_ref="payroll.housing",
        new_ref="document.new.housing",
        previous_amount=None,
        new_amount=9000000,
    )
    assert res_missing["previous_amount"] is None
    assert res_missing["difference"] is None
    assert res_missing["percent_change"] is None
    assert res_missing["state"] == "missing"
    assert res_missing["message"] == MISSING_MESSAGE


def test_calculate_comparison_table_totals_only_sums_monthly():
    rows = [
        {
            "id": "base",
            "title": "حقوق پایه",
            "period": "monthly",
            "old_ref": "payroll.base_salary",
            "new_ref": "document.new.base_salary",
            "previous_amount": 200000000,
            "new_amount": 250000000,
        },
        {
            "id": "food",
            "title": "بن خواربار",
            "period": "monthly",
            "old_ref": "payroll.food",
            "new_ref": "document.new.food",
            "previous_amount": 20000000,
            "new_amount": 22000000,
        },
        {
            "id": "bonus_yearly",
            "title": "پاداش سالانه",
            "period": "yearly",
            "old_ref": "payroll.bonus_yearly",
            "new_ref": "document.new.bonus_yearly",
            "previous_amount": 100000000,
            "new_amount": 120000000,
        },
    ]

    table = calculate_comparison_table(rows)
    assert len(table["rows"]) == 3
    # Monthly sums should only include the first two rows (200M + 20M = 220M; 250M + 22M = 272M; diff = 52M)
    # The yearly bonus (100M / 120M) MUST NOT be summed with monthly!
    assert table["monthly_previous_total"] == 220000000
    assert table["monthly_new_total"] == 272000000
    assert table["monthly_difference"] == 52000000


def test_normalize_search_equates_persian_arabic_and_digits():
    s1 = normalize_search("علي رضايي ۱۲۳")
    s2 = normalize_search("علی رضایی 123")
    s3 = normalize_search("علی رضایی ١٢٣")
    assert s1 == s2 == s3 == "علی رضایی 123"


def test_render_article_body_replaces_placeholders():
    body = "به موجب این حکم وضعیت حقوق [نام و نام خانوادگی پرسنل] با کد [کد پرسنلی] در تاریخ [تاریخ اجرای تغییر] تغییر می‌یابد."
    rendered = render_article_body(body, {
        "employee_name": "سهراب سپهری",
        "employee_number": "EMP-902",
        "effective_date": "1405/08/01",
    })
    assert "سهراب سپهری" in rendered
    assert "EMP-902" in rendered
    assert "1405/08/01" in rendered


def test_format_salary_change_order_print_shows_draft_watermark_when_not_final():
    draft_data = {
        "status": "draft",
        "number": "پیش‌نویس",
        "employee_name": "احمد شاملو",
        "employee_number": "EMP-101",
        "company_name": "شرکت تابان",
        "effective_date": "1405/08/01",
        "issue_date": "1405/08/05",
        "reason": "افزایش سالانه",
        "template_snapshot": default_template(),
        "comparison_table": calculate_comparison_table([
            {
                "id": "base",
                "title": "حقوق پایه",
                "period": "monthly",
                "old_ref": "payroll.base_salary",
                "new_ref": "document.new.base_salary",
                "previous_amount": 200000000,
                "new_amount": 230000000,
            }
        ]),
    }
    html_draft = format_salary_change_order_print(draft_data)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" in html_draft
    assert "احمد شاملو" in html_draft
    assert "جدول مقایسه حقوق و مزایا" in html_draft
    assert "table-header-group" in html_draft

    final_data = dict(draft_data, status="final", number="SAL-1405-001")
    html_final = format_salary_change_order_print(final_data)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in html_final
    assert to_persian_digits("SAL-1405-001") in html_final
