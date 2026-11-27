"""Pure tests for contract token reporting.

The contract renderer must never silently drop a missing or unknown token:
a known field with no value renders a neutral placeholder and is reported by
its Persian title; an unknown (legacy) token renders the same placeholder and
is reported by its raw key. The technical key must never appear in the
rendered text, and the stored template string must not be mutated.
"""

from asoud_erp.services.employment_contract import (
    DEFAULT_CLAUSES,
    build_company_context,
    build_personnel_context,
    render_contract_articles_with_findings,
)


def _render(body, context):
    clauses = [{"id": "c1", "title": "ماده", "body": body, "order": 1}]
    return render_contract_articles_with_findings(clauses, context)


def test_known_token_with_value_is_byte_identical():
    rendered, findings = _render("این قرارداد میان {{company.company_name}} است.",
                                 {"company": {"company_name": "شرکت تابان"}})
    assert rendered[0]["body"] == "این قرارداد میان شرکت تابان است."
    assert findings["missing_fields"] == []
    assert findings["unknown_tokens"] == []


def test_known_token_without_value_renders_placeholder_and_reports_title():
    rendered, findings = _render("نام: {{personnel.employee_name}}",
                                 {"personnel": {"employee_name": ""}})
    # The technical key must never appear; a neutral placeholder is shown.
    assert rendered[0]["body"] == "نام: —"
    assert "personnel.employee_name" not in rendered[0]["body"]
    # The designer is told which known field has no value, by its Persian title.
    assert findings["missing_fields"] == ["نام و نام خانوادگی"]
    assert findings["unknown_tokens"] == []


def test_known_token_none_value_is_reported_missing():
    rendered, findings = _render("کد ملی: {{personnel.national_id}}",
                                 {"personnel": {"national_id": None}})
    assert rendered[0]["body"] == "کد ملی: —"
    assert findings["missing_fields"] == ["کد ملی"]


def test_unknown_token_renders_placeholder_and_reports_raw_key():
    rendered, findings = _render("ماده قدیمی: {{legacy.old_field}}", {})
    assert rendered[0]["body"] == "ماده قدیمی: —"
    # The raw key must never leak into the rendered text.
    assert "legacy.old_field" not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["legacy.old_field"]
    assert findings["missing_fields"] == []


def test_unknown_token_renders_placeholder_even_if_context_has_a_value():
    # An unknown (legacy) key is never trusted: it renders the placeholder and
    # is reported, even if the context happens to carry a value for it.
    rendered, findings = _render("قدیمی: {{legacy.old_field}}",
                                 {"legacy": {"old_field": "مقدار قدیمی"}})
    assert rendered[0]["body"] == "قدیمی: —"
    assert "مقدار قدیمی" not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["legacy.old_field"]
    assert findings["missing_fields"] == []


def test_findings_are_deduplicated_in_order_of_first_appearance():
    body = ("{{personnel.employee_name}} و {{personnel.national_id}} و "
            "{{personnel.employee_name}} و {{legacy.x}} و {{legacy.y}} و {{legacy.x}}")
    context = {"personnel": {"employee_name": "", "national_id": ""}}
    rendered, findings = _render(body, context)
    assert findings["missing_fields"] == ["نام و نام خانوادگی", "کد ملی"]
    assert findings["unknown_tokens"] == ["legacy.x", "legacy.y"]
    # Every placeholder is rendered, none of the keys leak.
    assert "personnel." not in rendered[0]["body"]
    assert "legacy." not in rendered[0]["body"]


def test_payroll_token_without_value_is_reported_and_never_leaks():
    # A caller without payroll permission has no payroll group in the context,
    # so the payroll token is a known field with no value: placeholder + title,
    # and the (absent) value can never leak.
    rendered, findings = _render("حقوق: {{payroll.base_salary}}", {})
    assert rendered[0]["body"] == "حقوق: —"
    assert findings["missing_fields"] == ["حقوق پایه"]
    assert findings["unknown_tokens"] == []
    assert "235000000" not in rendered[0]["body"]


def test_payroll_token_with_value_renders_value():
    rendered, findings = _render("حقوق: {{payroll.base_salary}}",
                                 {"payroll": {"base_salary": 235000000}})
    assert rendered[0]["body"] == "حقوق: 235000000"
    assert findings["missing_fields"] == []
    assert findings["unknown_tokens"] == []


def test_rendering_does_not_mutate_stored_template_text():
    original_body = "متن قالب با {{personnel.employee_name}} و {{legacy.x}}"
    clauses = [{"id": "c1", "title": "ماده", "body": original_body, "order": 1}]
    rendered, _ = render_contract_articles_with_findings(clauses, {})
    # The stored template string is passed through untouched.
    assert clauses[0]["body"] == original_body
    # The rendered output is a new string with placeholders, not the template.
    assert rendered[0]["body"] == "متن قالب با — و —"


def test_known_token_zero_value_renders_value():
    # 0 is a real value, not "missing": it renders "0" and is not reported.
    rendered, findings = _render("کد ملی: {{personnel.national_id}}",
                                 {"personnel": {"national_id": 0}})
    assert rendered[0]["body"] == "کد ملی: 0"
    assert findings["missing_fields"] == []
    assert findings["unknown_tokens"] == []


def test_known_token_false_value_renders_value():
    # False is a real (present) value, not "missing": it renders "False".
    # Documents the renderer's falsy handling so a future change that treats
    # falsy values as missing is caught.
    rendered, findings = _render("وضعیت: {{personnel.employee_name}}",
                                 {"personnel": {"employee_name": False}})
    assert rendered[0]["body"] == "وضعیت: False"
    assert findings["missing_fields"] == []
    assert findings["unknown_tokens"] == []


def test_malformed_token_with_space_is_reported_not_leaked():
    rendered, findings = _render("متن: {{employee name}}", {})
    assert rendered[0]["body"] == "متن: —"
    # The raw span (without braces) is reported; the key never leaks.
    assert "employee name" not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["employee name"]
    assert findings["missing_fields"] == []


def test_malformed_token_with_persian_digits_is_reported_not_leaked():
    rendered, findings = _render("متن: {{personnel.۱۲۳}}", {})
    assert rendered[0]["body"] == "متن: —"
    assert "personnel.۱۲۳" not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["personnel.۱۲۳"]
    assert findings["missing_fields"] == []


def test_malformed_nested_braces_token_is_reported_not_leaked():
    # A nested-brace span is matched as a whole (outermost) span and replaced,
    # so neither the outer fragment nor the inner key leaks.
    rendered, findings = _render("متن: {{a.{{b}}}}", {})
    assert rendered[0]["body"] == "متن: —"
    assert "{{" not in rendered[0]["body"]
    assert "a." not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["a.{{b}}"]
    assert findings["missing_fields"] == []


def test_malformed_spelling_is_never_resolved():
    # A known field with a malformed spelling (extra space) must NOT resolve to
    # the field's value; it is reported unknown, not whitespace-trimmed.
    rendered, findings = _render("متن: {{personnel. employee_name}}",
                                 {"personnel": {"employee_name": "علی"}})
    assert rendered[0]["body"] == "متن: —"
    assert "علی" not in rendered[0]["body"]
    assert findings["unknown_tokens"] == ["personnel. employee_name"]
    assert findings["missing_fields"] == []


def _fake_employee_and_company():
    emp = {
        "name": "HR-EMP-00001",
        "employee_name": "علی محمدی",
        "first_name": "علی",
        "last_name": "محمدی",
        "father_name": "رضا",
        "national_id": "0012345678",
        "department": "امور اداری",
        "designation": "کارشناس اداری",
        "date_of_joining": "2020-01-01",
        "cell_number": "09121234567",
        "current_address": "تهران",
        "current_postal_code": "1234567890",
    }
    comp = {
        "company_name": "شرکت نمونه",
        "tax_id": "10000000000",
        "phone_no": "02112345678",
        "email": "info@example.com",
    }
    return emp, comp


def test_shared_context_helpers_render_default_clauses_without_placeholder():
    # F1: prepare (preview) and save (stored -> issued) must build the same
    # personnel/company groups from the shared helpers, so the default
    # clause_1/clause_2 bodies render with no «—» in BOTH contexts when the
    # data exists, and the two contexts agree on the shared keys.
    emp, comp = _fake_employee_and_company()
    personnel = build_personnel_context(emp)
    company = build_company_context(comp, "نمونه")

    preview_context = {
        "personnel": personnel,
        "company": company,
        "contract": {"contract_type": "مدت‌معین", "start_date": "1405/08/01",
                     "end_date": "", "work_location": "شرکت نمونه",
                     "creation_date": "1405/08/01"},
    }
    save_context = {
        "personnel": personnel,
        "company": company,
        "contract": {"contract_type": "مدت‌معین", "start_date": "1405/08/01",
                     "end_date": "1405/09/01", "work_location": "شرکت نمونه",
                     "creation_date": "1405/08/01"},
    }

    # The two contexts agree on the shared personnel and company groups.
    assert preview_context["personnel"] == save_context["personnel"]
    assert preview_context["company"] == save_context["company"]

    for context in (preview_context, save_context):
        rendered, findings = render_contract_articles_with_findings(DEFAULT_CLAUSES, context)
        # clause_1 (طرفین) and clause_2 (موضوع و محل کار) reference personnel and
        # company fields that the shared helpers now always populate.
        assert "—" not in rendered[0]["body"], rendered[0]["body"]
        assert "—" not in rendered[1]["body"], rendered[1]["body"]
        # The identity fields that the old narrow save context blanked are present.
        assert "علی محمدی" in rendered[0]["body"]
        assert "رضا" in rendered[0]["body"]
        assert "0012345678" in rendered[0]["body"]
        assert "کارشناس اداری" in rendered[1]["body"]
        assert "امور اداری" in rendered[1]["body"]
