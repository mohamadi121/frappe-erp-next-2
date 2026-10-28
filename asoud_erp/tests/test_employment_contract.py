import pytest

from asoud_erp.services.employment_contract import (
    DEFAULT_CLAUSES,
    DEFAULT_SALARY_ROWS,
    calculate_salary_items,
    generate_contract_print_data,
    get_field_catalog,
    normalize_search_term,
    render_contract_articles,
    validate_contract_template,
)


def test_default_clauses_and_salary_rows():
    assert len(DEFAULT_CLAUSES) >= 5
    assert DEFAULT_CLAUSES[0]["title"] == "طرفین قرارداد"
    assert len(DEFAULT_SALARY_ROWS) >= 3
    assert DEFAULT_SALARY_ROWS[0]["fieldRef"] == "payroll.base_salary"


def test_validate_contract_template_normalizes_and_sorts_by_order():
    raw_clauses = [
        {"id": "c2", "title": "ماده دوم", "body": "متن ماده دوم", "order": 2},
        {"id": "c1", "title": "ماده اول", "body": "متن ماده اول", "order": 1},
    ]
    raw_rows = [
        {"id": "r1", "name": "حقوق پایه", "period": "monthly", "fieldRef": "payroll.base_salary"},
    ]
    template = validate_contract_template(raw_clauses, raw_rows)
    assert template["clauses"][0]["id"] == "c1"
    assert template["clauses"][1]["id"] == "c2"
    assert template["clauses"][0]["order"] == 1
    assert template["clauses"][1]["order"] == 2


def test_validate_contract_template_rejects_empty():
    with pytest.raises(ValueError, match="حداقل یک ماده"):
        validate_contract_template([], DEFAULT_SALARY_ROWS)

    with pytest.raises(ValueError, match="عنوان و متن"):
        validate_contract_template([{"id": "c1", "title": "", "body": "متن"}], DEFAULT_SALARY_ROWS)


def test_validate_salary_rows_rejects_invalid_period():
    with pytest.raises(ValueError, match="دوره پرداخت"):
        validate_contract_template(DEFAULT_CLAUSES, [{"id": "r1", "name": "پاداش", "period": "weekly", "fieldRef": "payroll.bonus"}])


def test_render_contract_articles():
    clauses = [
        {"id": "c1", "title": "طرفین", "body": "این قرارداد میان {{company.company_name}} و {{personnel.employee_name}} است.", "order": 1}
    ]
    context = {
        "company": {"company_name": "شرکت تابان"},
        "personnel": {"employee_name": "محمد رضایی"},
    }
    rendered = render_contract_articles(clauses, context)
    assert rendered[0]["body"] == "این قرارداد میان شرکت تابان و محمد رضایی است."
    assert rendered[0]["title"] == "ماده ۱: طرفین"


def test_salary_calculation_with_missing_values_explicit_state():
    rows = [
        {"id": "r1", "name": "حقوق پایه", "period": "monthly", "fieldRef": "payroll.base_salary"},
        {"id": "r2", "name": "حق مسکن", "period": "monthly", "fieldRef": "payroll.housing"},
    ]
    # base is provided, housing is None (missing)
    values = {"payroll.base_salary": 235000000, "payroll.housing": None}
    calc = calculate_salary_items(rows, values)
    assert calc["items"][0]["has_value"] is True
    assert calc["items"][0]["amount"] == 235000000
    assert "۲۳۵٬۰۰۰٬۰۰۰" in calc["items"][0]["formatted_amount"]

    # Missing value MUST NOT be silently 0! It must be explicit "اطلاعات موجود نیست"
    assert calc["items"][1]["has_value"] is False
    assert calc["items"][1]["amount"] is None
    assert calc["items"][1]["formatted_amount"] == "اطلاعات موجود نیست"
    assert calc["total_monthly"] == 235000000
    assert "۲۳۵٬۰۰۰٬۰۰۰" in calc["formatted_total_monthly"]


def test_normalize_search_term():
    # Arabic letters to Persian
    assert normalize_search_term("علي كمالي") == "علی کمالی"
    # Persian digits to ASCII
    assert normalize_search_term("HR-۱۰۱") == "hr-101"
    # Mixed digits and spaces
    assert normalize_search_term("  ۱۲۳۴  ") == "1234"


def test_field_catalog_gated_by_payroll_permission():
    unauthorized = get_field_catalog(has_payroll_permission=False)
    payroll_cat = next(c for c in unauthorized["categories"] if c["key"] == "payroll")
    assert payroll_cat["authorized"] is False

    authorized = get_field_catalog(has_payroll_permission=True)
    payroll_cat_auth = next(c for c in authorized["categories"] if c["key"] == "payroll")
    assert payroll_cat_auth["authorized"] is True
    assert len(payroll_cat_auth["fields"]) >= 5


def test_generate_contract_print_data_draft_vs_final():
    clauses = [{"order": 1, "title": "ماده ۱: طرفین", "body": "متن قرارداد"}]
    salary_items = [{"name": "حقوق پایه", "period": "ماهانه", "formatted_amount": "۲۳۵٬۰۰۰٬۰۰۰ ریال"}]

    draft_print = generate_contract_print_data(
        is_draft=True,
        contract_number=None,
        issue_date="1405/08/01",
        employee_name="محمد رضایی",
        rendered_clauses=clauses,
        salary_table=salary_items,
        total_monthly_formatted="۲۳۵٬۰۰۰٬۰۰۰ ریال",
        letterhead_html="<div>سربرگ شرکت</div>"
    )
    assert draft_print["is_draft"] is True
    assert draft_print["draft_banner"] == "«پیش‌نویس ـ فاقد اعتبار نهایی»"
    assert draft_print["contract_number"] == "شماره پس از صدور"
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" in draft_print["html"]

    final_print = generate_contract_print_data(
        is_draft=False,
        contract_number="CNT-1405-00001",
        issue_date="1405/08/01",
        employee_name="محمد رضایی",
        rendered_clauses=clauses,
        salary_table=salary_items,
        total_monthly_formatted="۲۳۵٬۰۰۰٬۰۰۰ ریال",
        letterhead_html="<div>سربرگ شرکت</div>"
    )
    assert final_print["is_draft"] is False
    assert final_print["draft_banner"] is None
    assert final_print["contract_number"] == "CNT-1405-00001"
    assert "CNT-1405-00001" in final_print["html"]
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final_print["html"]
