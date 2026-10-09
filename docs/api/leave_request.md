# Leave requests — `asoud_erp.api.v1.leave_request`

Balance panel and live preview of the leave request form (template `leave` of the
[request templates](request_templates.md)). Both methods act for the **active Employee of the
session user in `company`**; there is no `employee` argument. A company the user does not belong
to gives `PermissionError`, a company user without an active Employee gives `EMPLOYEE_NOT_FOUND`.
Names are read-only for the offline layer (`get_*`, `preview_*`).

| Method | HTTP | Purpose |
| --- | --- | --- |
| `get_leave_balance(company, date?)` | GET | balance per category and Leave Type, hourly leave deducted |
| `preview_leave_request(company, leave_type, request_kind, start_date?, end_date?, leave_date?, start_time?, end_time?)` | GET | the leave rules as a dry run; business errors are data |

Dates are ISO (`YYYY-MM-DD`), times `HH:MM` (24 hour).

## `get_leave_balance`

```json
{"employee": "HR-EMP-00001", "as_of": "2026-10-06", "daily_working_hours": 8, "leave_approver": "mgr@x",
 "categories": [{"category": "annual", "label": "سالانه", "remaining_days": 12.5,
                 "available_days": 12.0, "pending_days": 0.5}],
 "leave_types": [{"leave_type": "Casual Leave", "category": "annual", "label": "سالانه", "is_lwp": 0,
                  "has_allocation": true, "total_leaves": 26.0, "leaves_taken": 13.0, "hourly_taken": 0.5,
                  "leaves_pending": 0.5, "remaining": 12.5, "available": 12.0}]}
```

* `leave_approver` is the user of the requester's direct manager (`reports_to`), who approves the
  seeded workflow; without one it is the HRMS leave approver.
* `categories` always lists `annual`, `sick`, `other` (zeros when empty) and sums the non-LWP Leave
  Types of each category. `unpaid` is not part of the panel. The category of a Leave Type is
  `Leave Type.asoud_leave_category`; only Leave Types with a category appear.
* Per Leave Type (HRMS `get_leave_details` is the *native* source, all numbers rounded to 3 decimals):

  ```
  hourly_taken = -SUM(Leave Ledger Entry.leaves) where transaction_type = "ASOUD Workflow Request",
                 docstatus = 1, from_date inside the allocation period
  inflight     = sum of day_equivalent of Running leave requests dated inside the allocation period
  remaining    = native.remaining_leaves - hourly_taken
  pending      = native.leaves_pending_approval + inflight          (key: leaves_pending)
  available    = remaining - pending
  ```

  For leave-without-pay types `remaining` and `available` are `null`. A Leave Type without allocation has
  `has_allocation: false` and zeros. `leaves_taken` is HRMS' own figure and does not include hourly leave.

## `preview_leave_request`

Runs the same rules as the template `validate` (one implementation, `leave_rules.evaluate_leave`) and
never raises for business errors, because the mobile client drops server messages from exceptions.

```json
{"valid": false,
 "errors": [{"code": "INSUFFICIENT_LEAVE_BALANCE", "field": "leave_type", "message": "مانده مرخصی کافی نیست."}],
 "duration": {"unit": "hour", "days": null, "hours": 4.0, "day_equivalent": 0.5},
 "balance": {"leave_type": "Casual Leave", "remaining_before": 12.5, "requested_days": 0.5,
             "remaining_after": 12.0, "available_after": 11.5},
 "holidays_excluded": 0}
```

* Incomplete input (a form being typed into) gives `valid: false`, `errors: []`, `duration: null`.
* An unknown Leave Type or a malformed date is not a business error and raises `ValidationError`.
* `message` is Persian for every code of the contract. Daily previews also dry-run HRMS
  `Leave Application.validate` on an unsaved document (status `Open`; messages queued by HRMS are
  discarded). HRMS rules without a contract code (maximum consecutive days, block dates, applicable
  after, outside the allocation period, attendance already marked, ...) come back as
  `LEAVE_RULE_VIOLATION` with the HRMS text.

### Rules and error codes

| Code | Rule |
| --- | --- |
| `INVALID_DATE_RANGE` | daily: end before start |
| `INVALID_TIME_RANGE` | hourly: end not after start, a malformed `HH:MM`, or less than 15 minutes |
| `LEAVE_ALL_HOLIDAYS` | daily: HRMS `get_number_of_leave_days` gives 0 or less |
| `HOURLY_EXCEEDS_DAY` | hourly: longer than `Company.asoud_daily_working_hours`, or the hourly total of that date would be |
| `HOURLY_ON_HOLIDAY` | hourly on a holiday of the employee's list (unless the Leave Type includes holidays) |
| `LEAVE_OVERLAP` | an in-flight request, an approved request without a finished native document, an approved hourly request or a Leave Application overlaps the date or time range |
| `DATE_IN_PAST` | `HR Settings.restrict_backdated_leave_application` is on and the date is past (on edit only when the date changed) |
| `INSUFFICIENT_LEAVE_BALANCE` | `day_equivalent > available` for a Leave Type that is neither LWP nor `allow_negative` |
| `LEAVE_RULE_VIOLATION` | any other HRMS validation of the daily dry run |
| `REQUESTER_MISMATCH` | `requester` is not the signed-in user (create only, not preview) |

Duration maths (`services/leave_hours.py`, exact decimals, half-up rounding):

```
hours          = round(minutes / 60, 2)
day_equivalent = round(hours / daily_working_hours, 4)      4 h at 8 h/day = 0.5, 1.5 h = 0.1875
ledger leaves  = -round(hours / daily_working_hours, 6)
```

## What approval creates

Created by the post-approval hook (`services/request_native_documents.py`), never by an endpoint:

* **Daily**: a submitted Leave Application, status `Approved`, `asoud_request` set, `leave_approver` the
  final approver. HRMS validates and posts it as usual (balance, overlap, block days, Attendance «On
  Leave», Leave Ledger Entry).
* **Hourly**: a submitted Leave Ledger Entry (`transaction_type = "ASOUD Workflow Request"`,
  `transaction_name` the request, `leaves = -hours / daily hours`, `from_date = to_date` the leave date).
  Before posting, the balance is checked again (`day_equivalent <= remaining`); otherwise the request stays
  approved with `native_status = Failed` and `INSUFFICIENT_LEAVE_BALANCE`.
* Both are idempotent (lookup by `asoud_request` or by `(transaction_type, transaction_name)`), run in a
  savepoint and never un-approve a request. `workflow_request.create_native_document(name)` retries a
  `Failed` one.
* The Leave Application validate hook (`leave_balance.validate_leave_application`) refuses a full-day leave
  that would spend what hourly leave took (`consumption - hourly_taken < total_leave_days`).

HRMS code that checks employee access (`get_leave_details`, `get_leave_balance_on`) runs as `Administrator`
during the post-approval step, because the approver is the direct manager and not necessarily the
Employee's HRMS leave approver.

## `hr_self_service.get_my_leave_summary(date?)`

Every key of a `balances[]` row is unchanged. Rows gain `hourly_leaves_taken`, `available_leaves`
(`remaining_leaves - hourly - pending`) and `category`.

## Known limitations

* HRMS standard reports, Leave Ledger reports and payroll LWP deduction ignore hourly leave: HRMS only
  counts `Leave Application` and `Leave Encashment` ledger entries (`get_leaves_for_period`).
* Cancelling an approved hourly leave is manual: delete the Leave Ledger Entry rows with
  `transaction_type = "ASOUD Workflow Request"` and `transaction_name = <request>` (this mirrors HRMS
  `delete_ledger_entry`).
* Stored hours have two decimals: a time pair that is not a multiple of 3 minutes loses a fraction of a
  minute in `day_equivalent` (20 minutes is 0.33 h). Quarter-hour times are exact.
* A request edited through the cartable after a Return keeps its in-flight reservation computed from the
  stored `duration`; the next `update_request` or approval recomputes it.
