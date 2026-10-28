from datetime import date

import pytest

from asoud_erp.services.personnel_introduction_letters import (
    DEFAULT_TEMPLATE,
    build_print_html,
    normalize_search,
    render_snapshot,
    validate_template,
)
from asoud_erp.services.request_templates.base import number_pattern


def test_optional_workflow_reference_is_preserved_in_template_snapshot():
    template = {**DEFAULT_TEMPLATE, "workflow": "approved-introduction-process"}
    snapshot = render_snapshot(template, {"employee": {"employee_name": "پرسنل"}})
    template["workflow"] = "replacement-process"
    assert snapshot["template"]["workflow"] == "approved-introduction-process"
    assert validate_template(DEFAULT_TEMPLATE)["workflow"] == ""


@pytest.mark.parametrize("workflow", [None, 1, [], {}])
def test_workflow_reference_rejects_non_string_values(workflow):
    with pytest.raises(ValueError, match="گردش کار قالب معرفی‌نامه معتبر نیست"):
        validate_template({**DEFAULT_TEMPLATE, "workflow": workflow})


def test_introduction_numbers_use_shared_jalali_numbering_pattern():
    assert number_pattern("INTRO", date(2025, 3, 21)) == "INTRO-1404-.####"


def test_default_template_is_valid():
    validated = validate_template(DEFAULT_TEMPLATE)
    assert len(validated["clauses"]) >= 4
    assert validated["required_recipient"] is True
    assert validated["required_purpose"] is True
    assert validated["has_expiry"] is False


def test_template_uses_stable_field_identifiers():
    template = validate_template({
        "clauses": [
            {"id": "intro", "title": "مقدمه", "body": "به: {{letter.recipient}} جهت {{letter.purpose}}"}
        ],
        "required_recipient": True,
        "required_purpose": True,
        "has_expiry": False,
    })
    assert template["clauses"][0]["id"] == "intro"
    assert template["clauses"][0]["enabled"] is True

    # Invalid tag format fails validation
    with pytest.raises(ValueError, match="شناسه فیلد"):
        validate_template({
            "clauses": [
                {"id": "intro", "title": "مقدمه", "body": "{{نام گیرنده}}"}
            ],
            "required_recipient": True,
            "required_purpose": True,
            "has_expiry": False,
        })


def test_search_normalizes_persian_arabic_and_digits():
    assert normalize_search("ك ي ۱۲۳ ٤٥٦") == "ک ی 123 456"
    assert normalize_search("  بانک   ملي  ") == "بانک ملی"


def test_snapshot_renders_values_and_excludes_disabled_clauses():
    template = {
        "clauses": [
            {"id": "c1", "title": "بند ۱", "body": "سلام {{employee.employee_name}} به {{letter.recipient}}", "enabled": True},
            {"id": "c2", "title": "بند ۲", "body": "متن غیرفعال {{employee.national_id}}", "enabled": False},
        ],
        "required_recipient": True,
        "required_purpose": True,
        "has_expiry": False,
    }
    values = {
        "employee": {"employee_name": "سهراب سپهری", "national_id": "0012345678"},
        "letter": {"recipient": "بانک ملت شعبه ونک"},
    }
    snap = render_snapshot(template, values)
    assert "سهراب سپهری" in snap["html"]
    assert "بانک ملت شعبه ونک" in snap["html"]
    assert "متن غیرفعال" not in snap["html"]


def test_build_print_html_draft_and_final_markers():
    draft = build_print_html("<p>متن</p>", is_final=False)
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" in draft
    assert "معرفی‌نامه پرسنل" in draft
    assert "شماره: —" in draft

    final = build_print_html(
        "<p>متن</p>",
        number="INTRO-1405-00042",
        issue_date="1405/08/10",
        validity_date="1405/09/30",
        is_final=True,
    )
    assert "پیش‌نویس ـ فاقد اعتبار نهایی" not in final
    assert "شماره: INTRO-1405-00042" in final
    assert "تاریخ: 1405/08/10" in final
    assert "اعتبار تا: 1405/09/30" in final

def test_template_literal_html_is_escaped():
    snapshot = render_snapshot({"clauses": [{"id": "body", "title": "متن", "body": '<script>alert(1)</script>{{employee.employee_name}}', "enabled": True}]}, {"employee": {"employee_name": '<img src=x onerror=alert(2)>'}})
    assert '<script>' not in snapshot['html']
    assert '&lt;script&gt;' in snapshot['html']
    assert '<img' not in snapshot['html']
