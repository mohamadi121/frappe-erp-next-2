import pytest

from asoud_erp.services.employment_certificates import (
    MISSING_MESSAGE,
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
