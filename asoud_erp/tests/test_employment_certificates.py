import pytest

from asoud_erp.services.employment_certificates import (
    DEFAULT_TEMPLATE,
    MISSING_MESSAGE,
    build_print_html,
    normalize_search,
    render_snapshot,
    validate_template,
)


def test_template_uses_stable_references_and_salary_is_explicitly_optional():
    template = validate_template({"clauses": [{"id": "address", "title": "مخاطب", "body": "به {{certificate.addressee_name}}"}], "salary_enabled": False, "salary_rows": []})
    assert template["clauses"][0]["id"] == "address"
    assert template["salary_rows"] == []
    with pytest.raises(ValueError, match="شناسه فیلد"):
        validate_template({"clauses": [{"id": "address", "title": "مخاطب", "body": "{{گیرنده گواهی}}"}], "salary_enabled": False, "salary_rows": []})


def test_snapshot_never_leaks_salary_when_template_disables_it():
    document = render_snapshot({"clauses": [{"id": "body", "title": "متن", "body": "{{employee.employee_name}}"}], "salary_enabled": False, "salary_rows": []}, {"employee": {"employee_name": "مینا"}, "certificate": {}}, [{"title": "حقوق پایه", "amount": 100}])
    assert "مینا" in document["html"]
    assert "حقوق پایه" not in document["html"]
    assert document["salary_rows"] == []


def test_salary_missing_is_explicit_and_periods_are_not_summed():
    document = render_snapshot({"clauses": [], "salary_enabled": True, "salary_rows": [{"id": "base", "title": "حقوق پایه", "field_ref": "base", "period": "monthly"}]}, {"employee": {}, "certificate": {}}, [{"id": "base", "title": "حقوق پایه", "amount": None, "period": "monthly"}])
    assert document["salary_rows"][0]["message"] == MISSING_MESSAGE
    assert "اطلاعات موجود نیست" in document["html"]


def test_search_normalizes_letters_and_all_digit_sets():
    assert normalize_search("ك ي ۱۲۳ ٤٥") == "ک ی 123 45"


def test_default_template_is_valid():
    validated = validate_template(DEFAULT_TEMPLATE)
    assert len(validated["clauses"]) >= 3
    assert validated["salary_enabled"] is False


def test_build_print_html_shows_draft_mark_and_hides_in_final():
    draft_html = build_print_html("<p>متن</p>", is_final=False)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" in draft_html
    assert "گواهی اشتغال به کار" in draft_html
    assert "شماره: —" in draft_html

    final_html = build_print_html("<p>متن</p>", number="CERT-1405-0001", issue_date="1405/01/15", is_final=True)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final_html
    assert "شماره: CERT-1405-0001" in final_html
    assert "تاریخ: 1405/01/15" in final_html


