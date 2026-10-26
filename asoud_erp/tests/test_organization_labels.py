from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_labels import localize_position, organization_label


def test_known_labels_and_custom_names():
    assert organization_label("All Departments") == "همهٔ واحدها"
    assert organization_label("  HUMAN   RESOURCES ") == "منابع انسانی"
    assert organization_label("Sales Manager") == "مدیر فروش"
    for custom in ("Sales - Tehran", "My Sales Team", "بازاریابی دیجیتال", "Salesforce"):
        assert organization_label(custom) == custom


def test_display_is_not_a_rename_or_authoritative_input():
    source = {"code": "CEO", "title": "CEO", "parent": "", "department": "Finance",
              "department_id": "Finance - EX", "employee": ""}
    localized = localize_position(source)
    assert localized["display_title"] == "مدیرعامل"
    assert localized["department_display_name"] == "مالی"
    assert source == {key: localized[key] for key in source}
    assert "display_title" not in source
    assert validate_rows([localized]) == [source]
