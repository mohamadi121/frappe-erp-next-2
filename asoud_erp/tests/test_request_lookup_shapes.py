import pytest

from asoud_erp.services.request_lookup import (
    FIELD_TYPE_SOURCES,
    FIELD_TYPES,
    SOURCE_FIELD_TYPES,
    delivery_location_value,
    leave_type_label,
    page_length,
    page_start,
    parse_delivery_location,
)
from asoud_erp.services.workflow_stage_policy import normalize_stage_config


def test_source_to_field_type_mapping():
    assert SOURCE_FIELD_TYPES == {
        "cost_center": "Cost Center", "project": "Project", "warehouse": "Warehouse", "branch": "Branch",
        "supplier": "Supplier", "leave_type": "Leave Type", "delivery_location": "Delivery Location",
    }
    assert FIELD_TYPE_SOURCES["Delivery Location"] == "delivery_location"
    assert set(FIELD_TYPES) == {"User", "Department", "Item", "UOM", *SOURCE_FIELD_TYPES.values()}


def test_every_source_is_accepted_by_the_form_policy():
    for source in SOURCE_FIELD_TYPES:
        field = {"key": "pick", "label": "انتخاب", "type": "System Select", "source": source}
        config = normalize_stage_config("User Task", {
            "title": "فرم", "activity_type": "Data Entry", "assignment_type": "Initiator",
            "form_fields": [field]})
        assert config["form_fields"][0]["source"] == source


@pytest.mark.parametrize("value,expected", [
    ("warehouse:Stores - WP", ("warehouse", "Stores - WP")),
    ("branch:Tehran", ("branch", "Tehran")),
    ("department:Sales - WP", ("department", "Sales - WP")),
    ("warehouse: Main : Floor 2 ", ("warehouse", "Main : Floor 2")),
])
def test_delivery_location_is_parsed(value, expected):
    assert parse_delivery_location(value) == expected
    assert delivery_location_value(*expected) == f"{expected[0]}:{expected[1]}"


@pytest.mark.parametrize("value", ["", "Stores - WP", "city:Tehran", "warehouse:", ":Stores", None, 5, "x" * 3 + ":" + "n" * 141])
def test_bad_delivery_locations_are_rejected(value):
    with pytest.raises(ValueError):
        parse_delivery_location(value)


def test_leave_type_label_uses_the_category_unless_several_types_share_it():
    assert leave_type_label("annual", "Casual Leave", 1) == "سالانه"
    assert leave_type_label("sick", "Sick Leave", 1) == "استعلاجی"
    assert leave_type_label("unpaid", "Leave Without Pay", 1) == "بدون حقوق"
    assert leave_type_label("other", "Study Leave", 1) == "سایر"
    assert leave_type_label("annual", "Privilege Leave", 2) == "سالانه — Privilege Leave"


def test_page_arguments_are_clamped():
    assert page_length(None) == 20 and page_length("x") == 20
    assert page_length(500) == 50 and page_length(0) == 1 and page_length("7") == 7
    assert page_start(-3) == 0 and page_start("5") == 5 and page_start(None) == 0


@pytest.mark.parametrize("name,is_lwp,expected", [
    ("Casual Leave", False, "annual"), ("Privilege Leave", False, "annual"), ("Earned Leave", False, "annual"),
    ("مرخصی سالانه", False, "annual"), ("مرخصی استحقاقی", False, "annual"),
    ("Sick Leave", False, "sick"), ("SICK leave", False, "sick"), ("مرخصی استعلاجی", False, "sick"),
    ("Leave Without Pay", True, "unpaid"), ("Casual Leave", True, "unpaid"),
    ("Compensatory Off", False, "other"), ("Study Leave", False, "other"), ("", False, "other"),
])
def test_leave_type_category_heuristic(name, is_lwp, expected):
    from asoud_erp.services.request_lookup import leave_category_for

    assert leave_category_for(name, is_lwp) == expected
