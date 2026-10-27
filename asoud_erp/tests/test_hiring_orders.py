import pytest

from asoud_erp.services.hiring_orders import default_template, normalize_search, snapshot_payroll, validate_template


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
