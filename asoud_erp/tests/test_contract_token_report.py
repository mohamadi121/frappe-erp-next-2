"""Pure tests for contract token reporting.

The contract renderer must never silently drop a missing or unknown token:
a known field with no value renders a neutral placeholder and is reported by
its Persian title; an unknown (legacy) token renders the same placeholder and
is reported by its raw key. The technical key must never appear in the
rendered text, and the stored template string must not be mutated.
"""

from asoud_erp.services.employment_contract import render_contract_articles_with_findings


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
