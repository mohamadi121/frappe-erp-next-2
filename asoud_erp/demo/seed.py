"""Re-runnable demo seed for a real test site.

Run it with::

    bench --site <site> execute asoud_erp.demo.seed.run
    bench --site <site> execute asoud_erp.demo.seed.run --kwargs "{'reset': True}"

Everything is built on standard ERPNext/HRMS DocTypes and controller
functions (wrapped through the thin ``asoud_erp.api.v1`` layer where one
exists); nothing is faked and ERPNext/HRMS source is never touched.

Idempotency: every section first looks its records up by their stable
demo identity (company, prefixed codes, fixed request_ids) and only
creates what is missing, so running twice creates nothing new.

Reset (``reset=True``) cancels submitted documents, purges the ledger
rows of exactly the vouchers the seed created (the same tables
ERPNext's own company-transaction purge touches), then deletes every
marked record in dependency order. Nothing else is touched. One
deliberate leftover: the hidden Custom Field a native ``Workflow`` adds
to ``ASOUD Workflow Request`` (a compatibility reference shared with
any workflow on that DocType); it is documented in ``docs/demo-seed.md``.

Safety: refuses to run when ``developer_mode`` is off, and never on a
site whose name contains neither "test" nor "demo", unless ``force=True``.
"""

import base64
import json
import secrets
import time
from datetime import date

import frappe
from frappe.utils import (
    add_days,
    cint,
    get_first_day,
    get_year_ending,
    get_year_start,
    getdate,
    nowdate,
)

from asoud_erp.demo import markers as m

SUMMARY: dict = {}


def _count(section: str, created: int = 0, skipped: int = 0) -> None:
    entry = SUMMARY.setdefault(section, {"created": 0, "existing": 0})
    entry["created"] += created
    entry["existing"] += skipped


def _today() -> date:
    return getdate(nowdate())


def _set_values(doctype: str, name: str, values: dict) -> None:
    """db.set_value, but only for fields that actually change.

    Unconditional writes take row locks (a deadlock hazard on this shared
    box) and bump `modified`, which makes a same-run reset look like a
    concurrent edit. Demo state is already idempotent; keep the writes so.
    """
    current = frappe.db.get_value(doctype, name, list(values), as_dict=True) or {}
    diff = {key: value for key, value in values.items() if current.get(key) != value}
    if diff:
        frappe.db.set_value(doctype, name, diff)


# ------------------------------------------------------------------ entrypoint

def run(reset: bool = False, force: bool = False, password: str | None = None) -> dict:
    """Seed (default) or reset (``reset=True``) the demo dataset."""
    global SUMMARY
    SUMMARY = {}
    frappe.set_user("Administrator")
    site = frappe.local.site
    developer_mode = bool(frappe.conf.get("developer_mode"))
    error = m.guard_error(site, developer_mode, bool(force))
    if error:
        frappe.throw(error, frappe.PermissionError)
    if cint(reset):
        _reset()
    else:
        _seed(password)
    frappe.db.commit()
    return {"site": site, "reset": bool(cint(reset)), "summary": SUMMARY}


# ------------------------------------------------------------------ company

def _ensure_company() -> str:
    if frappe.db.exists("Company", m.COMPANY):
        _count("company", skipped=1)
        return m.COMPANY
    for gender in ("Male", "Female"):
        if not frappe.db.exists("Gender", gender):
            frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "Company",
        "company_name": m.COMPANY,
        "abbr": m.ABBR,
        "default_currency": m.CURRENCY,
        "country": m.COUNTRY,
        "chart_of_accounts": m.CHART_OF_ACCOUNTS,
    }).insert(ignore_permissions=True)
    _count("company", created=1)
    return m.COMPANY


def _ensure_company_setup() -> None:
    if frappe.db.exists("ASOUD Company Setup", m.COMPANY):
        _set_values(
            "ASOUD Company Setup",
            m.COMPANY,
            {
                "office_saved": 1,
                "accounting_saved": 1,
                "roles_saved": 1,
                "enabled_roles_json": json.dumps(["System Manager"]),
            },
        )
        _count("company_setup", skipped=1)
        return
    frappe.get_doc({
        "doctype": "ASOUD Company Setup",
        "company": m.COMPANY,
        "office_type": "Legal",
        "office_saved": 1,
        "accounting_saved": 1,
        "roles_saved": 1,
        "enabled_roles_json": json.dumps(["System Manager"]),
        "chart_template": "Iran Standard",
        "display_currency": "Rial",
        "accounting_basis": "Accrual",
        "auto_generate_detail_code": 1,
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
        "fiscal_year": "1405",
        "activity_type": "Commercial",
        "province": "Tehran",
        "city": "Tehran",
    }).insert(ignore_permissions=True)
    _count("company_setup", created=1)


def _ensure_fiscal_year() -> str:
    year = _today().year
    name = str(year)
    today = _today()
    covering = frappe.get_all(
        "Fiscal Year",
        filters={
            "disabled": 0,
            "year_start_date": ["<=", today],
            "year_end_date": [">=", today],
        },
        pluck="name",
        order_by="year_start_date desc",
        limit=1,
    )
    if covering:
        doc = frappe.get_doc("Fiscal Year", covering[0])
        action = m.fiscal_year_seed_action(
            [row.company for row in doc.companies], m.COMPANY
        )
        if action == "append":
            doc.append("companies", {"company": m.COMPANY})
            doc.save(ignore_permissions=True)
            _count("fiscal_year", created=1)
        else:
            # "use": no company rows means the year applies to every company, so
            # adding a row would restrict it to the demo company.
            _count("fiscal_year", skipped=1)
        return doc.name
    frappe.get_doc({
        "doctype": "Fiscal Year",
        "year": name,
        "year_start_date": f"{year}-01-01",
        "year_end_date": f"{year}-12-31",
        "companies": [{"company": m.COMPANY}],
    }).insert(ignore_permissions=True)
    _count("fiscal_year", created=1)
    return name


def _leaf(doctype: str) -> str:
    return frappe.get_all(doctype, filters={"is_group": 0}, pluck="name",
                          order_by="lft asc", limit=1)[0]


# ------------------------------------------------------------------ HR masters

def _ensure_departments() -> dict:
    result = {}
    parent = frappe.db.get_value("Department", {"company": m.COMPANY, "is_group": 1}, "name")
    for name in m.DEPARTMENTS:
        existing = frappe.db.get_value("Department", {"company": m.COMPANY, "department_name": name}, "name")
        if existing:
            result[name] = existing
            _count("departments", skipped=1)
            continue
        doc = frappe.get_doc({"doctype": "Department", "department_name": name,
                              "company": m.COMPANY})
        if parent:
            doc.parent_department = parent
        result[name] = doc.insert(ignore_permissions=True).name
        _count("departments", created=1)
    return result


def _ensure_designations() -> None:
    for name in m.DESIGNATIONS:
        if frappe.db.exists("Designation", name):
            _count("designations", skipped=1)
            continue
        frappe.get_doc({"doctype": "Designation", "designation_name": name,
                        "description": name}).insert(ignore_permissions=True)
        _count("designations", created=1)


def _ensure_employees(departments: dict) -> dict:
    """Employee records through the asoud personnel API (``save_party``)."""
    from asoud_erp.api.v1 import party

    profiles: dict = {}
    for index, (full_name, dept_no, desig_no, reports_to, gender) in enumerate(m.EMPLOYEES):
        existing = frappe.db.get_value(
            "ASOUD Party Profile", {"display_name": full_name, "company": m.COMPANY},
            ["name", "employee"], as_dict=True)
        if existing and existing.employee and frappe.db.exists("Employee", existing.employee):
            profiles[index] = (existing.name, existing.employee)
            _count("employees", skipped=1)
            continue
        dept_name = departments[m.DEPARTMENTS[dept_no]] if dept_no is not None else None
        result = party.save_party(
            party_type="Individual", display_name=full_name, roles=["Employee"],
            company=m.COMPANY, employee_gender=gender,
            birth_date=f"{1965 + index}-04-{(index % 27) + 1:02d}",
            date_of_joining="2020-03-01" if index == 0 else f"2022-{(index % 12) + 1:02d}-01",
            mobile=f"091200000{index + 10:02d}",
            job_title=m.DESIGNATIONS[desig_no],
            department=dept_name,
        )["data"]
        profiles[index] = (result["name"], result["employee"])
        _count("employees", created=1)
    # Reporting chain, designations and departments on the native Employee.
    for index, (_name, dept_no, desig_no, reports_to, _gender) in enumerate(m.EMPLOYEES):
        _profile, employee = profiles[index]
        doc = frappe.get_doc("Employee", employee)
        changed = False
        designation = m.DESIGNATIONS[desig_no]
        if doc.designation != designation:
            doc.designation = designation
            changed = True
        if dept_no is not None:
            dept_name = departments[m.DEPARTMENTS[dept_no]]
            if doc.department != dept_name:
                doc.department = dept_name
                changed = True
        manager = profiles[reports_to][1] if reports_to is not None else None
        if (doc.reports_to or None) != manager:
            doc.reports_to = manager
            changed = True
        if changed:
            doc.save(ignore_permissions=True)
    return profiles


def _ensure_users(profiles: dict, password: str | None) -> tuple[str, bool]:
    """System users for three employees plus one who never logs in."""
    created_any = False
    for local_part, emp_index, roles, _note in m.USERS:
        email = m.demo_email(local_part)
        if frappe.db.exists("User", email):
            _count("users", skipped=1)
            continue
        frappe.get_doc({
            "doctype": "User", "email": email,
            "first_name": m.EMPLOYEES[emp_index][0].split()[0],
            "last_name": m.EMPLOYEES[emp_index][0].split()[-1],
            "send_welcome_email": 0, "user_type": "System User",
            "roles": [{"role": role} for role in roles],
        }).insert(ignore_permissions=True)
        created_any = True
        _count("users", created=1)
    if not created_any:
        return (password or ""), False
    pwd = password or secrets.token_urlsafe(9)
    from frappe.utils.password import update_password

    for local_part, emp_index, _roles, _note in m.USERS:
        email = m.demo_email(local_part)
        update_password(email, pwd, logout_all_sessions=True)
        _profile, employee = profiles[emp_index]
        doc = frappe.get_doc("Employee", employee)
        if doc.user_id != email:
            doc.user_id = email
            doc.create_user_permission = 0
            doc.save(ignore_permissions=True)
    if not password:
        # Printed once: the generated default is shared by all demo users.
        print(f"[asoud_demo_seed] demo user password (all {m.EMAIL_DOMAIN} users): {pwd}")
    return pwd, True


def _contract_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    import io

    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _ensure_personnel_records(profiles: dict) -> None:
    """Contract/document rows through the asoud personnel record API."""
    from asoud_erp.api.v1 import personnel

    ceo_profile = profiles[0][0]
    if not frappe.db.exists("ASOUD Personnel Record",
                             {"party": ceo_profile, "title": "شروع همکاری"}):
        personnel.add_record(ceo_profile, {
            "kind": "history", "title": "شروع همکاری",
            "date": "2020-03-01", "notes": "تأسیس شرکت نمونه آسود",
        }, "asoud-demo-record-ceo-history")
        _count("personnel_records", created=1)
    else:
        _count("personnel_records", skipped=1)
    sales_profile = profiles[1][0]
    if not frappe.db.exists("ASOUD Personnel Record",
                             {"party": sales_profile, "document_number": m.PURCHASE_BILL_NO}):
        personnel.add_record(sales_profile, {
            "kind": "document", "title": "قرارداد استخدام",
            "date": "2022-02-01", "document_category": "Employment",
            "document_number": m.PURCHASE_BILL_NO,
            "file": base64.b64encode(_contract_pdf()).decode(),
            "filename": "contract.pdf",
        }, "asoud-demo-record-sales-contract")
        _count("personnel_records", created=1)
    else:
        _count("personnel_records", skipped=1)


# ------------------------------------------------------------------ leave & pay

def _ensure_holiday_list() -> str:
    year = _today().year
    name = f"{m.HOLIDAY_LIST} {year}"
    if frappe.db.exists("Holiday List", name):
        _count("holiday_list", skipped=1)
    else:
        frappe.get_doc({
            "doctype": "Holiday List", "holiday_list_name": name,
            "from_date": get_year_start(nowdate()), "to_date": get_year_ending(nowdate()),
            "holidays": [
                {"holiday_date": f"{year}-03-21", "description": "نوروز"},
                {"holiday_date": f"{year}-04-01", "description": "روز طبیعت"},
                {"holiday_date": f"{year}-06-04", "description": "تعطیل رسمی"},
            ],
        }).insert(ignore_permissions=True)
        _count("holiday_list", created=1)
    _set_values("Company", m.COMPANY, {"default_holiday_list": name})
    for employee in _demo_employees():
        _set_values("Employee", employee, {"holiday_list": name})
    return name


def _demo_employees() -> list:
    return frappe.get_all("Employee", filters={"company": m.COMPANY, "status": "Active"},
                           pluck="name", order_by="creation asc")


def _ensure_leave_types() -> list:
    names = []
    for index, (title, max_leaves) in enumerate(m.LEAVE_TYPES):
        if frappe.db.exists("Leave Type", title):
            _count("leave_types", skipped=1)
        else:
            frappe.get_doc({"doctype": "Leave Type", "leave_type_name": title,
                            "max_leaves_allowed": max_leaves,
                            "allow_encashment": 0}).insert(ignore_permissions=True)
            _count("leave_types", created=1)
        # The leave template offers only Leave Types that have an Asoud category.
        _set_values("Leave Type", title, {"asoud_leave_category": m.LEAVE_CATEGORIES[index]})
        names.append(title)
    return names


def _ensure_leave_allocations(leave_types: list) -> None:
    start, end = str(get_year_start(nowdate())), str(get_year_ending(nowdate()))
    for employee in _demo_employees():
        for leave_type, _max_leaves in m.LEAVE_TYPES:
            if frappe.db.exists("Leave Allocation", {"employee": employee, "leave_type": leave_type,
                                                     "docstatus": 1, "from_date": start}):
                _count("leave_allocations", skipped=1)
                continue
            frappe.get_doc({
                "doctype": "Leave Allocation", "employee": employee, "leave_type": leave_type,
                "from_date": start, "to_date": end, "new_leaves_allocated": 26
                if leave_type == leave_types[0] else 8,
                "company": m.COMPANY,
            }).insert(ignore_permissions=True).submit()
            _count("leave_allocations", created=1)


def _ensure_leave_applications(profiles: dict, approver_email: str) -> dict:
    """Two approved leave applications inside the current month."""
    month_start = get_first_day(nowdate())
    first = str(month_start)
    plans = [
        (5, m.LEAVE_TYPES[0][0], first, str(add_days(first, 2))),
        (6, m.LEAVE_TYPES[1][0], str(add_days(first, 9)), str(add_days(first, 10))),
    ]
    leave_days: dict = {}
    for emp_index, leave_type, from_date, to_date in plans:
        _profile, employee = profiles[emp_index]
        if frappe.db.exists("Leave Application", {"employee": employee, "leave_type": leave_type,
                                                  "from_date": from_date, "docstatus": 1}):
            _count("leave_applications", skipped=1)
        else:
            doc = frappe.get_doc({
                "doctype": "Leave Application", "employee": employee, "company": m.COMPANY,
                "leave_type": leave_type, "from_date": from_date, "to_date": to_date,
                "description": "مرخصی نمایشی", "leave_approver": approver_email,
                "posting_date": nowdate(), "status": "Approved",
            })
            doc.insert(ignore_permissions=True)
            doc.submit()
            _count("leave_applications", created=1)
        day = getdate(from_date)
        while day <= getdate(to_date):
            leave_days.setdefault(employee, set()).add(str(day))
            day = add_days(day, 1)
    return leave_days


def _expense_account() -> str:
    rows = frappe.get_all("Account", filters={"company": m.COMPANY, "root_type": "Expense",
                                              "is_group": 0}, pluck="name", limit=1)
    return rows[0]


def _liability_account() -> str:
    rows = frappe.get_all("Account", filters={"company": m.COMPANY, "root_type": "Liability",
                                              "is_group": 0, "account_name": ["like", "%Payroll%"]},
                           pluck="name", limit=1)
    if rows:
        return rows[0]
    return frappe.get_all("Account", filters={"company": m.COMPANY, "root_type": "Liability",
                                              "is_group": 0}, pluck="name", limit=1)[0]


def _ensure_salary() -> None:
    payable = f"Payroll Payable - {m.ABBR}"
    if frappe.db.exists("Account", payable):
        _set_values("Account", payable, {"account_type": "Receivable"})
        _set_values("Company", m.COMPANY, {"default_payroll_payable_account": payable})
    for title, abbr, kind, account in (
            (m.SALARY_EARNING, m.SALARY_EARNING_ABBR, "Earning", _expense_account()),
            (m.SALARY_DEDUCTION, m.SALARY_DEDUCTION_ABBR, "Deduction", _liability_account())):
        if frappe.db.exists("Salary Component", title):
            _count("salary_components", skipped=1)
            continue
        frappe.get_doc({
            "doctype": "Salary Component", "salary_component": title,
            "salary_component_abbr": abbr, "type": kind,
            "accounts": [{"company": m.COMPANY, "account": account}],
        }).insert(ignore_permissions=True)
        _count("salary_components", created=1)
    if frappe.db.exists("Salary Structure", m.SALARY_STRUCTURE):
        _count("salary_structure", skipped=1)
    else:
        structure = frappe.get_doc({
            "doctype": "Salary Structure", "company": m.COMPANY,
            "payroll_frequency": "Monthly", "is_active": "Yes", "currency": m.CURRENCY,
            "earnings": [{"salary_component": m.SALARY_EARNING, "abbr": m.SALARY_EARNING_ABBR,
                          "amount_based_on_formula": 1, "formula": "base"}],
            "deductions": [{"salary_component": m.SALARY_DEDUCTION, "abbr": m.SALARY_DEDUCTION_ABBR,
                            "amount_based_on_formula": 1, "formula": "base * 0.07"}],
        })
        structure.insert(ignore_permissions=True, set_name=m.SALARY_STRUCTURE)
        structure.submit()
        _count("salary_structure", created=1)
    for employee in _demo_employees():
        if frappe.db.exists("Salary Structure Assignment", {"employee": employee,
                                                             "salary_structure": m.SALARY_STRUCTURE,
                                                             "docstatus": 1}):
            _count("salary_assignments", skipped=1)
            continue
        frappe.get_doc({
            "doctype": "Salary Structure Assignment", "employee": employee, "company": m.COMPANY,
            "salary_structure": m.SALARY_STRUCTURE, "from_date": f"{_today().year}-01-01",
            "base": m.SALARY_BASE, "variable": 0, "currency": m.CURRENCY,
        }).insert(ignore_permissions=True).submit()
        _count("salary_assignments", created=1)


def _ensure_attendance(holiday_list: str, leave_days: dict) -> None:
    holidays = set(frappe.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date"))
    holidays = {str(day) for day in holidays}
    day = getdate(get_first_day(nowdate()))
    end = _today()
    while day <= end:
        for employee in _demo_employees():
            day_str = str(day)
            if frappe.db.exists("Attendance", {"employee": employee, "attendance_date": day_str,
                                               "docstatus": ["!=", 2]}):
                _count("attendance", skipped=1)
                continue
            if day.weekday() == 4 or day_str in holidays:
                continue
            status = "On Leave" if day_str in leave_days.get(employee, set()) else "Present"
            frappe.get_doc({
                "doctype": "Attendance", "employee": employee, "company": m.COMPANY,
                "attendance_date": day_str, "status": status,
            }).insert(ignore_permissions=True).submit()
            _count("attendance", created=1)
        day = add_days(day, 1)


# ------------------------------------------------------------------ stock & trade

def _ensure_price_lists() -> None:
    """Demo price lists in the company currency (IRR).

    The site defaults ("Standard Selling"/"Standard Buying") are usually in
    the site currency, which would force a currency conversion on every demo
    invoice — failing without an exchange rate. Demo parties point at these
    lists instead, so no conversion ever happens.
    """
    for name, selling, buying in ((m.PRICE_LIST_SELLING, 1, 0),
                                  (m.PRICE_LIST_BUYING, 0, 1)):
        if frappe.db.exists("Price List", name):
            _count("price_lists", skipped=1)
            continue
        frappe.get_doc({"doctype": "Price List", "price_list_name": name,
                        "currency": m.CURRENCY, "selling": selling,
                        "buying": buying, "enabled": 1}).insert(ignore_permissions=True)
        _count("price_lists", created=1)


def _ensure_trade_masters() -> tuple[str, list, list]:
    _ensure_price_lists()
    for code, title, is_stock, rate in m.ITEMS:
        if frappe.db.exists("Item", code):
            _count("items", skipped=1)
        else:
            frappe.get_doc({
                "doctype": "Item", "item_code": code, "item_name": title,
                "item_group": _leaf("Item Group"), "stock_uom": "Nos",
                "is_stock_item": is_stock, "valuation_rate": rate if is_stock else 0,
                "standard_rate": rate,
            }).insert(ignore_permissions=True)
            _count("items", created=1)
        # Prices live in the demo IRR lists; drop stale rows in other lists
        # (e.g. left by an older seed run) so nothing prices in USD.
        for price in frappe.get_all("Item Price", filters={"item_code": code},
                                     fields=["name", "price_list"]):
            if price.price_list not in (m.PRICE_LIST_SELLING, m.PRICE_LIST_BUYING):
                frappe.delete_doc("Item Price", price.name, ignore_permissions=True)
        for price_list, flag in ((m.PRICE_LIST_SELLING, "selling"),
                                 (m.PRICE_LIST_BUYING, "buying")):
            if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
                frappe.get_doc({"doctype": "Item Price", "item_code": code,
                                "price_list": price_list, "price_list_rate": rate,
                                flag: 1}).insert(ignore_permissions=True)
    for title in m.CUSTOMERS:
        if frappe.db.exists("Customer", title):
            _count("customers", skipped=1)
        else:
            frappe.get_doc({"doctype": "Customer", "customer_name": title,
                            "customer_group": _leaf("Customer Group"),
                            "territory": _leaf("Territory")}).insert(ignore_permissions=True)
            _count("customers", created=1)
        # The document currency follows the party default; repair rows from
        # older runs so every invoice is created in the company currency.
        _set_values("Customer", title, {
            "default_currency": m.CURRENCY, "default_price_list": m.PRICE_LIST_SELLING})
    for title in m.SUPPLIERS:
        if frappe.db.exists("Supplier", title):
            _count("suppliers", skipped=1)
        else:
            frappe.get_doc({"doctype": "Supplier", "supplier_name": title,
                            "supplier_group": _leaf("Supplier Group")}).insert(ignore_permissions=True)
            _count("suppliers", created=1)
        _set_values("Supplier", title, {
            "default_currency": m.CURRENCY, "default_price_list": m.PRICE_LIST_BUYING})
    warehouse = f"Stores - {m.ABBR}"
    if not frappe.db.exists("Warehouse", warehouse):
        frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "Stores",
                        "company": m.COMPANY}).insert(ignore_permissions=True)
        _count("warehouse", created=1)
    else:
        _count("warehouse", skipped=1)
    return warehouse, list(m.CUSTOMERS), list(m.SUPPLIERS)


def _ensure_stock(warehouse: str) -> None:
    from asoud_erp.api.v1 import stock

    if frappe.db.exists("Stock Entry", {"company": m.COMPANY, "docstatus": 1}):
        _count("stock_entries", skipped=1)
        return
    stock.create_stock_entry(m.COMPANY, "Material Receipt", [
        {"item_code": code, "qty": 50, "rate": rate, "t_warehouse": warehouse}
        for code, _title, is_stock, rate in m.ITEMS if is_stock
    ], remarks="[ASOUD-DEMO] موجودی اولیه", submit=1)
    _count("stock_entries", created=1)


def _ensure_sales(customers: list) -> None:
    from asoud_erp.api.v1 import selling

    if frappe.db.count("Sales Invoice", {"company": m.COMPANY, "docstatus": 1}) >= 2:
        _count("sales_invoices", skipped=2)
        return
    selling.create_sales_invoice(
        m.COMPANY, customers[0],
        [{"item_code": "ASOUD-DEMO-SERVICE-01", "qty": 1, "rate": 5000000},
         {"item_code": "ASOUD-DEMO-ITEM-01", "qty": 2, "rate": 1500000}],
        remarks="[ASOUD-DEMO] فروش نمایشی ۱", submit=1,
        currency=m.CURRENCY, selling_price_list=m.PRICE_LIST_SELLING)
    selling.create_sales_invoice(
        m.COMPANY, customers[1],
        [{"item_code": "ASOUD-DEMO-ITEM-02", "qty": 3, "rate": 2800000},
         {"item_code": "ASOUD-DEMO-ITEM-03", "qty": 1, "rate": 950000}],
        remarks="[ASOUD-DEMO] فروش نمایشی ۲", submit=1,
        currency=m.CURRENCY, selling_price_list=m.PRICE_LIST_SELLING)
    _count("sales_invoices", created=2)


def _ensure_purchase(suppliers: list, warehouse: str) -> None:
    from asoud_erp.api.v1 import buying

    if frappe.db.exists("Purchase Order", {"company": m.COMPANY}):
        _count("purchase_flow", skipped=1)
        return
    order = buying.create_purchase_order(
        m.COMPANY, suppliers[0],
        [{"item_code": "ASOUD-DEMO-ITEM-01", "qty": 10, "rate": 1400000,
          "warehouse": warehouse}],
        schedule_date=str(add_days(nowdate(), 7)), submit=1,
        currency=m.CURRENCY, buying_price_list=m.PRICE_LIST_BUYING)["data"]
    buying.create_purchase_receipt_from_order(order["name"], submit=1)
    buying.create_purchase_invoice_from_order(order["name"], bill_no=m.PURCHASE_BILL_NO, submit=1)
    _count("purchase_flow", created=1)


# ------------------------------------------------------------------ workflows

def _drive_to_completed(instance: str, action: str, comment: str) -> None:
    """Complete every open task until the instance leaves Running (max 5 rounds)."""
    from asoud_erp.api.v1 import workflow_runtime

    for _round in range(5):
        doc = frappe.get_doc("ASOUD Workflow Instance", instance)
        if doc.status != "Running":
            return
        open_tasks = frappe.get_all("ASOUD Workflow Task",
                                    filters={"workflow_instance": instance, "status": "Open"},
                                    fields=["name", "assigned_to"])
        if not open_tasks:
            return
        for task in open_tasks:
            frappe.set_user(task.assigned_to)
            workflow_runtime.complete_workflow_task(task.name, action, comment=comment)
        frappe.set_user("Administrator")


def _request_plans(warehouse: str, holiday_list: str) -> list:
    """The demo requests: (key, template, requester, subject, values, target status, action).

    Leave dates are in the future (see ``markers.demo_leave_dates``); in the last days of the
    calendar year there is no room left and the leave requests are skipped.
    """
    today = _today()
    employee, newcomer = m.demo_email("employee"), m.demo_email("newcomer")
    department = {email: frappe.db.get_value("Employee", {"user_id": email}, "department")
                  for email in (employee, newcomer)}
    annual, sick = (title for title, _max_leaves in m.LEAVE_TYPES)
    needed = str(add_days(today, 10))
    service = m.ITEMS[3][0]

    def who(email: str) -> dict:
        return {"requester": email, "org_unit": department[email]}

    plans = [
        ("purchase-approved", "purchase", employee, "خرید خدمات نصب تجهیزات",
         {**who(employee), "needed_date": needed, "priority": "Normal", "reason": "نصب تجهیزات واحد فروش",
          "items": [{"item_code": service, "qty": 1, "description": "نصب و راه‌اندازی",
                     "note": "هماهنگی با واحد فروش"}]},
         "Completed", "Approve"),
        ("purchase-rejected", "purchase", employee, "خرید لپ‌تاپ",
         {**who(employee), "needed_date": needed, "priority": "High", "reason": "تجهیز واحد فروش",
          "items": [{"item_code": m.ITEMS[0][0], "qty": 2, "description": "لپ‌تاپ اداری"}]},
         "Rejected", "Reject"),
        ("supply-approved", "supply", newcomer, "تأمین کالا برای انبار مرکزی",
         {**who(newcomer), "delivery_location": f"warehouse:{warehouse}", "needed_date": needed,
          "supply_method": "Transfer", "priority": "Normal", "reason": "انتقال کالا به انبار مرکزی",
          "items": [{"item_code": m.ITEMS[1][0], "qty": 3, "description": "انتقال از انبار فرعی"}]},
         "Completed", "Approve"),
    ]
    holidays = {str(day) for day in frappe.get_all("Holiday", filters={"parent": holiday_list},
                                                   pluck="holiday_date")}
    dates = m.demo_leave_dates(today, getdate(get_year_ending(nowdate())), holidays)
    if not dates:
        SUMMARY.setdefault("skipped_requests", []).extend(
            key for key in ("leave-approved", "leave-pending", "leave-cancelled"))
        return plans
    approved, cancelled = dates["approved"], dates["cancelled"]
    plans += [
        ("leave-approved", "leave", employee, "",
         {**who(employee), "leave_type": annual, "request_kind": "Daily", "start_date": str(approved[0]),
          "end_date": str(approved[1]), "reason": "سفر خانوادگی"}, "Completed", "Approve"),
        ("leave-pending", "leave", newcomer, "",
         {**who(newcomer), "leave_type": sick, "request_kind": "Hourly", "leave_date": str(dates["pending"]),
          "start_time": "09:00", "end_time": "13:00", "reason": "مراجعه به پزشک"}, "Running", None),
        ("leave-cancelled", "leave", newcomer, "",
         {**who(newcomer), "leave_type": annual, "request_kind": "Daily", "start_date": str(cancelled[0]),
          "end_date": str(cancelled[1]), "reason": "تغییر برنامه"}, "Cancelled", None),
    ]
    return plans


def _ensure_requests(warehouse: str, holiday_list: str) -> None:
    """Requests of the system templates, created, approved or cancelled like real users would.

    Approving a purchase or supply request creates a draft Material Request, approving a leave
    request a Leave Application (daily) or Leave Ledger Entry (hourly); the post-approval hook
    does that, nothing here writes those documents.
    """
    from asoud_erp.api.v1 import workflow_request

    for key, template, requester, subject, values, target, action in _request_plans(warehouse, holiday_list):
        request_id = m.REQUEST_IDS[key]
        existing = frappe.db.get_value("ASOUD Workflow Request", {"request_id": request_id},
                                       ["name", "workflow_instance"], as_dict=True)
        if existing:
            _count("workflow_requests", skipped=1)
            request_name, instance = existing.name, existing.workflow_instance
        else:
            frappe.set_user(requester)
            created = workflow_request.create_request(
                company=m.COMPANY, template_key=template, subject=subject, request_id=request_id,
                values=values)["data"]
            frappe.set_user("Administrator")
            request_name, instance = created["name"], created["workflow_instance"]
            _count("workflow_requests", created=1)
        status = frappe.db.get_value("ASOUD Workflow Instance", instance, "status")
        if status == target or status != "Running":
            continue
        if target == "Cancelled":
            frappe.set_user(requester)
            workflow_request.cancel_request(request_name, reason="انصراف")
            frappe.set_user("Administrator")
        else:
            _drive_to_completed(instance, action,
                                "تأیید شد" if action == "Approve" else "بودجه کافی نیست")
            native = frappe.db.get_value("ASOUD Workflow Request", request_name,
                                         ["native_status", "native_error"], as_dict=True)
            if native.native_status == "Created":
                _count("native_documents", created=1)
            elif native.native_status == "Failed":
                SUMMARY.setdefault("native_failed", []).append(
                    {"request": request_name, "error": native.native_error})


def _seed(password: str | None) -> None:
    _ensure_company()
    _ensure_company_setup()
    _ensure_fiscal_year()
    departments = _ensure_departments()
    _ensure_designations()
    profiles = _ensure_employees(departments)
    _ensure_users(profiles, password)
    _ensure_personnel_records(profiles)
    holiday_list = _ensure_holiday_list()
    leave_types = _ensure_leave_types()
    _ensure_leave_allocations(leave_types)
    approver = m.demo_email("sales-manager")
    leave_days = _ensure_leave_applications(profiles, approver)
    _ensure_salary()
    _ensure_attendance(holiday_list, leave_days)
    warehouse, customers, suppliers = _ensure_trade_masters()
    _ensure_stock(warehouse)
    _ensure_sales(customers)
    _ensure_purchase(suppliers, warehouse)
    from asoud_erp.services.request_templates.seed import ensure_system_templates

    templates = ensure_system_templates(m.COMPANY)
    _count("system_templates", created=templates["created"] + templates["updated"],
           skipped=templates["skipped"])
    _ensure_requests(warehouse, holiday_list)
    frappe.set_user("Administrator")


# ------------------------------------------------------------------ reset

def _cancel_and_delete(doctype: str, names: list, purge_ledger: bool = False) -> int:
    removed = 0
    for name in names:
        if not frappe.db.exists(doctype, name):
            continue
        _delete_one(doctype, name, purge_ledger)
        removed += 1
    return removed


def _delete_one(doctype: str, name: str, purge_ledger: bool) -> None:
    """Cancel (if submitted), purge ledgers, delete — retrying lock contention.

    The site is shared, so a row lock held by another connection surfaces as
    QueryTimeoutError/QueryDeadlockError. The failed statement is atomic, so
    retrying the whole step without rolling back is safe; earlier deletes in
    this transaction are untouched.
    """
    for attempt in range(4):
        try:
            doc = frappe.get_doc(doctype, name)
            if doc.get("docstatus") == 1:
                doc.cancel()
            if purge_ledger:
                for table in ("GL Entry", "Payment Ledger Entry", "Stock Ledger Entry"):
                    frappe.db.sql(f"delete from `tab{table}` where voucher_type=%s and voucher_no=%s",
                                  (doctype, name))
            frappe.delete_doc(doctype, name, ignore_permissions=True)
            return
        except (frappe.QueryTimeoutError, frappe.QueryDeadlockError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def _pluck(doctype: str, filters: dict) -> list:
    return frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0)


def _shared_workflow_unreferenced() -> bool:
    """The shared native Workflow of the system templates exists and no definition uses it."""
    return bool(frappe.db.exists("Workflow", m.SYSTEM_NATIVE_WORKFLOW)) and not frappe.db.exists(
        "ASOUD Workflow Definition", {"frappe_workflow": m.SYSTEM_NATIVE_WORKFLOW})


def _definition_names() -> list:
    return _pluck("ASOUD Workflow Definition", {"company": m.COMPANY})


def _demo_instance_names(definitions: list | None = None) -> list:
    definitions = definitions if definitions is not None else _definition_names()
    if not definitions:
        return []
    return frappe.get_all("ASOUD Workflow Instance",
                           filters={"workflow_definition": ["in", definitions]},
                           pluck="name", limit_page_length=0)


def check() -> dict:
    """Read-only count of demo-marked records per DocType (all zero = clean)."""
    frappe.set_user("Administrator")
    demo_employees = _pluck("Employee", {"company": m.COMPANY})
    demo_profiles = _pluck("ASOUD Party Profile", {"company": m.COMPANY})
    definitions = _definition_names()
    instances = _demo_instance_names(definitions)

    def in_demo(values: list) -> list:
        return ["in", values] if values else ["in", [""]]

    result = {
        "Company": frappe.db.count("Company", {"name": m.COMPANY}),
        "ASOUD Company Setup": frappe.db.count("ASOUD Company Setup", {"company": m.COMPANY}),
        "Employee": len(demo_employees),
        "Department": frappe.db.count("Department", {"company": m.COMPANY}),
        "User": sum(1 for local, _i, _r, _n in m.USERS
                     if frappe.db.exists("User", m.demo_email(local))),
        "ASOUD Party Profile": len(demo_profiles),
        "ASOUD Personnel Record": frappe.db.count(
            "ASOUD Personnel Record", {"party": in_demo(demo_profiles)}),
        "ASOUD Personnel Operation": frappe.db.count(
            "ASOUD Personnel Operation", {"party": in_demo(demo_profiles)}),
        "ASOUD Floating Detail": frappe.db.count(
            "ASOUD Floating Detail", {"linked_document": in_demo(demo_profiles)}),
        "Customer": sum(1 for title in m.CUSTOMERS if frappe.db.exists("Customer", title)),
        "Supplier": sum(1 for title in m.SUPPLIERS if frappe.db.exists("Supplier", title)),
        "Item": sum(1 for code, _t, _s, _r in m.ITEMS if frappe.db.exists("Item", code)),
        "Item Price": frappe.db.count(
            "Item Price", {"item_code": in_demo([code for code, _t, _s, _r in m.ITEMS])}),
        "Price List": sum(1 for name in (m.PRICE_LIST_SELLING, m.PRICE_LIST_BUYING)
                          if frappe.db.exists("Price List", name)),
        "Warehouse": frappe.db.count("Warehouse", {"company": m.COMPANY}),
        "Stock Entry": frappe.db.count("Stock Entry", {"company": m.COMPANY}),
        "Sales Invoice": frappe.db.count("Sales Invoice", {"company": m.COMPANY}),
        "Purchase Order": frappe.db.count("Purchase Order", {"company": m.COMPANY}),
        "Purchase Receipt": frappe.db.count("Purchase Receipt", {"company": m.COMPANY}),
        "Purchase Invoice": frappe.db.count("Purchase Invoice", {"company": m.COMPANY}),
        "Payment Entry": frappe.db.count("Payment Entry", {"company": m.COMPANY}),
        "Attendance": frappe.db.count("Attendance", {"company": m.COMPANY}),
        "Leave Application": frappe.db.count("Leave Application", {"company": m.COMPANY}),
        "Leave Allocation": frappe.db.count("Leave Allocation", {"company": m.COMPANY}),
        "Salary Structure": frappe.db.count("Salary Structure",
                                            {"name": m.SALARY_STRUCTURE}),
        "Salary Component": sum(1 for name in (m.SALARY_EARNING, m.SALARY_DEDUCTION)
                                if frappe.db.exists("Salary Component", name)),
        "Salary Structure Assignment": frappe.db.count(
            "Salary Structure Assignment", {"company": m.COMPANY}),
        "Salary Slip": frappe.db.count("Salary Slip", {"company": m.COMPANY}),
        "Payroll Entry": frappe.db.count("Payroll Entry", {"company": m.COMPANY}),
        "Holiday List": frappe.db.count(
            "Holiday List", {"holiday_list_name": ["like", f"{m.HOLIDAY_LIST}%"]}),
        "Leave Type": sum(1 for title, _max_leaves in m.LEAVE_TYPES
                          if frappe.db.exists("Leave Type", title)),
        "Designation": sum(1 for name in m.DESIGNATIONS
                           if frappe.db.exists("Designation", name)),
        "ASOUD Workflow Definition": len(definitions),
        "ASOUD Workflow Stage": frappe.db.count(
            "ASOUD Workflow Stage", {"workflow_definition": in_demo(definitions)}),
        "ASOUD Workflow Transition": frappe.db.count(
            "ASOUD Workflow Transition", {"workflow_definition": in_demo(definitions)}),
        "ASOUD Workflow Request": frappe.db.count(
            "ASOUD Workflow Request", {"company": m.COMPANY}),
        "ASOUD Workflow Instance": len(instances),
        "ASOUD Workflow Task": frappe.db.count(
            "ASOUD Workflow Task", {"workflow_instance": in_demo(instances)}),
        "ASOUD Workflow Activity": frappe.db.count(
            "ASOUD Workflow Activity", {"workflow_instance": in_demo(instances)}),
        # The shared system workflow is only counted once nothing else references it.
        "Workflow": sum(1 for name in (f"{code}-NATIVE" for code in m.LEGACY_WORKFLOW_CODES)
                        if frappe.db.exists("Workflow", name)) + int(_shared_workflow_unreferenced()),
        "Workflow State": 1 if frappe.db.exists("Workflow State", f"{m.PREFIX} Draft") else 0,
        "Material Request": frappe.db.count("Material Request", {"company": m.COMPANY}),
        "Notification Log": frappe.db.count(
            "Notification Log", {"document_type": "ASOUD Workflow Instance",
                                 "document_name": in_demo(instances)}),
        "GL Entry": frappe.db.count("GL Entry", {"company": m.COMPANY}),
        "Stock Ledger Entry": frappe.db.count("Stock Ledger Entry", {"company": m.COMPANY}),
        "Payment Ledger Entry": frappe.db.count("Payment Ledger Entry", {"company": m.COMPANY}),
        "Leave Ledger Entry": frappe.db.count(
            "Leave Ledger Entry", {"employee": in_demo(demo_employees)}),
        "Repost Item Valuation": frappe.db.count(
            "Repost Item Valuation",
            {"item_code": in_demo([code for code, _t, _s, _r in m.ITEMS])}),
        "File": frappe.db.count(
            "File", {"attached_to_doctype": "Employee",
                     "attached_to_name": in_demo(demo_employees)}),
        "Fiscal Year rows": sum(
            1 for year in frappe.get_all("Fiscal Year", pluck="name")
            if frappe.db.exists("Fiscal Year Company",
                                {"parent": year, "company": m.COMPANY})),
    }
    result["TOTAL"] = sum(result.values())
    return result


def _reset() -> None:
    deleted: dict = {}

    def wipe(doctype: str, names: list, purge_ledger: bool = False) -> None:
        if names:
            deleted[doctype] = deleted.get(doctype, 0) + _cancel_and_delete(
                doctype, names, purge_ledger)

    demo_employees = _pluck("Employee", {"company": m.COMPANY})
    demo_items = [code for code, _t, _s, _r in m.ITEMS]
    # 1. Submitted transactions first (cancel, purge their ledger rows, delete).
    wipe("Purchase Invoice", _pluck("Purchase Invoice", {"company": m.COMPANY}), purge_ledger=True)
    wipe("Purchase Receipt", _pluck("Purchase Receipt", {"company": m.COMPANY}), purge_ledger=True)
    wipe("Purchase Order", _pluck("Purchase Order", {"company": m.COMPANY}))
    wipe("Sales Invoice", _pluck("Sales Invoice", {"company": m.COMPANY}), purge_ledger=True)
    wipe("Payment Entry", _pluck("Payment Entry", {"company": m.COMPANY}), purge_ledger=True)
    wipe("Stock Entry", _pluck("Stock Entry", {"company": m.COMPANY}), purge_ledger=True)
    # Drafts created by the approved purchase/supply requests (they link their request).
    wipe("Material Request", _pluck("Material Request", {"company": m.COMPANY}))
    wipe("Attendance", _pluck("Attendance", {"company": m.COMPANY}))
    wipe("Leave Application", _pluck("Leave Application", {"company": m.COMPANY}))
    wipe("Leave Allocation", _pluck("Leave Allocation", {"company": m.COMPANY}))
    # Leave ledger rows are ERPNext-internal postings of the allocations and
    # applications above; purge exactly the demo employees' rows.
    if demo_employees:
        purged = frappe.db.count(
            "Leave Ledger Entry", {"employee": ["in", demo_employees]})
        frappe.db.sql("delete from `tabLeave Ledger Entry` where employee in %s",
                      [tuple(demo_employees)])
        deleted["Leave Ledger Entry"] = deleted.get("Leave Ledger Entry", 0) + purged
    wipe("Salary Structure Assignment", _pluck("Salary Structure Assignment",
                                               {"company": m.COMPANY}))
    wipe("Salary Slip", _pluck("Salary Slip", {"company": m.COMPANY}), purge_ledger=True)
    wipe("Payroll Entry", _pluck("Payroll Entry", {"company": m.COMPANY}))
    # 2. ASOUD workflow records of the demo company.
    definitions = _definition_names()
    instances = _demo_instance_names(definitions)
    # Activities reference their task, so they go before the tasks.
    wipe("ASOUD Workflow Activity", _pluck("ASOUD Workflow Activity",
                                           {"workflow_instance": ["in", instances] or [""]})
         if instances else [])
    wipe("ASOUD Workflow Task", _pluck("ASOUD Workflow Task",
                                       {"workflow_instance": ["in", instances] or [""]})
         if instances else [])
    # Requests and instances reference each other (Request.workflow_instance
    # and the instance's dynamic reference), so the link is cleared first.
    for request in _pluck("ASOUD Workflow Request", {"company": m.COMPANY}):
        _set_values("ASOUD Workflow Request", request, {"workflow_instance": None})
    wipe("ASOUD Workflow Instance", instances)
    requests = _pluck("ASOUD Workflow Request", {"company": m.COMPANY})
    # Native-document failures notify about the request itself.
    wipe("Notification Log", _pluck("Notification Log", {"document_type": "ASOUD Workflow Request",
                                                          "document_name": ["in", requests]})
         if requests else [])
    wipe("ASOUD Workflow Request", requests)
    wipe("Notification Log", _pluck("Notification Log",
                                    {"document_type": "ASOUD Workflow Instance",
                                     "document_name": ["in", instances] or [""]}) if instances else [])
    wipe("ASOUD Workflow Transition", _pluck("ASOUD Workflow Transition",
                                             {"workflow_definition": ["in", definitions]
                                              or [""]}) if definitions else [])
    wipe("ASOUD Workflow Stage", _pluck("ASOUD Workflow Stage",
                                        {"workflow_definition": ["in", definitions]
                                         or [""]}) if definitions else [])
    wipe("ASOUD Workflow Definition", definitions)
    # Older seeds had a native Workflow per demo request type. The system templates share one
    # Workflow across companies: it goes only when no definition of any company still uses it.
    wipe("Workflow", [f"{code}-NATIVE" for code in m.LEGACY_WORKFLOW_CODES])
    if _shared_workflow_unreferenced():
        wipe("Workflow", [m.SYSTEM_NATIVE_WORKFLOW])
    # Workflow States live in a shared namespace: another workflow on this
    # site may reference the demo state (e.g. stamps it on its own requests).
    # Remove it only when nothing else links it; never touch other data.
    try:
        wipe("Workflow State", [f"{m.PREFIX} Draft"])
    except frappe.LinkExistsError:
        SUMMARY.setdefault("kept", {})["Workflow State"] = f"{m.PREFIX} Draft"
    # 3. Personnel records, profiles, employees, users.
    demo_profiles = _pluck("ASOUD Party Profile", {"company": m.COMPANY})
    wipe("ASOUD Personnel Record", _pluck("ASOUD Personnel Record",
                                          {"party": ["in", demo_profiles] or [""]})
         if demo_profiles else [])
    wipe("ASOUD Personnel Operation", _pluck("ASOUD Personnel Operation",
                                             {"party": ["in", demo_profiles] or [""]})
         if demo_profiles else [])
    wipe("ASOUD Floating Detail", _pluck("ASOUD Floating Detail",
                                         {"linked_document": ["in", demo_profiles] or [""]})
         if demo_profiles else [])
    wipe("File", _pluck("File", {"attached_to_doctype": "Employee",
                                 "attached_to_name": ["in", demo_employees] or [""]})
         if demo_employees else [])
    wipe("Comment", frappe.get_all(
        "Comment", filters={"reference_doctype": "Employee",
                            "reference_name": ["in", demo_employees] or [""]},
        pluck="name", limit_page_length=0) if demo_employees else [])
    wipe("ASOUD Party Profile", demo_profiles)
    # Break the reports_to chain first: a manager cannot be deleted while
    # their reports still point at them. Scoped to demo employees only.
    for employee in demo_employees:
        _set_values("Employee", employee, {"reports_to": None})
    wipe("Employee", demo_employees)
    wipe("User", [m.demo_email(local) for local, _i, _r, _n in m.USERS])
    # 4. Trade masters and HR masters.
    # Cancelling stock vouchers spawns fresh Repost Item Valuation rows, so
    # they are wiped here, after every voucher is gone. A Queued repost
    # cannot be cancelled (and never runs where the scheduler is off), so
    # those rows are marked Failed first — reposting deleted vouchers is moot.
    for riv in _pluck("Repost Item Valuation", {"item_code": ["in", demo_items]}):
        if frappe.db.get_value("Repost Item Valuation", riv, "status") in ("Queued", "In Progress"):
            frappe.db.set_value("Repost Item Valuation", riv, "status", "Failed")
    wipe("Repost Item Valuation", _pluck("Repost Item Valuation",
                                         {"item_code": ["in", demo_items]}))
    wipe("Item", [code for code, _t, _s, _r in m.ITEMS])
    wipe("Customer", list(m.CUSTOMERS))
    wipe("Supplier", list(m.SUPPLIERS))
    # Parties reference the demo lists, and items cascade their prices.
    wipe("Price List", [m.PRICE_LIST_SELLING, m.PRICE_LIST_BUYING])
    wipe("Warehouse", frappe.get_all("Warehouse", filters={"company": m.COMPANY},
                                        pluck="name", order_by="lft desc",
                                        limit_page_length=0))
    wipe("Salary Structure", [m.SALARY_STRUCTURE])
    wipe("Salary Component", [m.SALARY_EARNING, m.SALARY_DEDUCTION])
    wipe("Leave Type", list(dict(m.LEAVE_TYPES).keys()))
    if frappe.db.exists("Company", m.COMPANY):
        # The company links its default holiday list; clear it before deleting the list.
        _set_values("Company", m.COMPANY, {"default_holiday_list": None})
    wipe("Holiday List", _pluck("Holiday List",
                                {"holiday_list_name": ["like", f"{m.HOLIDAY_LIST}%"]}))
    wipe("Designation", [name for name in m.DESIGNATIONS])
    # NestedSet: delete leaves before their parents.
    wipe("Department", frappe.get_all("Department", filters={"company": m.COMPANY},
                                      pluck="name", order_by="lft desc", limit_page_length=0))
    # 5. Fiscal year row, then the company itself.
    for year in frappe.get_all("Fiscal Year", pluck="name"):
        doc = frappe.get_doc("Fiscal Year", year)
        action = m.fiscal_year_reset_action(
            doc.name,
            doc.year_start_date,
            doc.year_end_date,
            [row.company for row in doc.companies],
            m.COMPANY,
        )
        if action == "keep":
            continue
        if action == "delete":
            frappe.delete_doc("Fiscal Year", year, ignore_permissions=True)
            deleted["Fiscal Year"] = deleted.get("Fiscal Year", 0) + 1
            continue
        for row in [row for row in doc.companies if row.company == m.COMPANY]:
            doc.remove(row)
        doc.save(ignore_permissions=True)
    wipe("ASOUD Company Setup", _pluck("ASOUD Company Setup", {"company": m.COMPANY}))
    if frappe.db.exists("Company", m.COMPANY):
        frappe.delete_doc("Company", m.COMPANY, ignore_permissions=True)
        deleted["Company"] = deleted.get("Company", 0) + 1
    SUMMARY["deleted"] = deleted
