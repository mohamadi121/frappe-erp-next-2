"""Pure tests for the leave balance formulas (CONTRACT 4.11, 4.12 overlay)."""

from asoud_erp.services import leave_hours as lh

NATIVE = {"total_leaves": 26, "expired_leaves": 0, "leaves_taken": 13.5,
          "leaves_pending_approval": 0.5, "remaining_leaves": 12.5}


def test_remaining_pending_available_follow_the_contract():
    balance = lh.type_balance(native=NATIVE, hourly_taken=0.625, inflight=1.25, is_lwp=False)
    assert balance["remaining"] == 11.875          # 12.5 - 0.625
    assert balance["leaves_pending"] == 1.75       # 0.5 + 1.25
    assert balance["available"] == 10.125          # 11.875 - 1.75
    assert balance["hourly_taken"] == 0.625
    assert balance["total_leaves"] == 26.0
    assert balance["leaves_taken"] == 13.5         # native value, untouched
    assert balance["has_allocation"] is True


def test_without_hourly_or_inflight_the_native_numbers_stand():
    balance = lh.type_balance(native=NATIVE, hourly_taken=0, inflight=0, is_lwp=False)
    assert (balance["remaining"], balance["leaves_pending"], balance["available"]) == (12.5, 0.5, 12.0)


def test_lwp_has_no_remaining_or_available():
    balance = lh.type_balance(native=None, hourly_taken=0, inflight=2, is_lwp=True)
    assert balance["remaining"] is None and balance["available"] is None
    assert balance["leaves_pending"] == 2.0


def test_leave_type_without_allocation_is_zero():
    balance = lh.type_balance(native=None, hourly_taken=0, inflight=0, is_lwp=False)
    assert balance["has_allocation"] is False
    assert (balance["total_leaves"], balance["remaining"], balance["available"]) == (0.0, 0.0, 0.0)


def test_rounding_is_three_decimals_half_up():
    native = {"total_leaves": 10, "leaves_taken": 0, "leaves_pending_approval": 0, "remaining_leaves": 10}
    balance = lh.type_balance(native=native, hourly_taken=0.0625, inflight=0, is_lwp=False)
    assert balance["remaining"] == 9.938   # 9.9375 -> half up
    assert balance["hourly_taken"] == 0.063


def test_category_rows_sum_non_lwp_types_and_skip_unpaid():
    sick = lh.type_balance(native={"remaining_leaves": 8, "leaves_pending_approval": 0}, hourly_taken=0,
                           inflight=0, is_lwp=False)
    annual_a = lh.type_balance(native=NATIVE, hourly_taken=0.625, inflight=0, is_lwp=False)
    annual_b = lh.type_balance(native={"remaining_leaves": 2, "leaves_pending_approval": 0}, hourly_taken=0,
                               inflight=0, is_lwp=False)
    unpaid = lh.type_balance(native=None, hourly_taken=0, inflight=0, is_lwp=True)
    types = [
        {"category": "annual", "is_lwp": 0, **annual_a},
        {"category": "annual", "is_lwp": 0, **annual_b},
        {"category": "sick", "is_lwp": 0, **sick},
        {"category": "unpaid", "is_lwp": 1, **unpaid},
    ]
    rows = {row["category"]: row for row in lh.category_rows(types)}
    assert list(rows) == ["annual", "sick", "other"]
    assert rows["annual"] == {"category": "annual", "label": "سالانه", "remaining_days": 13.875,
                              "available_days": 13.375, "pending_days": 0.5}
    assert rows["sick"]["remaining_days"] == 8.0
    assert rows["other"] == {"category": "other", "label": "سایر", "remaining_days": 0.0,
                             "available_days": 0.0, "pending_days": 0.0}


def test_preview_balance_subtracts_the_requested_days():
    balance = lh.type_balance(native=NATIVE, hourly_taken=0, inflight=0, is_lwp=False)
    preview = lh.preview_balance("Casual Leave", balance, 0.5)
    assert preview == {"leave_type": "Casual Leave", "remaining_before": 12.5, "requested_days": 0.5,
                       "remaining_after": 12.0, "available_after": 11.5}
    lwp = lh.preview_balance("LWP", lh.type_balance(native=None, hourly_taken=0, inflight=0, is_lwp=True), 1)
    assert lwp["remaining_after"] is None and lwp["available_after"] is None


def test_insufficient_checks():
    balance = lh.type_balance(native=NATIVE, hourly_taken=0, inflight=0, is_lwp=False)  # available 12.0
    kwargs = {"is_lwp": False, "allow_negative": False}
    assert not lh.exceeds_available(12.0, balance, **kwargs)
    assert lh.exceeds_available(12.0001, balance, **kwargs)
    assert not lh.exceeds_available(99, balance, is_lwp=True, allow_negative=False)
    assert not lh.exceeds_available(99, balance, is_lwp=False, allow_negative=True)
    # Final approval compares against remaining (12.5), not available (12.0).
    assert not lh.exceeds_remaining(12.5, balance, **kwargs)
    assert lh.exceeds_remaining(12.6, balance, **kwargs)


def test_leave_application_overlay():
    # HRMS says 3 days are consumable, 2.5 were taken hourly: a 1-day leave is refused.
    assert lh.overlay_insufficient(3, 2.5, 1)
    assert not lh.overlay_insufficient(3, 2.5, 0.5)
    assert not lh.overlay_insufficient(3, 0, 3)
    assert lh.overlay_insufficient(3, 0.0625, 3)       # 2.9375 < 3
    assert not lh.overlay_insufficient(10, 4, 5.5)
