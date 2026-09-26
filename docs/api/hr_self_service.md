# HR self-service — `asoud_erp.api.v1.hr_self_service`

Employee requests on HRMS documents. Every method acts for the **active
Employee linked to the session user**; there is no `employee` argument. A user
without an active Employee gets `PermissionError`. HRMS keeps its own rules
(leave balances, holidays, approvers, accounting of advances and claims).

## Leave (مرخصی) — Leave Application

| Method | HTTP | Purpose |
| --- | --- | --- |
| `get_my_leave_summary(date?)` | GET | balances per leave type (HRMS `get_leave_details`), leave approver |
| `get_leave_days(leave_type, from_date, to_date, half_day=0, half_day_date?)` | GET | working days the leave would take (holidays excluded per Leave Type) |
| `create_leave_application(leave_type, from_date, to_date, reason?, half_day=0, half_day_date?)` | POST | an `Open` application addressed to the HRMS leave approver |
| `list_my_leave_applications(limit_start, limit_page_length≤50)` | GET | |
| `cancel_leave_application(name)` | POST | withdraw one's own application while still Open and unsubmitted (status `Cancelled`) |
| `list_leave_approvals()` | GET | open applications where the session user is the leave approver |
| `approve_leave_application(name)` · `reject_leave_application(name, reason?)` | POST | approver (or HR Manager) sets status and submits |

Balance row:
`{"leave_type": "Casual Leave", "total_leaves": 10, "expired_leaves": 0, "leaves_taken": 2, "leaves_pending_approval": 1, "remaining_leaves": 8}`.
The leave approver comes from the Employee (or Department approvers) in HRMS.

## Check-in — Employee Checkin

| Method | HTTP | Purpose |
| --- | --- | --- |
| `create_checkin(log_type, latitude?, longitude?, device_id?)` | POST | `IN` or `OUT` now; HRMS shift rules turn check-ins into Attendance |
| `list_my_checkins(from_date?, to_date?, …)` | GET | newest first |

## Mission (مأموریت) — Travel Request

| Method | HTTP | Purpose |
| --- | --- | --- |
| `mission_options()` | GET | travel types, purposes (`Purpose of Travel`), expense types |
| `create_travel_request(travel_type, purpose_of_travel, itinerary, description?, costings?)` | POST | a draft for the session user's Employee |
| `list_my_travel_requests(…)` | GET | |

`itinerary`: `[{"travel_from", "travel_to", "departure_date", "arrival_date"?, "mode_of_travel"?}]`
(mode ∈ Air, Rail, Bus, Taxi, Car, Other). `costings`:
`[{"expense_type", "total_amount", "comments"?}]`.

## Salary advance (مساعده) — Employee Advance

| Method | HTTP | Purpose |
| --- | --- | --- |
| `create_employee_advance(amount, purpose, posting_date?)` | POST | a draft in company currency; the expense approver submits it |
| `list_my_employee_advances(…)` | GET | with paid and claimed amounts and HRMS status |

Paying the advance is an accounts task:
[`payments.create_payment_entry`](payments.md) with `party_type=Employee` and a
reference to the Employee Advance.

## Expense claim — Expense Claim

| Method | HTTP | Purpose |
| --- | --- | --- |
| `create_expense_claim(expenses, remark?)` | POST | a draft; `expenses`: `[{"expense_type", "expense_date", "amount", "description"?}]` |
| `list_my_expense_claims(…)` | GET | |

The expense approver approves the claim in HRMS.

## Payslips, attendance and holidays (read-only)

| Method | HTTP | Purpose |
| --- | --- | --- |
| `list_my_salary_slips(limit_start, limit_page_length≤50)` | GET | issued (submitted) salary slips, newest period first |
| `get_my_salary_slip(name)` | GET | one issued slip with `earnings` and `deductions` (`component`, `abbr`, `amount`), payment days and totals |
| `list_my_attendance(from_date, to_date)` | GET | submitted Attendance in a range of at most 100 days: status, leave type, shift, working hours, in/out, late/early flags |
| `get_my_holidays(from_date, to_date)` | GET | holidays and weekly offs of the Holiday List that applies to the employee |

Payroll itself (Salary Structure, Payroll Entry) stays in HRMS; these methods only
show employees their own results.

## Where this module steps outside standard HRMS permissions

Both exceptions fix the employee to the session user before writing:

- **Travel Request**: HRMS grants it to System Manager only, so
  `create_travel_request` inserts on the employee's behalf. Lists and reads are
  limited to the caller's own Employee.
- **Withdrawing a leave**: HRMS keeps `status` writable only by approvers;
  `cancel_leave_application` sets `Cancelled` for the owner of an open, unsubmitted
  application.

## Site configuration HRMS needs

- A **Holiday List** on the Employee or Company (leave day counts).
- A **Leave Allocation** per employee and leave type (balances).
- A **leave approver** on the Employee or its Department.
- For advances: the company's *Default Employee Advance Account*, of type
  **Receivable**.
- For expense claims: a default account per company on each **Expense Claim Type**.

Missing configuration comes back as a `ValidationError` with HRMS's message.
