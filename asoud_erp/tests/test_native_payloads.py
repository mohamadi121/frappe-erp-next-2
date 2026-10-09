"""Pure tests for the native document payload builders (CONTRACT 4.12)."""

import pytest

from asoud_erp.services import native_payloads as np

ROWS = [
    {"item_code": "ICU-MON-01", "item_name": "مانیتور", "qty": 2, "uom": "Box", "stock_uom": "Nos",
     "conversion_factor": 6, "stock_qty": 12, "description": "شرح ردیف", "note": "یادداشت", "attachment": None},
    {"item_code": "SVC-1", "qty": 1, "uom": None, "stock_uom": "Nos", "conversion_factor": 1,
     "description": "", "note": ""},
]


def purchase_values(**extra):
    return {"needed_date": "2026-10-20", "project": "PROJ-1", "cost_center": "Main - WP",
            "priority": "High", "items": ROWS, **extra}


def build(template, values, **kwargs):
    return np.material_request_payload(
        template_key=template, request_name="PR-1405-0001", company="Wind Power LLC",
        creation_date="2026-10-06", values=values, **kwargs)


def test_purchase_payload():
    payload = build("purchase", purchase_values(), default_warehouse="Stores - WP")
    assert payload["doctype"] == "Material Request"
    assert payload["material_request_type"] == "Purchase"
    assert payload["company"] == "Wind Power LLC"
    assert payload["transaction_date"] == "2026-10-06"
    assert payload["schedule_date"] == "2026-10-20"
    assert payload["asoud_request"] == "PR-1405-0001"
    assert payload["set_warehouse"] == "Stores - WP"
    first, second = payload["items"]
    assert first == {
        "item_code": "ICU-MON-01", "qty": 2, "uom": "Box", "stock_uom": "Nos", "conversion_factor": 6,
        "schedule_date": "2026-10-20", "description": "شرح ردیف\nیادداشت", "warehouse": "Stores - WP",
        "project": "PROJ-1", "cost_center": "Main - WP"}
    # No description or note: the key is omitted so ERPNext fills the item description; uom falls back.
    assert "description" not in second
    assert second["uom"] == "Nos"
    assert second["project"] == "PROJ-1" and second["cost_center"] == "Main - WP"


def test_purchase_without_default_warehouse_or_project():
    payload = build("purchase", purchase_values(project=None, cost_center=""))
    assert "set_warehouse" not in payload
    for row in payload["items"]:
        assert not {"warehouse", "project", "cost_center"} & set(row)


def test_row_description_joins_non_empty_parts():
    assert np.row_description({"description": " a ", "note": " b "}) == "a\nb"
    assert np.row_description({"description": "a"}) == "a"
    assert np.row_description({"note": "b"}) == "b"
    assert np.row_description({}) == ""


SUPPLY_TABLE = [
    # supply_method, delivery_location, expected type, header warehouse, row warehouse
    ("Purchase", "warehouse:Stores - WP", "Purchase", "Stores - WP", "Stores - WP"),
    ("Purchase", "branch:Tehran", "Purchase", "Default - WP", "Default - WP"),
    ("Warehouse", "warehouse:Stores - WP", "Material Issue", None, "Default - WP"),
    ("Warehouse", "department:Sales - WP", "Material Issue", None, "Default - WP"),
    ("Transfer", "warehouse:Stores - WP", "Material Transfer", "Stores - WP", "Stores - WP"),
]


@pytest.mark.parametrize("method,delivery,request_type,header,row", SUPPLY_TABLE)
def test_supply_mapping(method, delivery, request_type, header, row):
    values = {"supply_method": method, "delivery_location": delivery, "needed_date": "2026-10-20",
              "items": [ROWS[1]]}
    payload = build("supply", values, default_warehouse="Default - WP")
    assert payload["material_request_type"] == request_type
    assert payload.get("set_warehouse") == header
    assert payload["items"][0].get("warehouse") == row
    assert "set_from_warehouse" not in payload
    assert not {"project", "cost_center"} & set(payload["items"][0])


@pytest.mark.parametrize("method", ["Contract", "Unspecified", "", None, "Other"])
def test_supply_without_native_document(method):
    values = {"supply_method": method, "delivery_location": "warehouse:Stores - WP", "items": [ROWS[1]]}
    assert build("supply", values) is None


def test_supply_mapping_table_is_exactly_the_contract():
    assert np.SUPPLY_MATERIAL_REQUEST_TYPES == {
        "Purchase": "Purchase", "Warehouse": "Material Issue", "Transfer": "Material Transfer",
        "Contract": None, "Unspecified": None}


def test_unknown_template_is_refused():
    with pytest.raises(ValueError):
        build("leave", {"items": []})


@pytest.mark.parametrize("value,expected", [
    ("warehouse:Stores - WP", ("warehouse", "Stores - WP")),
    ("branch:تهران", ("branch", "تهران")),
    ("department:Sales: East - WP", ("department", "Sales: East - WP")),
    ("room:1", None), ("warehouse:", None), ("Stores - WP", None), ("", None), (None, None), (5, None),
])
def test_parse_delivery_location(value, expected):
    assert np.parse_delivery_location(value) == expected


def test_daily_leave_application_payload():
    payload = np.leave_application_payload(
        request_name="LV-1405-0001", employee="HR-EMP-1", company="Wind Power LLC", creation_date="2026-10-06",
        approver="mgr@x", values={"leave_type": "Casual Leave", "start_date": "2026-10-10",
                                  "end_date": "2026-10-12", "reason": "سفر"})
    assert payload == {
        "doctype": "Leave Application", "employee": "HR-EMP-1", "company": "Wind Power LLC",
        "leave_type": "Casual Leave", "from_date": "2026-10-10", "to_date": "2026-10-12", "half_day": 0,
        "description": "سفر", "posting_date": "2026-10-06", "leave_approver": "mgr@x", "status": "Approved",
        "asoud_request": "LV-1405-0001"}


def hourly_values(hours=4.0, leave_type="Casual Leave"):
    return {"leave_type": leave_type, "request_kind": "Hourly", "leave_date": "2026-10-10",
            "start_time": "09:00", "end_time": "13:00",
            "duration": {"unit": "hour", "days": None, "hours": hours, "day_equivalent": hours / 8}}


def ledger(values, daily_hours=8, **kwargs):
    return np.leave_ledger_payload(
        request_name="LV-1405-0002", employee="HR-EMP-1", employee_name="سارا", company="Wind Power LLC",
        values=values, daily_hours=daily_hours, is_lwp=False, holiday_list="Holidays", **kwargs)


def test_hourly_ledger_entry_four_hours():
    payload = ledger(hourly_values(4.0))
    assert payload["leaves"] == -0.5
    assert payload["transaction_type"] == "ASOUD Workflow Request"
    assert payload["transaction_name"] == "LV-1405-0002"
    assert payload["doctype"] == "Leave Ledger Entry"
    assert (payload["from_date"], payload["to_date"]) == ("2026-10-10", "2026-10-10")
    assert (payload["is_carry_forward"], payload["is_expired"], payload["is_lwp"]) == (0, 0, 0)
    assert payload["holiday_list"] == "Holidays"
    assert payload["employee_name"] == "سارا" and payload["company"] == "Wind Power LLC"


def test_hourly_ledger_entry_keeps_six_decimals_and_company_hours():
    assert ledger(hourly_values(1.5))["leaves"] == -0.1875
    assert ledger(hourly_values(4.0), daily_hours=7.5)["leaves"] == -0.533333


def test_lwp_flag_and_missing_holiday_list():
    payload = np.leave_ledger_payload(
        request_name="LV-1405-0003", employee="E", employee_name="x", company="C",
        values=hourly_values(2.0), daily_hours=8, is_lwp=True, holiday_list=None)
    assert payload["is_lwp"] == 1 and payload["holiday_list"] == ""
    assert payload["leaves"] == -0.25
