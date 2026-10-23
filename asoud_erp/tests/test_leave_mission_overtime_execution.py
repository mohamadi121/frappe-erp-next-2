from datetime import date

import pytest

from asoud_erp.services.form_execution import EXECUTORS, leave_application, mission, overtime
from asoud_erp.services.form_execution.parameters import collect_parameters
from asoud_erp.services.form_execution.schema import validate_execution

TODAY = date.today().isoformat()
CTX = {"company": "شرکت", "employee": "EMP-1", "user": "u@example.com", "request_name": "REQ-1", "today": TODAY}


def test_registry_and_labels():
    assert EXECUTORS["leave_application"] is leave_application
    assert EXECUTORS["mission"] is mission
    assert EXECUTORS["overtime"] is overtime
    assert (leave_application.LABEL, mission.LABEL, overtime.LABEL) == (
        "درخواست مرخصی", "درخواست مأموریت", "درخواست اضافه‌کار")


def test_leave_type_is_a_scoped_source_without_employee_filter():
    form_schema = pytest.importorskip("frappe") and pytest.importorskip("asoud_erp.services.form_schema")
    SOURCES, SCOPED_SOURCES, scope_filters = (
        form_schema.SOURCES, form_schema.SCOPED_SOURCES, form_schema.scope_filters)
    assert "Leave Type" in SOURCES and "Leave Type" in SCOPED_SOURCES
    assert scope_filters("Leave Type", "شرکت", None) == {"is_optional_leave": 0}


def test_parameter_names_and_required_flags():
    def required(module):
        return {k for k, v in module.PARAMETERS.items() if v["required"]}

    assert required(leave_application) == {"leave_type", "from_date", "to_date"}
    assert set(leave_application.PARAMETERS) == {"leave_type", "from_date", "to_date", "half_day",
                                                 "half_day_date", "description"}
    assert required(mission) == {"from_date", "to_date", "destination", "purpose"}
    assert set(mission.PARAMETERS) == {"from_date", "to_date", "half_day", "half_day_date", "shift",
                                       "destination", "purpose", "notes"}
    assert "include_holidays" not in mission.PARAMETERS
    assert required(overtime) == {"work_date", "start_time", "end_time", "purpose"}


def test_execution_kind_validates_a_complete_mapping():
    schema = {"kind": "Request", "execution": {"kind": "overtime"}, "sections": [{"fields": [
        {"key": "d", "type": "Date", "execution_key": "work_date"},
        {"key": "s", "type": "Time", "execution_key": "start_time"},
        {"key": "e", "type": "Time", "execution_key": "end_time"},
        {"key": "p", "type": "LongText", "execution_key": "purpose"}]}]}
    validate_execution(schema)
    schema["sections"][0]["fields"].pop()
    with pytest.raises(ValueError):
        validate_execution(schema)


def leave(**extra):
    return {"leave_type": "Casual Leave", "from_date": "2026-11-01", "to_date": "2026-11-03", **extra}


def test_leave_build_maps_native_fields():
    payload = leave_application.build(leave(description=" سفر "), {**CTX, "leave_approver": "boss@example.com"})
    assert payload == {
        "doctype": "Leave Application", "employee": "EMP-1", "company": "شرکت", "leave_type": "Casual Leave",
        "from_date": "2026-11-01", "to_date": "2026-11-03", "half_day": 0, "half_day_date": None,
        "description": "سفر", "posting_date": TODAY, "leave_approver": "boss@example.com",
        "status": "Approved", "docstatus": 0}


def test_leave_half_day_rules():
    one = leave_application.build(leave(to_date="2026-11-01", half_day=True), CTX)
    assert (one["half_day"], one["half_day_date"]) == (1, "2026-11-01")
    many = leave_application.build(leave(half_day=True, half_day_date="2026-11-02"), CTX)
    assert many["half_day_date"] == "2026-11-02"
    full = leave_application.build(leave(half_day=False, half_day_date="2026-11-02"), CTX)
    assert (full["half_day"], full["half_day_date"]) == (0, None)
    with pytest.raises(ValueError, match="تاریخ نیم‌روز باید در بازه درخواست باشد."):
        leave_application.build(leave(half_day=True, half_day_date="2026-11-09"), CTX)
    with pytest.raises(ValueError, match="تاریخ نیم‌روز را مشخص کنید."):
        leave_application.build(leave(half_day=True), CTX)


@pytest.mark.parametrize("params,message", [
    (leave(to_date="2026-10-31"), "تاریخ پایان نباید پیش از تاریخ شروع باشد."),
    (leave(leave_type=" "), "نوع مرخصی را انتخاب کنید."),
    (leave(from_date=None), "تاریخ شروع مرخصی معتبر نیست."),
    (leave(to_date="1405/08/01"), "تاریخ پایان مرخصی معتبر نیست."),
    (leave(half_day="yes"), "گزینه نیم‌روز باید بله یا خیر باشد."),
    (leave(description=5), "توضیح مرخصی باید متن باشد."),
    (leave(description="ا" * 2001), "توضیح مرخصی حداکثر ۲۰۰۰ نویسه است."),
])
def test_leave_invalid_input(params, message):
    with pytest.raises(ValueError, match=message):
        leave_application.build(params, CTX)


def test_leave_requires_company_and_employee():
    with pytest.raises(ValueError, match="پرونده پرسنلی درخواست‌دهنده ثبت نشده است."):
        leave_application.build(leave(), {**CTX, "employee": ""})
    with pytest.raises(ValueError, match="شرکت درخواست مشخص نشده است."):
        leave_application.build(leave(), {**CTX, "company": None})


def trip(**extra):
    return {"from_date": "2026-11-01", "to_date": "2026-11-02", "destination": " تبریز ",
            "purpose": "بازدید", **extra}


def test_mission_build_fixed_reason_and_explanation():
    payload = mission.build(trip(notes="هماهنگی", shift="Day"), CTX)
    assert payload == {
        "doctype": "Attendance Request", "employee": "EMP-1", "company": "شرکت", "from_date": "2026-11-01",
        "to_date": "2026-11-02", "half_day": 0, "half_day_date": None, "reason": "On Duty",
        "include_holidays": 0, "shift": "Day", "docstatus": 0,
        "explanation": "مقصد: تبریز\nهدف: بازدید\nتوضیحات: هماهنگی"}
    assert mission.build(trip(include_holidays=True, reason="Work From Home"), CTX)["reason"] == "On Duty"
    assert mission.build(trip(include_holidays=True), CTX)["include_holidays"] == 0
    assert mission.build(trip(), CTX)["explanation"] == "مقصد: تبریز\nهدف: بازدید"
    assert mission.build(trip(shift=" "), CTX)["shift"] is None


@pytest.mark.parametrize("params,message", [
    (trip(destination=" "), "مقصد و هدف مأموریت را وارد کنید."),
    (trip(purpose=None), "مقصد و هدف مأموریت را وارد کنید."),
    (trip(destination="ا" * 251), "مقصد مأموریت حداکثر ۲۵۰ نویسه است."),
    (trip(purpose="ا" * 2001), "هدف مأموریت حداکثر ۲۰۰۰ نویسه است."),
    (trip(notes="ا" * 2001), "توضیحات مأموریت حداکثر ۲۰۰۰ نویسه است."),
    (trip(to_date="2026-10-31"), "تاریخ پایان نباید پیش از تاریخ شروع باشد."),
    (trip(half_day=True, half_day_date="2026-12-01"), "تاریخ نیم‌روز باید در بازه درخواست باشد."),
    (trip(from_date="x"), "تاریخ شروع مأموریت معتبر نیست."),
])
def test_mission_invalid_input(params, message):
    with pytest.raises(ValueError, match=message):
        mission.build(params, CTX)


def test_mission_conflicts_only_on_boundary_holidays_and_working_days():
    holidays = {"2026-11-03", "2027-01-01"}
    # a holiday inside the range is skipped by HRMS, not a conflict
    assert mission.conflict_days("2026-11-01", "2026-11-05", holidays, set(), set()) == []
    # but not as the first or the last day
    assert mission.conflict_days("2026-11-03", "2026-11-05", holidays, set(), set()) == ["2026-11-03"]
    assert mission.conflict_days("2026-11-01", "2026-11-03", holidays, set(), set()) == ["2026-11-03"]
    # attendance and leave matter on working days only, out-of-range rows are ignored
    found = mission.conflict_days("2026-11-01", "2026-11-04", holidays, {"2026-11-02", "2026-11-03"},
                                  {"2026-10-30", "2026-11-04"})
    assert found == ["2026-11-02", "2026-11-04"]
    assert mission.conflict_days("2026-11-01", "2026-11-04", set(), set(), set(), {"2026-11-03"}) == ["2026-11-03"]
    reason = mission.review_reason(["2026-11-02", "2026-11-03"])
    assert reason.startswith("نیاز به اقدام HR؛ بازه مأموریت با تعطیلی، مرخصی یا حضور ثبت‌شده تعارض دارد")
    assert "۱۴۰۵/۰۸/۱۱" in reason and "۱۴۰۵/۰۸/۱۲" in reason


def overtime_params(**extra):
    return {"work_date": "2026-11-01", "start_time": "17:00", "end_time": "20:30", "purpose": "پروژه", **extra}


def test_overtime_same_day_reason_carries_date_and_hours():
    result = overtime.build(overtime_params(), CTX)
    assert list(result) == ["needs_review"]
    assert result["needs_review"] == (
        "نیاز به اقدام HR؛ اضافه‌کار تأییدشده در تاریخ ۱۴۰۵/۰۸/۱۰ از ساعت ۱۷:۰۰ تا ساعت ۲۰:۳۰ "
        "به مدت ۳ ساعت و ۳۰ دقیقه است؛ ثبت کارکرد و محاسبه مالی باید توسط منابع انسانی انجام شود.")


def test_overtime_across_midnight_and_seconds():
    reason = overtime.build(overtime_params(start_time="22:00:00", end_time="01:15:00",
                                            end_time__next_day=True), CTX)["needs_review"]
    assert "از ساعت ۲۲:۰۰ تا ساعت ۰۱:۱۵ روز بعد به مدت ۳ ساعت و ۱۵ دقیقه" in reason
    full_day = overtime.build(overtime_params(start_time="09:00", end_time="09:00", end_time__next_day=True), CTX)
    assert "به مدت ۲۴ ساعت است" in full_day["needs_review"]


def test_overtime_whole_hours_have_no_minutes_part():
    reason = overtime.build(overtime_params(end_time="19:00"), CTX)["needs_review"]
    assert "به مدت ۲ ساعت است" in reason


@pytest.mark.parametrize("params,message", [
    (overtime_params(end_time="17:00"), "ساعت پایان باید پس از ساعت شروع باشد."),
    (overtime_params(end_time="16:00"), "ساعت پایان باید پس از ساعت شروع باشد."),
    (overtime_params(start_time="10:00", end_time="09:00", start_time__next_day=True),
     "ساعت پایان باید پس از ساعت شروع باشد."),
    (overtime_params(start_time="08:00", end_time="09:00", end_time__next_day=True),
     "مدت اضافه‌کار باید بیش از صفر و حداکثر ۲۴ ساعت باشد."),
    (overtime_params(start_time="08:00", end_time="09:00", end_time__next_day="x"), "گزینه روز بعد معتبر نیست."),
    (overtime_params(start_time="25:00"), "ساعت شروع معتبر نیست."),
    (overtime_params(end_time=None), "ساعت پایان معتبر نیست."),
    (overtime_params(work_date="2026-13-01"), "تاریخ اضافه‌کار معتبر نیست."),
    (overtime_params(purpose=" "), "شرح کار اضافه‌کار را وارد کنید."),
])
def test_overtime_invalid_input(params, message):
    with pytest.raises(ValueError, match=message):
        overtime.build(params, CTX)


def test_overtime_needs_requester_and_company():
    with pytest.raises(ValueError, match="پرونده پرسنلی درخواست‌دهنده ثبت نشده است."):
        overtime.build(overtime_params(), {**CTX, "employee": None})


def test_collect_parameters_passes_next_day_companion_of_mapped_time_field():
    fields = [{"key": "from", "type": "Time", "execution_key": "end_time", "next_day_allowed": True},
              {"key": "plain", "type": "Time", "execution_key": "start_time"}]
    values = {"from": "01:00", "from__next_day": True, "plain": "22:00", "plain__next_day": True}
    params = collect_parameters(fields, values, [])
    assert params == {"end_time": "01:00", "end_time__next_day": True, "start_time": "22:00",
                      "start_time__next_day": False}


def test_stage_time_without_toggle_resets_the_day_marker():
    fields = [{"key": "t", "type": "Time", "execution_key": "end_time", "next_day_allowed": True}]
    task = {"name": "T1", "status": "Completed", "completed_on": "2026-11-01 10:00:00",
            "fields": [{"key": "approved_end", "type": "Time", "execution_key": "end_time"}],
            "values": {"approved_end": "23:00"}}
    params = collect_parameters(fields, {"t": "01:00", "t__next_day": True}, [task])
    assert (params["end_time"], params["end_time__next_day"]) == ("23:00", False)


def test_stage_response_overrides_time_and_its_companion():
    fields = [{"key": "t", "type": "Time", "execution_key": "end_time", "next_day_allowed": True}]
    task = {"name": "T1", "status": "Completed", "completed_on": "2026-11-01 10:00:00",
            "fields": [{"key": "approved_end", "type": "Time", "execution_key": "end_time",
                        "next_day_allowed": True}],
            "values": {"approved_end": "23:00", "approved_end__next_day": False}}
    params = collect_parameters(fields, {"t": "01:00", "t__next_day": True}, [task])
    assert params["end_time"] == "23:00" and params["end_time__next_day"] is False
