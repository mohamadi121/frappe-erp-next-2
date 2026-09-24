"""Shared records for the API integration tests.

The site is prepared by ERPNext's and HRMS's ``before_tests`` hooks (setup
wizard company "Wind Power LLC"). Every record here is created once, with a
fixed name, and reused; each test runs in a transaction that is rolled back.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_year_ending, get_year_start, getdate, nowdate

ITEM = "ASOUD-TEST-ITEM"
SERVICE = "ASOUD-TEST-SERVICE"
CUSTOMER = "ASOUD Test Customer"
SUPPLIER = "ASOUD Test Supplier"
LEAVE_TYPE = "ASOUD Test Leave"
EXPENSE_TYPE = "ASOUD Test Expense"
EMPLOYEE_USER = "asoud.employee@example.com"
APPROVER_USER = "asoud.approver@example.com"
ACCOUNTANT_USER = "asoud.accountant@example.com"


def company() -> str:
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", pluck="name", limit=1)[0]


def abbr() -> str:
    return frappe.get_cached_value("Company", company(), "abbr")


def warehouse() -> str:
    return f"Stores - {abbr()}"


def leaf(doctype: str) -> str:
    """A non-group record of a tree DocType (Customer Group, Territory, ...)."""
    return frappe.get_all(doctype, filters={"is_group": 0}, pluck="name", order_by="lft asc", limit=1)[0]


def _ensure(doctype: str, name: str, values: dict) -> str:
    if not frappe.db.exists(doctype, name):
        frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
    return name


def _user(email: str, roles: list[str]) -> str:
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
                        "send_welcome_email": 0, "user_type": "System User",
                        "roles": [{"role": role} for role in roles]}).insert(ignore_permissions=True)
    return email


def _employee(user: str, first_name: str, **extra) -> str:
    name = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if name:
        return name
    return frappe.get_doc({
        "doctype": "Employee", "first_name": first_name, "gender": "Male",
        "date_of_birth": "1990-01-01", "date_of_joining": "2020-01-01", "company": company(),
        "status": "Active", "user_id": user, "create_user_permission": 0, **extra,
    }).insert(ignore_permissions=True).name


def _holiday_list() -> str:
    name = f"ASOUD Test Holidays {getdate().year}"
    _ensure("Holiday List", name, {"holiday_list_name": name, "from_date": get_year_start(nowdate()),
                                   "to_date": get_year_ending(nowdate())})
    frappe.db.set_value("Company", company(), "default_holiday_list", name)
    return name


def setup_records() -> dict:
    """Idempotently creates what the tests need and commits it."""
    frappe.set_user("Administrator")
    _ensure("Item", ITEM, {"item_code": ITEM, "item_name": "کالای آزمایشی", "item_group": leaf("Item Group"),
                           "stock_uom": "Nos", "is_stock_item": 1, "valuation_rate": 100,
                           "standard_rate": 250})
    _ensure("Item", SERVICE, {"item_code": SERVICE, "item_name": "خدمت آزمایشی",
                              "item_group": leaf("Item Group"), "stock_uom": "Nos", "is_stock_item": 0,
                              "standard_rate": 1000})
    # ERPNext's before_tests deletes every Item Price at the start of a run.
    for item_code, rate in ((ITEM, 250), (SERVICE, 1000)):
        if not frappe.db.exists("Item Price", {"item_code": item_code, "price_list": "Standard Selling"}):
            frappe.get_doc({"doctype": "Item Price", "item_code": item_code, "price_list": "Standard Selling",
                            "price_list_rate": rate}).insert(ignore_permissions=True)
    _ensure("Customer", CUSTOMER, {"customer_name": CUSTOMER, "customer_group": leaf("Customer Group"),
                                   "territory": leaf("Territory")})
    _ensure("Supplier", SUPPLIER, {"supplier_name": SUPPLIER, "supplier_group": leaf("Supplier Group")})
    cash = frappe.get_doc("Mode of Payment", "Cash")
    if not any(row.company == company() for row in cash.accounts):
        cash.append("accounts", {"company": company(), "default_account": f"Cash - {abbr()}"})
        cash.save(ignore_permissions=True)
    holidays = _holiday_list()
    # HRMS requires the employee advance account to be Receivable; the standard chart leaves it blank.
    advances = f"Employee Advances - {abbr()}"
    if frappe.db.exists("Account", advances):
        frappe.db.set_value("Account", advances, "account_type", "Receivable")
        frappe.db.set_value("Company", company(), "default_employee_advance_account", advances)
    _user(APPROVER_USER, ["Employee", "Leave Approver", "Expense Approver"])
    _user(EMPLOYEE_USER, ["Employee"])
    _user(ACCOUNTANT_USER, ["Accounts User", "Sales User", "Stock User", "Purchase User"])
    approver = _employee(APPROVER_USER, "Approver", holiday_list=holidays)
    employee = _employee(EMPLOYEE_USER, "Employee", holiday_list=holidays, leave_approver=APPROVER_USER,
                         expense_approver=APPROVER_USER, reports_to=approver)
    _employee(ACCOUNTANT_USER, "Accountant", holiday_list=holidays)
    _ensure("Leave Type", LEAVE_TYPE, {"leave_type_name": LEAVE_TYPE, "max_leaves_allowed": 30})
    if not frappe.db.exists("Leave Allocation", {"employee": employee, "leave_type": LEAVE_TYPE,
                                                 "docstatus": 1}):
        frappe.get_doc({"doctype": "Leave Allocation", "employee": employee, "leave_type": LEAVE_TYPE,
                        "from_date": get_year_start(nowdate()), "to_date": get_year_ending(nowdate()),
                        "new_leaves_allocated": 10}).submit()
    _ensure("Purpose of Travel", "ASOUD Mission", {"purpose_of_travel": "ASOUD Mission"})
    expense_account = frappe.get_all("Account", filters={"company": company(), "root_type": "Expense",
                                                         "is_group": 0}, pluck="name", limit=1)[0]
    _ensure("Expense Claim Type", EXPENSE_TYPE, {"expense_type": EXPENSE_TYPE, "accounts": [
        {"company": company(), "default_account": expense_account}]})
    frappe.db.commit()
    return {"company": company(), "employee": employee, "approver": approver}


class APITestCase(FrappeTestCase):
    """Rolls back everything a test wrote, and always returns to Administrator."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.records = setup_records()
        cls.company = cls.records["company"]

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def future(self, days: int = 7) -> str:
        return add_days(nowdate(), days)
