"""Parametrized unit tests for malformed inputs across the five HR documents."""

import pytest

from asoud_erp.services.employment_certificates import validate_template as validate_cert_template
from asoud_erp.services.employment_contract import validate_contract_template
from asoud_erp.services.hiring_orders import validate_template as validate_hiring_template
from asoud_erp.services.personnel_introduction_letters import validate_template as validate_intro_template
from asoud_erp.services.salary_change_orders import validate_template as validate_salary_template


# 1. Employment Contracts malformed input matrix
@pytest.mark.parametrize("clauses,salary_rows,title,expected_error_substr", [
    (None, [], "قالب", "حداقل یک ماده"),
    ([], [], "قالب", "حداقل یک ماده"),
    ("not-a-list", [], "قالب", "حداقل یک ماده"),
    ([None], [], "قالب", "ساختار مواد قرارداد معتبر نیست"),
    (["not-a-dict"], [], "قالب", "ساختار مواد قرارداد معتبر نیست"),
    ([{"title": "", "body": "متن"}], [], "قالب", "عنوان و متن تمام مواد قرارداد"),
    ([{"title": "عنوان", "body": ""}], [], "قالب", "عنوان و متن تمام مواد قرارداد"),
    ([{"title": "عنوان", "body": "x" * 10001}], [], "قالب", "فراتر از حد مجاز"),
    ([{"title": "x" * 501, "body": "متن"}], [], "قالب", "فراتر از حد مجاز"),
    ([{"title": "ماده ۱", "body": "متن"}], [None], "قالب", "ساختار ردیف حقوق و مزایا معتبر نیست"),
    ([{"title": "ماده ۱", "body": "متن"}], [{"name": "پایه", "period": "daily"}], "قالب", "دوره پرداخت اقلام حقوقی"),
    ([{"title": "ماده ۱", "body": "متن"}], [{"name": "", "period": "monthly"}], "قالب", "نام ردیف جدول حقوق و مزایا"),
    ([{"title": "ماده ۱", "body": "متن"}], [], "", "عنوان قالب قرارداد الزامی است"),
])
def test_contracts_malformed_inputs(clauses, salary_rows, title, expected_error_substr):
    with pytest.raises(ValueError) as exc:
        validate_contract_template(clauses, salary_rows, title)
    assert expected_error_substr in str(exc.value)


# 2. Employment Certificates malformed input matrix
@pytest.mark.parametrize("payload,expected_error_substr", [
    (None, "ساختار قالب گواهی معتبر نیست"),
    ("not-a-dict", "ساختار قالب گواهی معتبر نیست"),
    ({"clauses": None, "salary_enabled": False, "salary_rows": []}, "ساختار قالب گواهی معتبر نیست"),
    ({"clauses": [None], "salary_enabled": False, "salary_rows": []}, "شناسه پایدار بند معتبر نیست"),
    ({"clauses": ["not-a-dict"], "salary_enabled": False, "salary_rows": []}, "شناسه پایدار بند معتبر نیست"),
    ({"clauses": [{"id": "c1", "title": "", "body": "متن"}], "salary_enabled": False, "salary_rows": []}, "عنوان و متن بند را کامل کنید"),
    ({"clauses": [{"id": "c1", "title": "عنوان", "body": "x" * 10001}], "salary_enabled": False, "salary_rows": []}, "فراتر از حد مجاز"),
    ({"clauses": [{"id": "c1", "title": "عنوان", "body": "متن {{invalid..field}}"}], "salary_enabled": False, "salary_rows": []}, "شناسه فیلد در متن بند معتبر نیست"),
    ({"clauses": [{"id": "c1", "title": "عنوان", "body": "متن"}], "salary_enabled": True, "salary_rows": []}, "حداقل یک قلم لازم است"),
    ({"clauses": [{"id": "c1", "title": "عنوان", "body": "متن"}], "salary_enabled": False, "salary_rows": [None]}, "شناسه فیلد حقوق معتبر نیست"),
])
def test_certificates_malformed_inputs(payload, expected_error_substr):
    with pytest.raises(ValueError) as exc:
        validate_cert_template(payload)
    assert expected_error_substr in str(exc.value)


# 3. Hiring Orders malformed input matrix
@pytest.mark.parametrize("payload,expected_error_substr", [
    (None, "ساختار قالب حکم معتبر نیست"),
    ("not-a-dict", "ساختار قالب حکم معتبر نیست"),
    ({"articles": None, "payroll_rows": []}, "شش ماده داشته باشد"),
    ({"articles": [{"id": "a1", "title": "t", "body": "b"}], "payroll_rows": []}, "شش ماده داشته باشد"),
    ({"articles": [None] * 6, "payroll_rows": []}, "ساختار مادهٔ حکم معتبر نیست"),
    ({"articles": ["not-a-dict"] * 6, "payroll_rows": []}, "ساختار مادهٔ حکم معتبر نیست"),
    ({
        "articles": [
            {"id": f"art_{i}", "title": "عنوان", "body": "x" * 10001 if i == 0 else "متن"}
            for i in range(6)
        ],
        "payroll_rows": [{"id": "p1", "field_ref": "base", "period": "monthly"}],
    }, "فراتر از حد مجاز"),
    ({
        "articles": [{"id": f"art_{i}", "title": "عنوان", "body": "متن"} for i in range(6)],
        "payroll_rows": None,
    }, "حداقل یک قلم حقوق و مزایا لازم است"),
    ({
        "articles": [{"id": f"art_{i}", "title": "عنوان", "body": "متن"} for i in range(6)],
        "payroll_rows": [None],
    }, "ساختار ردیف حقوق معتبر نیست"),
])
def test_hiring_orders_malformed_inputs(payload, expected_error_substr):
    with pytest.raises(ValueError) as exc:
        validate_hiring_template(payload)
    assert expected_error_substr in str(exc.value)


# 4. Personnel Introduction Letters malformed input matrix
@pytest.mark.parametrize("payload,expected_error_substr", [
    (None, "ساختار قالب معرفی‌نامه معتبر نیست"),
    ("not-a-dict", "ساختار قالب معرفی‌نامه معتبر نیست"),
    ({"clauses": None}, "ساختار قالب معرفی‌نامه معتبر نیست"),
    ({"clauses": [None], "workflow": ""}, "شناسه پایدار بند معتبر نیست"),
    ({"clauses": ["bad"], "workflow": ""}, "شناسه پایدار بند معتبر نیست"),
    ({"clauses": [{"id": "b1", "title": "", "body": "متن"}], "workflow": ""}, "عنوان و متن بند را کامل کنید"),
    ({"clauses": [{"id": "b1", "title": "عنوان", "body": "x" * 10001}], "workflow": ""}, "فراتر از حد مجاز"),
    ({"clauses": [{"id": "b1", "title": "عنوان", "body": "متن"}], "workflow": 12345}, "گردش کار قالب معرفی‌نامه معتبر نیست"),
])
def test_introduction_letters_malformed_inputs(payload, expected_error_substr):
    with pytest.raises(ValueError) as exc:
        validate_intro_template(payload)
    assert expected_error_substr in str(exc.value)


# 5. Salary Change Orders malformed input matrix
@pytest.mark.parametrize("payload,expected_error_substr", [
    (None, "ساختار قالب حکم معتبر نیست"),
    ("not-a-dict", "ساختار قالب حکم معتبر نیست"),
    ({"articles": None, "comparison_rows": []}, "شش ماده داشته باشد"),
    ({"articles": [{"id": "a1", "title": "t", "body": "b"}], "comparison_rows": []}, "شش ماده داشته باشد"),
    ({"articles": [None] * 6, "comparison_rows": []}, "ماده قالب معتبر نیست"),
    ({
        "articles": [
            {"id": f"art_{i}", "title": "عنوان", "body": "x" * 10001 if i == 0 else "متن"}
            for i in range(6)
        ],
        "comparison_rows": [{"id": "base", "title": "حقوق", "period": "monthly", "old_ref": "old", "new_ref": "new"}],
    }, "فراتر از حد مجاز"),
    ({
        "articles": [{"id": f"art_{i}", "title": "عنوان", "body": "متن"} for i in range(6)],
        "comparison_rows": None,
    }, "حداقل یک قلم حقوق و مزایا"),
    ({
        "articles": [{"id": f"art_{i}", "title": "عنوان", "body": "متن"} for i in range(6)],
        "comparison_rows": [None],
    }, "ردیف جدول مقایسه معتبر نیست"),
])
def test_salary_change_orders_malformed_inputs(payload, expected_error_substr):
    with pytest.raises(ValueError) as exc:
        validate_salary_template(payload)
    assert expected_error_substr in str(exc.value)
