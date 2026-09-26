"""Presentation templates only. Access remains native Frappe Role/Profile."""

CATEGORIES = [
    {"code": "MANAGERS", "title": "مدیران", "style": "managers"},
    {"code": "SYSTEM", "title": "مدیریت سیستم", "style": "system"},
    {"code": "FINANCE", "title": "مالی و حسابداری", "style": "finance"},
    {"code": "SALES", "title": "فروش و بازاریابی", "style": "sales"},
    {"code": "STOCK", "title": "انبار و کالا", "style": "stock"},
    {"code": "PURCHASE", "title": "خرید و تدارکات", "style": "purchase"},
    {"code": "HR", "title": "منابع انسانی", "style": "hr"},
    {"code": "EMPLOYEE", "title": "پرسنل", "style": "employee"},
]

BASE_ROLES = {
    "System Manager": ("مدیر سیستم", "مدیریت سراسری سامانه؛ دسترسی بسیار گسترده و حساس"),
    "Accounts Manager": ("مدیر مالی", "دسترسی‌های استاندارد مدیریت مالی ERPNext"),
    "Accounts User": ("کاربر حسابداری", "دسترسی‌های استاندارد حسابداری؛ محدود به خزانه نیست"),
    "Sales Manager": ("مدیر فروش", "مدیریت فروش طبق مجوزهای نصب‌شده ERPNext"),
    "Sales User": ("کاربر فروش", "عملیات فروش طبق مجوزهای نصب‌شده ERPNext"),
    "Purchase Manager": ("مدیر خرید", "مدیریت خرید طبق مجوزهای نصب‌شده ERPNext"),
    "Purchase User": ("کاربر خرید", "عملیات خرید طبق مجوزهای نصب‌شده ERPNext"),
    "Stock Manager": ("مدیر انبار", "مدیریت موجودی و عملیات انبار"),
    "Stock User": ("کاربر انبار", "عملیات استاندارد انبار و کالا"),
    "HR Manager": ("مدیر منابع انسانی", "مدیریت منابع انسانی طبق مجوزهای نصب‌شده HRMS"),
    "HR User": ("کارشناس منابع انسانی", "عملیات منابع انسانی طبق مجوزهای نصب‌شده HRMS"),
    "Payroll Manager": ("مدیر حقوق و دستمزد", "مجوزهای حساس حقوق و دستمزد در HRMS"),
    "Payroll Employee": ("پرسنل حقوق و دستمزد", "دسترسی استاندارد پرسنلی حقوق و دستمزد"),
    "Employee": ("پرسنل", "نقش استاندارد پرسنل؛ ارتباط کاربر با Employee باید جداگانه تنظیم شود"),
}

TEMPLATES = [
    ("SYSTEM_ADMIN", "مدیر سیستم", "SYSTEM", ["System Manager"]),
    ("FINANCE_MANAGER", "مدیر مالی", "FINANCE", ["Accounts Manager"]),
    ("ACCOUNTANT", "حسابدار", "FINANCE", ["Accounts User"]),
    ("SALES_MANAGER", "مدیر فروش", "SALES", ["Sales Manager"]),
    ("SALES_USER", "کارشناس فروش", "SALES", ["Sales User"]),
    ("PURCHASE_MANAGER", "مدیر خرید", "PURCHASE", ["Purchase Manager"]),
    ("PURCHASE_USER", "کارشناس خرید", "PURCHASE", ["Purchase User"]),
    ("STOCK_MANAGER", "مدیر انبار", "STOCK", ["Stock Manager"]),
    ("STOCK_USER", "انباردار", "STOCK", ["Stock User"]),
    ("HR_MANAGER", "مدیر منابع انسانی", "HR", ["HR Manager"]),
    ("HR_USER", "کارشناس منابع انسانی", "HR", ["HR User"]),
    ("PAYROLL_MANAGER", "مسئول حقوق و دستمزد", "FINANCE", ["Payroll Manager"]),
    ("EMPLOYEE", "پرسنل", "EMPLOYEE", ["Employee"]),
]
