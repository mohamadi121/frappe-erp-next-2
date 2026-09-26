# Personnel file — `asoud_erp.api.v1.personnel_file`

The personnel file (پرونده پرسنلی) HR builds for every employee, and the employee's
own panel (خانه · اطلاعات من). Everything is read from standard records:

| Section | Source |
| --- | --- |
| header, personal, organization, employment | Employee (+ Iranian fields on ASOUD Party Profile) |
| education, previous work | Employee *Education* and *External Work History* tables (previous salary is never returned) |
| contracts | ERPNext **Contract** with `party_type = Employee`; signed copy as a private File on the Contract |
| salary | HRMS Salary Structure Assignment (current and history) and the latest submitted Salary Slip |
| documents | private Files on the Employee, with category/number/expiry kept on ASOUD Personnel Record |
| history | joining date, internal work history, HRMS Employee Promotion and Transfer, contracts, salary assignments, relieving date |
| attendance | this month's submitted Attendance and the last Employee Checkin |
| leave | HRMS `get_leave_details` balances |
| activity | Employee change Versions (field labels only), contracts and personnel records |

**Access.** HR Manager / System Manager: every profile of their companies, and
all writes. An employee: only their own file, read-only. **Bank details are never
returned** and cannot be edited here; HR keeps them on the ERPNext Employee form.

## Reading

| Method | HTTP | Purpose |
| --- | --- | --- |
| `get_personnel_file(name)` | GET | the file of profile `name` (an ASOUD Party Profile id) |
| `get_my_personnel_file()` | GET | the session user's own file («اطلاعات من»); `DoesNotExistError` until HR creates the profile |
| `get_contract_file(contract)` | GET | `{filename, content_base64}` of a contract's signed copy |
| `get_my_home()` | GET | the employee home screen (below) |
| `list_announcements()` | GET | public, unexpired announcements, newest first |

Document files keep using `personnel.get_record(id)` (it returns `file` as base64).

### File object

```json
{
  "profile_id": "PARTY-0042", "can_edit": true, "revision": "…",
  "header": {"name": "امیر موفق", "employee_code": "HR-EMP-00042", "designation": "کارشناس فروش",
             "department": "Sales - T", "department_name": "فروش", "company": "Tabaan", "status": "Active",
             "photo_record": "native:File:…", "employment_type": "Full-time", "date_of_joining": "2020-01-01",
             "service_length": {"years": 6, "months": 8, "days": 2459}, "linked": true},
  "personal": {"national_id": "…", "father_name": "…", "birth_date": "1990-01-01", "employee_gender": "Male",
               "marital_status": "Married", "blood_group": "O+", "mobile": "0912…", "phone": "", "email": "…",
               "company_email": "…", "address_line": "…", "province": "…", "city": "…", "postal_code": "…",
               "permanent_address": "…",
               "emergency": {"name": "زهرا", "phone": "0912…", "relation": "همسر"},
               "education": [{"qualification": "کارشناسی", "school": "…", "level": "Graduate",
                              "year_of_passing": 2012, "major": "…"}],
               "previous_work": [{"company": "…", "designation": "…", "experience": "3 سال"}]},
  "organization": {"company": "Tabaan", "department": "Sales - T", "department_name": "فروش",
                   "department_path": ["بازرگانی", "فروش"], "designation": "کارشناس فروش", "branch": "تهران",
                   "employee_number": "…", "direct_reports": 0,
                   "reports_to": {"employee": "HR-EMP-00007", "name": "محمد حسینی", "designation": "مدیر فروش",
                                  "department_name": "فروش"}},
  "employment": {"employment_type": "Full-time", "date_of_joining": "2020-01-01", "status": "Active",
                 "service_length": {…}, "scheduled_confirmation_date": "", "final_confirmation_date": "2020-04-01",
                 "contract_end_date": "2026-12-31", "notice_number_of_days": 30, "relieving_date": "",
                 "holiday_list": "…", "default_shift": "…"},
  "contracts": [{"name": "HR-CONT-0015", "start_date": "2026-01-01", "end_date": "2026-12-31", "status": "Active",
                 "is_signed": 1, "signed_on": "…", "docstatus": 1, "state": "active", "days_remaining": 97,
                 "terms": "…", "file": {"id": "…", "filename": "contract.pdf"}}],
  "salary": {"visible": true, "currency": "IRR",
             "current": {"salary_structure": "…", "from_date": "2026-03-21", "base": 30000000, "variable": 0},
             "history": [{…}], "latest_slip": {"start_date": "…", "end_date": "…", "gross_pay": 30000000,
             "total_deduction": 2100000, "net_pay": 27900000,
             "earnings": [{"component": "حقوق پایه", "amount": 30000000}], "deductions": [{…}]},
             "legacy": null},
  "documents": [{"id": "…", "title": "کارت ملی", "category": "Identity", "document_number": "0012345678",
                 "issue_date": "2015-05-01", "expiry_date": "2030-05-01", "status": "valid",
                 "filename": "id.pdf"}],
  "history": [{"kind": "promotion", "title": "ارتقا یا تغییر سمت", "date": "2026-09-25",
               "details": "Designation: کارشناس فروش ← سرپرست فروش", "reference": "HR-EMP-PRO-0001"}],
  "attendance": {"from_date": "2026-09-01", "to_date": "2026-09-25", "present": 18, "absent": 0,
                 "on_leave": 1, "half_day": 0, "late_entries": 2, "early_exits": 0, "by_status": {…},
                 "last_checkin": {"time": "2026-09-25 08:02:00", "log_type": "IN"}},
  "leave": [{"leave_type": "Casual Leave", "total_leaves": 12, "leaves_taken": 3, "leaves_pending_approval": 1,
             "remaining_leaves": 8, "expired_leaves": 0}],
  "activity": [{"date": "2026-09-25 10:41:00", "title": "ویرایش اطلاعات پرسنلی",
                "details": "سمت، مدیر مستقیم", "by": "مدیر منابع انسانی"}]
}
```

Values and their meaning:

- `header.employee_code` is the ERPNext Employee id; `null` while the profile is
  not yet linked to an Employee (show «در انتظار ثبت»; never show a local id).
- `documents[].status`: `valid`, `expiring` (expires within 30 days), `expired`,
  `no_expiry`. `category` ∈ Identity, Education, Employment, Medical, Financial, Other.
- `contracts[].state`: `draft`, `unsigned`, `upcoming`, `active`, `expired`
  (`cancelled` contracts are not listed).
- `history[].kind`: `joining`, `internal`, `promotion`, `transfer`, `contract`,
  `salary`, `relieving`; newest first.
- `salary.legacy` holds the old display-only amounts, for HR only, when HRMS has no
  salary assignment yet. Employees see HRMS data only.
- Dates are ISO; show them in Jalali.

## Writing (HR managers)

| Method | HTTP | Purpose |
| --- | --- | --- |
| `personnel.update_personnel(name, values, revision, request_id)` | POST | also accepts `marital_status`, `blood_group`, `emergency_contact_name`, `emergency_phone`, `emergency_relation`, `company_email`, `branch`, `reports_to` (Employee id, same company), `final_confirmation_date`, `contract_end_date`, `notice_number_of_days`, all written to Employee |
| `personnel.add_record(name, payload, request_id)` | POST | documents accept `document_category`, `document_number`, `expiry_date` (not before `date`) |
| `save_contract(name, start_date, terms, end_date?, contract?, is_signed=0, file?, filename?, submit=0)` | POST | creates, or edits while draft, an ERPNext Contract; `file` = base64 PDF/PNG/JPEG ≤ 5 MB; submitting a contract with an end date also updates the Employee's *contract end date*; returns the contracts list |
| `add_promotion(name, promotion_date, designation?, department?, branch?, remarks?)` | POST | HRMS Employee Promotion; submitted (and applied to the Employee) when the date is today or earlier, kept as draft otherwise |
| `create_announcement(title, content, expire_on?)` | POST | a public Frappe Note shown on every employee's home screen |

## Employee home — `get_my_home()`

```json
{
  "profile_id": "PARTY-0042", "employee": "HR-EMP-00042", "name": "امیر موفق",
  "designation": "کارشناس فروش", "department_name": "فروش", "company": "Tabaan",
  "photo_record": "native:File:…", "date": "2026-09-25",
  "counts": {"open_requests": 2, "open_tasks": 1, "unread_notifications": 3,
             "pending_leave_applications": 0, "leave_remaining": 8},
  "last_checkin": {"time": "2026-09-25 08:02:00", "log_type": "IN"},
  "announcements": [{"name": "…", "title": "جلسه عمومی", "summary": "…", "date": "…", "expires_on": "…"}]
}
```

Home quick actions map to: درخواست‌ها → `workflow_request` / [request cards](../backend-roadmap.md#request-cards--native-documents),
حضور و غیاب → `hr_self_service.create_checkin` / `list_my_attendance`, گزارش کار →
`hr.save_report`, مکاتبات → `hr.list_communications`, اطلاعات من →
`get_my_personnel_file`, مدارک → `get_my_personnel_file().documents`.
