"""Shared constants and pure guard helpers for the demo seed command.

This module must stay free of ``frappe`` imports so its naming and safety
rules can be unit-tested with plain pytest (see ``asoud_erp/tests``).

Records created by ``asoud_erp.demo.seed`` are identified for reset by:

- the demo company (``COMPANY``): every company-scoped record
  (departments, employees, warehouses, invoices, attendance, leave,
  salary, workflow definitions/requests, party profiles) carries it;
- a technical prefix (``PREFIX``) for shared/global records whose DocType
  has no company field (items, salary components, native workflows);
- Persian display names containing ``FA_MARKER`` where the phone shows the
  record name (designations, leave types, salary structure, customers,
  suppliers, holiday lists).
"""

COMPANY = "شرکت نمونه آسود"
ABBR = "ASDM"
CURRENCY = "IRR"
COUNTRY = "Iran"
CHART_OF_ACCOUNTS = "Standard"

# Technical marker for codes and global DocTypes without a company field.
PREFIX = "ASOUD-DEMO"
# Display marker inside Persian names shown on the phone.
FA_MARKER = "نمونه آسود"

EMAIL_DOMAIN = "asoud-demo.local"

DEPARTMENTS = ["فروش", "مالی", "فناوری اطلاعات", "اداری و منابع انسانی"]

DESIGNATIONS = [
    "مدیرعامل (نمونه آسود)",
    "مدیر فروش (نمونه آسود)",
    "مدیر مالی (نمونه آسود)",
    "مدیر فناوری اطلاعات (نمونه آسود)",
    "مسئول اداری و منابع انسانی (نمونه آسود)",
    "کارشناس فروش (نمونه آسود)",
    "کارشناس مالی (نمونه آسود)",
    "کارشناس فناوری اطلاعات (نمونه آسود)",
    "کارشناس اداری (نمونه آسود)",
]

# (display name, department index into DEPARTMENTS, designation index,
#  reports_to index into EMPLOYEES or None, gender)
EMPLOYEES: list = [
    ("رضا محمدی", None, 0, None, "Male"),
    ("سارا احمدی", 0, 1, 0, "Female"),
    ("علی کریمی", 1, 2, 0, "Male"),
    ("مریم حسینی", 2, 3, 0, "Female"),
    ("حسین رضایی", 3, 4, 0, "Male"),
    ("نگار موسوی", 0, 5, 1, "Female"),
    ("امید صادقی", 0, 5, 1, "Male"),
    ("لیلا نادری", 1, 6, 2, "Female"),
    ("کیان مرادی", 2, 7, 3, "Male"),
    ("شیرین قاسمی", 2, 7, 3, "Female"),
    ("آرش فرهادی", 3, 8, 4, "Male"),
    ("بهنام عزیزی", 3, 8, 4, "Male"),
]

# (email local part, employee index, roles, note)
# The last user is created but never signed in, for the resend-invitation case.
USERS: list = [
    ("hr-manager", 4, ["HR Manager", "Employee"], "HR Manager"),
    ("sales-manager", 1, ["Sales Manager", "Employee"], "manager"),
    ("employee", 5, ["Employee"], "employee"),
    ("newcomer", 11, ["Employee"], "never logged in"),
]

LEAVE_TYPES = [
    ("مرخصی استحقاقی نمونه آسود", 30),
    ("مرخصی استعلاجی نمونه آسود", 10),
]

SALARY_EARNING = "حقوق پایه نمونه آسود"
SALARY_EARNING_ABBR = "ASDB"
SALARY_DEDUCTION = "کسور بیمه نمونه آسود"
SALARY_DEDUCTION_ABBR = "ASDI"
SALARY_STRUCTURE = "ساختار حقوق نمونه آسود"
SALARY_BASE = 58000000

ITEMS = [
    ("ASOUD-DEMO-ITEM-01", "کالای نمونه آسود ۱", 1, 1500000),
    ("ASOUD-DEMO-ITEM-02", "کالای نمونه آسود ۲", 1, 2800000),
    ("ASOUD-DEMO-ITEM-03", "کالای نمونه آسود ۳", 1, 950000),
    ("ASOUD-DEMO-SERVICE-01", "خدمت نمونه آسود ۱", 0, 5000000),
]

CUSTOMERS = ["مشتری نمونه آسود ۱", "مشتری نمونه آسود ۲", "مشتری نمونه آسود ۳"]
SUPPLIERS = ["تأمین‌کننده نمونه آسود ۱", "تأمین‌کننده نمونه آسود ۲"]

HOLIDAY_LIST = "تعطیلات نمونه آسود"

WORKFLOW_LEAVE_CODE = "ASOUD-DEMO-LEAVE"
WORKFLOW_LEAVE_TITLE = "درخواست مرخصی نمونه"
WORKFLOW_PURCHASE_CODE = "ASOUD-DEMO-PURCHASE"
WORKFLOW_PURCHASE_TITLE = "درخواست خرید نمونه"

# Fixed request_ids make request creation idempotent by itself.
REQUEST_IDS = {
    "leave-approved": "asoud-demo-req-leave-approved",
    "leave-pending": "asoud-demo-req-leave-pending",
    "purchase-rejected": "asoud-demo-req-purchase-rejected",
    "leave-cancelled": "asoud-demo-req-leave-cancelled",
}

PURCHASE_BILL_NO = "ASOUD-DEMO-B-1"


def demo_email(local_part: str) -> str:
    return f"{local_part}@{EMAIL_DOMAIN}"


def site_allowed(site: str | None) -> bool:
    """Only test/demo sites may be seeded, so real data is never touched."""
    name = (site or "").lower()
    return "test" in name or "demo" in name


def guard_error(site: str | None, developer_mode: bool, force: bool) -> str | None:
    """Pure safety check for the seed command.

    Returns an error message when the command must refuse to run, else None.
    ``force=True`` bypasses both guards (explicit operator override).
    """
    if force:
        return None
    if not site_allowed(site):
        return (
            f"Refusing to seed site '{site}': "
            "the demo seed only runs on sites whose name contains "
            "'test' or 'demo' (pass force=True to override)."
        )
    if not developer_mode:
        return (
            "Refusing to seed: developer_mode is off "
            "(pass force=True to override)."
        )
    return None
