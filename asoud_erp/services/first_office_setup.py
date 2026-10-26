"""First-office account bootstrap; native User, password and company permissions."""

import re
from email.utils import parseaddr
from uuid import uuid4

import frappe

from asoud_erp.services import account_state, security_audit
from asoud_erp.services.credential_policy import clean_name, normalize_email, normalize_mobile
from asoud_erp.services.request_access import require_company
from asoud_erp.services.system_admin import is_system_admin

INTERNAL_SUFFIX = "@users.asoud.invalid"


def internal_email(value):
    return parseaddr(str(value or ""))[1].lower().endswith(INTERNAL_SUFFIX)


def block_internal_mail(doc, method=None):
    """An internal User key is never a deliverable/verified contact address."""
    if any(internal_email(row.recipient) for row in doc.get("recipients") or []):
        frappe.throw("این حساب ایمیل تماس ندارد؛ اطلاعات ورود را امن و مستقیم تحویل دهید.")


def _setup(company, *, lock=False):
    if not is_system_admin():
        frappe.throw("این مرحله فقط برای مدیر سیستم مجاز است.", frappe.PermissionError)
    require_company(company)
    if company != frappe.db.get_single_value("ASOUD Settings", "first_office_company"):
        frappe.throw("این مسیر فقط برای راه‌اندازی اولین دفتر است.", frappe.PermissionError)
    if not frappe.get_meta("ASOUD Company Setup").has_field("first_hr_user"):
        frappe.throw("ابتدا به‌روزرسانی ساختار پایگاه دادهٔ سرور را اجرا کنید.")
    if not frappe.db.exists("ASOUD Company Setup", company):
        frappe.throw("دفتر کار هنوز ثبت نشده است.")
    doc = frappe.get_doc("ASOUD Company Setup", company, for_update=lock)
    if not doc.office_saved:
        frappe.throw("ابتدا دفتر کار را تکمیل کنید.")
    return doc


def _require_fiscal(company):
    years = frappe.get_all("Fiscal Year Company", filters={"company": company},
                           pluck="parent", limit_page_length=0)
    if not years or not frappe.db.exists("Fiscal Year", {"name": ["in", years], "disabled": 0}):
        frappe.throw("ابتدا سال مالی فعال این دفتر را ثبت کنید.")


def _summary(doc):
    lead = None
    ready = False
    if doc.first_hr_user:
        row = frappe.db.get_value("User", doc.first_hr_user,
                                  ["full_name", "username", "enabled", "user_type"], as_dict=True)
        if row:
            lead = {"full_name": row.full_name, "username": row.username,
                    "role_title": "مسئول منابع انسانی"}
            ready = bool(row.enabled and row.user_type == "System User" and row.username
                         and "HR Manager" in frappe.get_roles(doc.first_hr_user)
                         and frappe.db.get_single_value("System Settings", "allow_login_using_user_name")
                         and frappe.db.exists("User Permission", {"user": doc.first_hr_user,
                             "allow": "Company", "for_value": doc.company, "apply_to_all_doctypes": 1}))
    return {"company": doc.company, "hr_lead": lead, "hr_ready": ready,
            "completed": bool(doc.bootstrap_completed)}


def status(company):
    return _summary(_setup(company))


def create_hr_lead(company, full_name, username, contact, temporary_password):
    from frappe.permissions import add_user_permission
    from frappe.utils.password import update_password

    doc = _setup(company, lock=True)
    _require_fiscal(company)
    if doc.first_hr_user:
        return _summary(doc)  # Retry never changes an existing password/account.
    try:
        name = clean_name(full_name, "نام و نام خانوادگی")
        username = str(username or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,39}", username) or username in {"administrator", "guest", "admin"}:
            raise ValueError("نام کاربری باید ۳ تا ۴۰ حرف انگلیسی، عدد یا زیرخط باشد و با حرف شروع شود.")
        contact = str(contact or "").strip()
        mail = normalize_email(contact) if "@" in contact else None
        mobile = None if mail else normalize_mobile(contact)
        if not mail and not mobile:
            raise ValueError("شماره موبایل یا ایمیل را وارد کنید.")
        if internal_email(mail):
            raise ValueError("ایمیل تماس واقعی وارد کنید.")
        if not isinstance(temporary_password, str) or not 8 <= len(temporary_password) <= 128:
            raise ValueError("رمز موقت باید بین ۸ تا ۱۲۸ نویسه باشد.")
    except ValueError as exc:
        frappe.throw(str(exc))
    # Serialise identity checks across simultaneous bootstrap requests.
    frappe.db.sql("select name from tabRole where name='HR Manager' for update")
    if not frappe.db.exists("Role", {"name": "HR Manager", "disabled": 0}):
        frappe.throw("نقش منابع انسانی در سرور فعال نیست.")
    if (frappe.db.exists("User", {"username": username})
            or (mail and frappe.db.exists("User", {"email": mail}))
            or (mobile and frappe.db.exists("User", {"mobile_no": mobile}))):
        frappe.throw("نام کاربری یا اطلاعات تماس قبلاً برای حساب دیگری ثبت شده است.")
    user = frappe.get_doc({"doctype": "User", "email": mail or f"{uuid4().hex}{INTERNAL_SUFFIX}",
        "first_name": name, "username": username, "mobile_no": mobile,
        "enabled": 1, "user_type": "System User", "send_welcome_email": 0,
        "thread_notify": 0, "follow_assigned_documents": 0,
        "roles": [{"role": "HR Manager"}]})
    # Explicit administrator-only provisioning, not a missing-permissions fallback.
    user.insert(ignore_permissions=True)
    update_password(user.name, temporary_password)
    account_state.set_must_change(user.name, True, expires_in_hours=72)
    add_user_permission("Company", company, user.name, ignore_permissions=True)
    settings = frappe.get_single("System Settings")
    if not settings.allow_login_using_user_name:
        settings.allow_login_using_user_name = 1
        settings.save(ignore_permissions=True)
    doc.flags.first_office_bootstrap = True
    doc.first_hr_user = user.name
    doc.save(ignore_permissions=True)
    frappe.clear_cache(user=user.name)
    security_audit.record("office.first_hr_account", target_type="User", target=user.name,
                          company=company, details={"role": "HR Manager", "personnel_created": False})
    return _summary(doc)


def complete(company):
    doc = _setup(company, lock=True)
    _require_fiscal(company)
    if not _summary(doc)["hr_ready"]:
        frappe.throw("حساب فعال مسئول منابع انسانی و دسترسی دفتر باید تأیید شود.")
    doc.flags.first_office_bootstrap = True
    doc.bootstrap_completed = 1
    doc.save(ignore_permissions=True)
    frappe.defaults.set_user_default("company", company)
    security_audit.record("office.bootstrap_complete", target_type="Company", target=company, company=company)
    return _summary(doc)
