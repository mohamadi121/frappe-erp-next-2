"""The permission matrix catalogue behind «دسترسی‌ها» with simple / medium / advanced levels (pure).

* simple   - one module-level switch: view the data of the module (``read`` only);
* medium   - per document type: view, create, edit, delete;
* advanced - medium plus the controlled operations: submit, cancel, amend (only for
  submittable document types), print, email, export, report, share, import.

Before this module the server returned the four medium actions only, so the app showed
the same list for «متوسط» and «پیشرفته». The server now states, per row, exactly which
actions each level contains (``levels``), and ``apply`` validates against that list.
"""

MEDIUM_ACTIONS = ("read", "create", "write", "delete")
SUBMIT_ACTIONS = ("submit", "cancel", "amend")
EXTRA_ACTIONS = ("print", "email", "export", "report", "share", "import")
ADVANCED_ONLY = SUBMIT_ACTIONS + EXTRA_ACTIONS
ALL_ACTIONS = MEDIUM_ACTIONS + ADVANCED_ONLY

ACTION_TITLES = {
    "read": "مشاهده", "create": "ایجاد", "write": "ویرایش", "delete": "حذف",
    "submit": "ثبت قطعی", "cancel": "لغو سند", "amend": "اصلاح سند", "print": "چاپ",
    "email": "ارسال ایمیل", "export": "خروجی", "report": "گزارش", "share": "اشتراک‌گذاری",
    "import": "ورود اطلاعات",
}

#: Read-only configuration screens expose just «read» in every level.
READ_ONLY_DOCTYPES = frozenset({"User", "System Settings"})

MODULES: dict[str, tuple[tuple[str, str], ...]] = {
    "حسابداری": (("Journal Entry", "سند حسابداری"), ("Payment Entry", "دریافت و پرداخت"), ("Account", "حساب‌ها")),
    "اشخاص و شرکت‌ها": (("Customer", "مشتریان"), ("Supplier", "تأمین‌کنندگان"), ("Contact", "مخاطبان")),
    "کالا و انبار": (("Item", "کالاها"), ("Warehouse", "انبارها"), ("Stock Entry", "ورود و خروج انبار")),
    "خرید": (("Material Request", "درخواست کالا"), ("Purchase Order", "سفارش خرید"), ("Purchase Invoice", "فاکتور خرید")),
    "فروش": (("Quotation", "پیش‌فاکتور"), ("Sales Order", "سفارش فروش"), ("Sales Invoice", "فاکتور فروش")),
    "منابع انسانی": (
        ("Employee", "پرسنل (پرونده پرسنلی)"),
        ("ASOUD Party Profile", "اشخاص و پرونده‌های شخصی"),
        ("Department", "واحدهای سازمانی"),
        ("Designation", "سمت‌ها"),
        ("Branch", "شعبه‌ها"),
        ("Employment Type", "انواع استخدام"),
        ("Holiday List", "تقویم تعطیلات"),
        ("Shift Type", "انواع شیفت"),
        ("Shift Assignment", "تخصیص شیفت"),
        ("Shift Request", "درخواست تغییر شیفت"),
        ("Employee Checkin", "تردد"),
        ("Attendance", "حضور و غیاب"),
        ("Attendance Request", "درخواست حضور"),
        ("Leave Type", "انواع مرخصی"),
        ("Leave Allocation", "تخصیص مرخصی"),
        ("Leave Application", "درخواست مرخصی"),
        ("Travel Request", "مأموریت"),
        ("Employee Advance", "مساعده"),
        ("Expense Claim", "هزینه‌های پرسنلی"),
        ("Salary Structure", "ساختار حقوق"),
        ("Salary Slip", "فیش حقوقی"),
        ("Payroll Entry", "محاسبه حقوق"),
        ("Additional Salary", "حقوق و کسورات اضافی"),
        ("Appraisal Cycle", "دوره ارزیابی"),
        ("Appraisal", "ارزیابی عملکرد"),
        ("Employee Promotion", "ارتقا"),
        ("Employee Transfer", "انتقال پرسنل"),
        ("Training Event", "رویداد آموزشی"),
        ("Exit Interview", "مصاحبه خروج"),
        ("Full and Final Statement", "تسویه حساب"),
        ("ASOUD Work Report", "گزارش کار"),
        ("ASOUD Internal Communication", "نامه‌ها و دستورات"),
        ("ASOUD Employee Invitation", "دعوت‌نامه حساب پرسنل"),
    ),
    "تنظیمات": (("System Settings", "تنظیمات سامانه"),),
    "مدیریت کاربران": (("User", "کاربران"),),
}


def levels_for(doctype: str, is_submittable: bool = False) -> dict[str, list[str]]:
    """The actions each level offers for one document type."""
    if doctype in READ_ONLY_DOCTYPES:
        return {"simple": ["read"], "medium": ["read"], "advanced": ["read"]}
    advanced = list(MEDIUM_ACTIONS)
    advanced += [a for a in SUBMIT_ACTIONS if is_submittable]
    advanced += list(EXTRA_ACTIONS)
    return {"simple": ["read"], "medium": list(MEDIUM_ACTIONS), "advanced": advanced}


def validate_grant(values, allowed: set[str]) -> str | None:
    """Persian refusal for a list of actions that is not allowed, or None."""
    if not isinstance(values, list) or any(not isinstance(a, str) or a not in allowed for a in values):
        return "عملیات دسترسی مجاز نیست."
    if values and "read" not in values:
        return "ایجاد، ویرایش، حذف و عملیات پیشرفته نیازمند مشاهده هستند."
    return None


def catalog_rows(exists, submittable) -> list[dict]:
    """Rows of the matrix; ``exists(doctype)``/``submittable(doctype)`` come from the site."""
    rows = []
    for module, items in MODULES.items():
        for doctype, title in items:
            if not exists(doctype):
                continue
            levels = levels_for(doctype, bool(submittable(doctype)))
            rows.append({
                "module": module, "doctype": doctype, "title": title,
                # `actions` is the legacy medium list; `advanced_actions` is what only «پیشرفته» adds.
                "actions": levels["medium"],
                "advanced_actions": [a for a in levels["advanced"] if a not in levels["medium"]],
                "levels": levels,
            })
    return rows


# --- ASOUD capabilities (the «what can this role do» layer on top of DocType rights) -----------------
#
# Each capability names the real server gate that enforces it. The system administrator holds
# every capability by definition (``System Manager`` is accepted by every gate); other
# roles hold a capability only through the roles listed in ``roles``.

ASOUD_CAPABILITIES: tuple[dict, ...] = (
    {"key": "offices.create", "module": "دفترهای کار", "title": "ایجاد دفتر",
     "gate": "setup.save_office (new)", "roles": ("System Manager", "ASOUD Office Creator")},
    {"key": "offices.view", "module": "دفترهای کار", "title": "مشاهده دفتر",
     "gate": "setup.get_setup_status", "roles": ("System Manager", "Accounts Manager", "Accounts User", "HR Manager")},
    {"key": "offices.edit", "module": "دفترهای کار", "title": "ویرایش دفتر",
     "gate": "setup.save_office (existing)", "roles": ("System Manager", "Accounts Manager")},
    {"key": "offices.manage", "module": "دفترهای کار", "title": "مدیریت دفتر و تنظیمات آن",
     "gate": "setup.update_company_settings", "roles": ("System Manager", "Accounts Manager")},
    {"key": "offices.access", "module": "دفترهای کار", "title": "مدیریت دسترسی دفتر",
     "gate": "role_access.assign_role", "roles": ("System Manager", "ASOUD Role Assigner")},
    {"key": "roles.manage", "module": "نقش‌ها و دسترسی‌ها", "title": "تعریف و ویرایش نقش و مجوز",
     "gate": "role_management.save_role / user_access.apply", "roles": ("System Manager",)},
    {"key": "roles.assign", "module": "نقش‌ها و دسترسی‌ها", "title": "اختصاص و حذف نقش کاربران",
     "gate": "role_access.assign_role", "roles": ("System Manager", "ASOUD Role Assigner")},
    {"key": "hr.personnel.view", "module": "منابع انسانی", "title": "مشاهده پرسنل",
     "gate": "personnel.list_personnel", "roles": ("System Manager", "HR Manager")},
    {"key": "hr.personnel.create", "module": "منابع انسانی", "title": "ایجاد پرسنل و حساب کاربری",
     "gate": "hr_onboarding.register_personnel", "roles": ("System Manager", "HR Manager")},
    {"key": "hr.personnel.edit", "module": "منابع انسانی", "title": "ویرایش پرسنل",
     "gate": "personnel.update_personnel", "roles": ("System Manager", "HR Manager")},
    {"key": "hr.reports.view", "module": "منابع انسانی", "title": "مشاهده گزارش‌های پرسنلی",
     "gate": "hr.review_report", "roles": ("System Manager", "HR Manager")},
    {"key": "hr.permissions.manage", "module": "منابع انسانی", "title": "مدیریت مجوزهای مرتبط",
     "gate": "auth.sync_employee_access", "roles": ("System Manager", "HR Manager")},
    {"key": "directives.issue", "module": "دستورات", "title": "صدور دستور",
     "gate": "directives.issue", "roles": ("System Manager", "Employee")},
    {"key": "directives.view", "module": "دستورات", "title": "مشاهده دستورات مجاز",
     "gate": "directives.get_directive", "roles": ("System Manager", "Employee")},
    {"key": "directives.refer", "module": "دستورات", "title": "ارجاع دستور",
     "gate": "directives.transfer", "roles": ("System Manager", "Employee")},
    {"key": "directives.reports", "module": "دستورات", "title": "مشاهده گزارش‌های دستور",
     "gate": "directives.reports", "roles": ("System Manager", "Employee")},
    {"key": "workreports.submit", "module": "گزارش کار", "title": "ارسال گزارش کار به مافوق",
     "gate": "hr.save_report", "roles": ("System Manager", "Employee")},
    {"key": "workreports.review", "module": "گزارش کار", "title": "بررسی گزارش کار",
     "gate": "hr.review_report", "roles": ("System Manager", "HR Manager")},
)


def capabilities_for(held_roles, is_admin: bool) -> list[dict]:
    held = set(held_roles or ())
    return [{"key": c["key"], "module": c["module"], "title": c["title"], "gate": c["gate"],
             "granted": bool(is_admin or held & set(c["roles"]))} for c in ASOUD_CAPABILITIES]
