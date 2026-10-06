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

# Demo price lists in the company currency. The site defaults
# ("Standard Selling"/"Standard Buying") are usually in the site currency,
# which would force a currency conversion on every demo invoice — and fail
# without an exchange rate. Parties point at these lists instead.
PRICE_LIST_SELLING = "ASOUD-DEMO Selling"
PRICE_LIST_BUYING = "ASOUD-DEMO Buying"

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


def fiscal_year_seed_action(company_rows: list, company: str) -> str:
    """How the seed must treat an existing Fiscal Year that covers today.

    A Fiscal Year without company rows applies to every company in ERPNext, so
    it already covers the demo company and must not be restricted.
    """
    if not company_rows:
        return "use"
    return "present" if company in company_rows else "append"


def fiscal_year_reset_action(name: str, start, end, company_rows: list, company: str) -> str:
    """What reset does with a Fiscal Year: ``keep``, ``remove_row`` or ``delete``.

    Only a year shaped exactly like the one the seed creates (named after its
    calendar year, Jan 1 - Dec 31) that holds nothing but the demo row is
    deleted. Anything else, including a shared year the seed only appended to,
    just loses the demo row, so a pre-existing Fiscal Year is never deleted.
    """
    if company not in company_rows:
        return "keep"
    year = str(start)[:4]
    seed_shaped = (
        name == year
        and str(start) == f"{year}-01-01"
        and str(end) == f"{year}-12-31"
    )
    if seed_shaped and set(company_rows) == {company}:
        return "delete"
    return "remove_row"
