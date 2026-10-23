from datetime import date, timedelta

import pytest

from asoud_erp.services.form_execution import EXECUTORS
from asoud_erp.services.form_execution import attendance_correction as execution

TODAY = date.today().isoformat()
CTX = {"company": "شرکت", "employee": "EMP-1", "user": "employee@example.com",
       "request_name": "REQ-1", "today": TODAY}


def params(**extra):
    return {"date": TODAY, "kind": "missing_entry", "in_time": "08:15", **extra}


def test_registry_and_parameter_contract():
    assert EXECUTORS["attendance_correction"] is execution
    assert execution.KIND == "attendance_correction"
    assert execution.LABEL == "اصلاح تردد"
    assert execution.PARAMETERS == {
        "date": {"label": "تاریخ تردد", "types": ["Date"], "required": True},
        "kind": {"label": "نوع اصلاح", "types": ["Select"], "required": True},
        "in_time": {"label": "ساعت ورود پیشنهادی", "types": ["Time"], "required": False},
        "out_time": {"label": "ساعت خروج پیشنهادی", "types": ["Time"], "required": False},
        "reason": {"label": "دلیل اصلاح تردد", "types": ["LongText"], "required": False},
    }


@pytest.mark.parametrize("kind,key,log_type", [
    ("missing_entry", "in_time", "IN"), ("missing_exit", "out_time", "OUT"),
])
@pytest.mark.parametrize("clock,expected", [("08:15", "08:15:00"), ("23:59:07", "23:59:07")])
@pytest.mark.parametrize("next_day", [False, True])
def test_build_punch(kind, key, log_type, clock, expected, next_day):
    values = {"date": TODAY, "kind": kind, key: clock, f"{key}__next_day": next_day,
              "reason": "فراموشی ثبت"}
    original = values.copy()
    context = CTX.copy()
    day = date.fromisoformat(TODAY) + timedelta(days=int(next_day))
    assert execution.build(values, context) == {
        "doctype": "Employee Checkin", "employee": "EMP-1", "log_type": log_type,
        "time": f"{day.isoformat()} {expected}", "docstatus": 0,
    }
    assert values == original
    assert context == CTX


@pytest.mark.parametrize("key", ["reason", "out_time", "out_time__next_day", "in_time__next_day"])
@pytest.mark.parametrize("empty", [None, ""])
def test_empty_optional_values(key, empty):
    assert execution.build(params(**{key: empty}), CTX)["time"] == f"{TODAY} 08:15:00"


@pytest.mark.parametrize("kind,key,unused", [
    ("missing_entry", "in_time", "out_time"), ("missing_exit", "out_time", "in_time"),
])
@pytest.mark.parametrize("value", [None, ""])
def test_irrelevant_time_can_be_absent_or_empty(kind, key, unused, value):
    values = {"date": TODAY, "kind": kind, key: "08:00"}
    expected = execution.build(values, CTX)
    assert execution.build({**values, unused: value}, CTX) == expected


def test_missing_optional_values_and_overnight_exit():
    assert execution.build(params(), CTX)["log_type"] == "IN"
    assert execution.build(params(kind="missing_exit", out_time="01:00", out_time__next_day=True), CTX) == {
        "doctype": "Employee Checkin", "employee": "EMP-1", "log_type": "OUT",
        "time": f"{(date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()} 01:00:00",
        "docstatus": 0,
    }


@pytest.mark.parametrize("kind,reason", [
    ("correct_recorded_time", "نیاز به اقدام HR؛ اصلاح ساعت ثبت‌شده باید با بررسی رکورد اصلی انجام شود."),
    ("other", "نیاز به اقدام HR؛ نوع عملیات برای سایر موارد مشخص نشده است."),
])
def test_review_kinds_have_no_native_payload(kind, reason):
    with pytest.raises(ValueError) as error:
        execution.build({"date": TODAY, "kind": kind}, CTX)
    assert str(error.value) == reason


@pytest.mark.parametrize("key,message", [
    ("date", "تاریخ تردد معتبر نیست."), ("kind", "نوع اصلاح تردد معتبر نیست."),
    ("in_time", "ساعت ورود پیشنهادی معتبر نیست."),
])
@pytest.mark.parametrize("value", [None, "", [], {}, True, 12])
def test_missing_empty_or_wrong_required_value(key, message, value):
    with pytest.raises(ValueError) as error:
        execution.build(params(**{key: value}), CTX)
    assert str(error.value) == message


@pytest.mark.parametrize("key,message", [
    ("date", "تاریخ تردد معتبر نیست."), ("kind", "نوع اصلاح تردد معتبر نیست."),
    ("in_time", "ساعت ورود پیشنهادی معتبر نیست."),
])
def test_absent_required_parameter(key, message):
    values = params()
    del values[key]
    with pytest.raises(ValueError) as error:
        execution.build(values, CTX)
    assert str(error.value) == message


@pytest.mark.parametrize("value", [None, "", "25:00", "09:60", "1:00", "08:00+03:30", "08:00:00.5", [], 1])
def test_exit_requires_valid_exit_time(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(kind="missing_exit", out_time=value), CTX)
    assert str(error.value) == "ساعت خروج پیشنهادی معتبر نیست."


@pytest.mark.parametrize("value", ["2025-02-30", "20251001", "1405/01/01", "yesterday"])
def test_invalid_calendar_date(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(date=value), CTX)
    assert str(error.value) == "تاریخ تردد معتبر نیست."


@pytest.mark.parametrize("value", ["missing_check_in", "mission", "missing_check_out", "unknown"])
def test_unknown_kind(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(kind=value), CTX)
    assert str(error.value) == "نوع اصلاح تردد معتبر نیست."


@pytest.mark.parametrize("kind,key", [("missing_entry", "in_time"), ("missing_exit", "out_time")])
@pytest.mark.parametrize("value", ["true", "false", 1, [], {}])
def test_invalid_next_day_flag(kind, key, value):
    with pytest.raises(ValueError) as error:
        execution.build(params(kind=kind, **{key: "08:00", f"{key}__next_day": value}), CTX)
    assert str(error.value) == "گزینه روز بعد معتبر نیست."


@pytest.mark.parametrize("value", [1, True, [], {}])
def test_reason_must_be_optional_text(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(reason=value), CTX)
    assert str(error.value) == "دلیل اصلاح تردد باید متن باشد."


@pytest.mark.parametrize("key,message", [
    ("company", "شرکت درخواست مشخص نشده است."),
    ("employee", "پرونده پرسنلی درخواست‌دهنده ثبت نشده است."),
])
@pytest.mark.parametrize("value", [None, "", "  ", [], 1])
def test_missing_context(key, message, value):
    with pytest.raises(ValueError) as error:
        execution.build(params(), {**CTX, key: value})
    assert str(error.value) == message


@pytest.mark.parametrize("value", [None, [], "", 1])
def test_invalid_params_shape(value):
    with pytest.raises(ValueError) as error:
        execution.build(value, CTX)
    assert str(error.value) == "اطلاعات اصلاح تردد معتبر نیست."


@pytest.mark.parametrize("value", [None, [], "", 1])
def test_invalid_context_shape(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(), value)
    assert str(error.value) == "اطلاعات اصلاح تردد معتبر نیست."


def test_next_day_cannot_overflow_calendar():
    with pytest.raises(ValueError) as error:
        execution.build(params(date=date.max.isoformat(), in_time__next_day=True), CTX)
    assert str(error.value) == "تاریخ تردد معتبر نیست."


@pytest.mark.parametrize("value", ["24:00", "08:61", "08:00Z", "08:00:01.5"])
def test_invalid_entry_clock(value):
    with pytest.raises(ValueError) as error:
        execution.build(params(in_time=value), CTX)
    assert str(error.value) == "ساعت ورود پیشنهادی معتبر نیست."


@pytest.mark.parametrize("kind", ["correct_recorded_time", "other"])
def test_invalid_review_data_still_fails_validation(kind):
    with pytest.raises(ValueError) as error:
        execution.build(params(kind=kind, date="not a date"), CTX)
    assert str(error.value) == "تاریخ تردد معتبر نیست."
