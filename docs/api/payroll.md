# Payroll — `asoud_erp.api.v1.payroll`

Payroll processing on HRMS. What each person earns and what is deducted
(insurance, tax, allowances) is configured in HRMS **Salary Components** and
**Salary Structures**; this module runs the process. Employees read their own
results through [`hr_self_service`](hr_self_service.md#payslips-attendance-and-holidays-read-only).

Roles: HR Manager (and System Manager) run payroll; HR User may also assign
structures.

```
Salary Structure (HRMS) ─▶ create_salary_structure_assignment ─▶ create_payroll_entry ─▶ draft Salary Slips
                                                                   submit_payroll_salary_slips ─▶ submitted slips + accrual Journal Entry
```

| Method | HTTP | Purpose |
| --- | --- | --- |
| `payroll_options(company)` | GET | active submitted salary structures, frequencies, payroll payable account, cost center, currency |
| `list_salary_structure_assignments(company, employee?, …)` | GET | |
| `create_salary_structure_assignment(employee, salary_structure, from_date, base, variable=0, payroll_payable_account?, submit=1)` | POST | `base`/`variable` feed the structure formulas |
| `create_payroll_entry(company, start_date, end_date, posting_date?, payroll_frequency=Monthly, department?, branch?, designation?, validate_attendance=0)` | POST | selects employees with a matching assignment and creates draft slips; above 30 employees HRMS queues it (status `Queued`) |
| `submit_payroll_salary_slips(payroll_entry)` | POST | submits the draft slips; HRMS books the accrual journal entry |
| `list_payroll_entries(company, …)` · `get_payroll_entry(name)` | GET | entry with its slips (`gross_pay`, `total_deduction`, `net_pay`) and totals |

## Site configuration HRMS needs

- Company: *Default Payroll Payable Account* and a default *Cost Center*.
- Every Salary Component: an account per company (used by the accrual entry).
- Employees are matched by company, currency, frequency and the assignment's
  payroll payable account; `create_salary_structure_assignment` defaults it to
  the company's.
- With `validate_attendance=1`, attendance must be marked for the period.

Example (tested): structure with `ASOUD Basic = base` and `ASOUD Insurance = base * 0.07`,
base 30,000,000 → gross 30,000,000, deductions 2,100,000, net 27,900,000.
