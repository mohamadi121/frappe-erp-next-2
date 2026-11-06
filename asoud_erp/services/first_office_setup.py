"""First-office account bootstrap; native User, password and company permissions."""

import re
from email.utils import parseaddr
from uuid import uuid4

from asoud_erp.services.credential_policy import clean_name, normalize_email, normalize_mobile

INTERNAL_SUFFIX = "@users.asoud.invalid"

ZXCVBN_WARNINGS_FA = {
    "This is similar to a commonly used password.": "این رمز شبیه یکی از رمزهای پرکاربرد است.",
    "This is a top-10 common password.": "این رمز جزو ۱۰ رمز عبور بسیار رایج و ناامن است.",
    "This is a top-100 common password.": "این رمز جزو ۱۰۰ رمز عبور بسیار رایج است.",
    "This is a very common password.": "این رمز جزو رمزهای عبور بسیار رایج است.",
    "Straight rows of keys are easy to guess.": "الگوهای ردیفی روی صفحه‌کلید به‌راحتی قابل حدس هستند.",
    "Short keyboard patterns are easy to guess.": "الگوهای کوتاه صفحه‌کلید به‌راحتی قابل حدس هستند.",
    'Repeats like "aaa" are easy to guess.': 'تکرار نویسه‌ها (مانند "aaa") به‌راحتی قابل حدس است.',
    'Repeats like "abcabcabc" are only slightly harder to guess than "abc".': 'تکرار الگوها به‌راحتی قابل حدس است.',
    'Sequences like "abc" or "6543" are easy to guess.': 'توالی حروف یا اعداد به‌راحتی قابل حدس است.',
    "Recent years are easy to guess.": "استفاده از سال‌های اخیر به‌راحتی قابل حدس است.",
    "Dates are often easy to guess.": "تاریخ‌ها به‌راحتی قابل حدس هستند.",
    "A word by itself is easy to guess.": "استفاده از یک کلمه به‌تنهایی به‌راحتی قابل حدس است.",
    "Names and surnames by themselves are easy to guess.": "نام و نام‌خانوادگی به‌تنهایی به‌راحتی قابل حدس است.",
    "Common names and surnames are easy to guess.": "نام‌ها و نام‌های خانوادگی رایج به‌راحتی قابل حدس هستند.",
}

ZXCVBN_SUGGESTIONS_FA = {
    "Add another word or two. Uncommon words are better.": "یک یا دو کلمه دیگر اضافه کنید؛ استفاده از کلمات غیرمعمول بهتر است.",
    "Use a few words, avoid common phrases.": "از ترکیب چند کلمه استفاده کنید و از عبارات رایج بپرهیزید.",
    "No need for symbols, digits, or uppercase letters.": "نیازی به نمادها، ارقام یا حروف بزرگ نیست.",
    "Use a longer keyboard pattern with more turns.": "از الگوهای پیچیده‌تر صفحه‌کلید با تغییر جهت استفاده کنید.",
    "Avoid repeated words and characters.": "از تکرار کلمات و نویسه‌ها بپرهیزید.",
    "Avoid sequences.": "از دنباله‌ها و توالی حروف یا اعداد بپرهیزید.",
    "Avoid recent years.": "از سال‌های اخیر بپرهیزید.",
    "Avoid years that are associated with you.": "از سال‌های مرتبط با خودتان بپرهیزید.",
    "Avoid dates and years that are associated with you.": "از تاریخ‌ها و سال‌های مرتبط با خود بپرهیزید.",
    "Capitalization doesn't help very much.": "بزرگ کردن حروف اول کمک چندانی به امنیت رمز نمی‌کند.",
    "All-uppercase is almost as easy to guess as all-lowercase.": "استفاده کامل از حروف بزرگ به‌اندازه حروف کوچک قابل حدس است.",
    "Reversed words aren't much harder to guess.": "معکوس کردن کلمات حدس زدن آنها را سخت‌تر نمی‌کند.",
    "Predictable substitutions like '@' instead of 'a' don't help very much.": "جایگزینی‌های قابل پیش‌بینی (مانند '@' به‌جای 'a') کمک چندانی نمی‌کنند.",
}


def format_password_policy_error(feedback: dict | None) -> str:
    """Format zxcvbn warning and suggestions into a Persian error message."""
    fb = feedback or {}
    warning_en = (fb.get("warning") or "").strip()
    suggestions_en = fb.get("suggestions") or []

    warning_fa = ZXCVBN_WARNINGS_FA.get(warning_en)
    if not warning_fa and warning_en:
        warning_fa = "این رمز به‌راحتی قابل حدس است."

    suggestions_fa = [
        ZXCVBN_SUGGESTIONS_FA[s]
        for s in suggestions_en
        if s and s in ZXCVBN_SUGGESTIONS_FA
    ]

    details = []
    if warning_fa:
        details.append(warning_fa)
    if suggestions_fa:
        details.append("پیشنهاد: " + " ".join(suggestions_fa))

    if details:
        return f"رمز موقت ضعیف است؛ {' '.join(details)}"
    return "رمز موقت ضعیف است؛ رمز قوی‌تری با حروف و نویسه‌های متنوع انتخاب کنید."


def internal_email(value):
    return parseaddr(str(value or ""))[1].lower().endswith(INTERNAL_SUFFIX)


def validate_lead_inputs(full_name, username, contact, temporary_password):
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
    if len(set(temporary_password)) < 4 or temporary_password.isdigit() or temporary_password.isspace():
        raise ValueError("رمز موقت ضعیف است؛ از حروف و نویسه‌های متنوع استفاده کنید.")
    return name, username, mail, mobile


def block_internal_mail(doc, method=None):
    """An internal User key is never a deliverable/verified contact address."""
    import frappe

    if any(internal_email(row.recipient) for row in doc.get("recipients") or []):
        frappe.throw("این حساب ایمیل تماس ندارد؛ اطلاعات ورود را امن و مستقیم تحویل دهید.")


def _setup(company, *, lock=False):
    import frappe

    from asoud_erp.services.request_access import require_company
    from asoud_erp.services.system_admin import is_system_admin

    if not is_system_admin():
        frappe.throw("این مرحله فقط برای مدیر سیستم مجاز است.", frappe.PermissionError)
    require_company(company)
    if company != frappe.db.get_single_value("ASOUD Settings", "first_office_company"):
        frappe.throw("این مسیر فقط برای راه‌اندازی اولین دفتر است.", frappe.PermissionError)
    if lock:
        # A locking current read settles provisioning before either status or retry
        # reads its pointer. Keep the wait below the client's network timeout.
        try:
            frappe.db.sql("SELECT name FROM tabCompany WHERE name=%s FOR UPDATE WAIT 3", (company,))
        except frappe.QueryTimeoutError:
            frappe.throw("ثبت مسئول منابع انسانی هنوز در جریان است؛ چند لحظه دیگر وضعیت را دوباره دریافت کنید.")
    if not frappe.get_meta("ASOUD Company Setup").has_field("first_hr_user"):
        frappe.throw("ابتدا به‌روزرسانی ساختار پایگاه دادهٔ سرور را اجرا کنید.")
    if not frappe.db.exists("ASOUD Company Setup", company):
        frappe.throw("دفتر کار هنوز ثبت نشده است.")
    doc = frappe.get_doc("ASOUD Company Setup", company, for_update=lock)
    if not doc.office_saved:
        frappe.throw("ابتدا دفتر کار را تکمیل کنید.")
    return doc


def _require_fiscal(company):
    import frappe

    years = frappe.get_all("Fiscal Year Company", filters={"company": company},
                           pluck="parent", limit_page_length=0)
    if not years or not frappe.db.exists("Fiscal Year", {"name": ["in", years], "disabled": 0}):
        frappe.throw("ابتدا سال مالی فعال این دفتر را ثبت کنید.")


def _summary(doc, *, idempotent_replay=False):
    import frappe

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
            "completed": bool(doc.bootstrap_completed), "idempotent_replay": idempotent_replay}


def status(company):
    return _summary(_setup(company, lock=True))


def create_hr_lead(company, full_name, username, contact, temporary_password):
    import frappe
    from frappe.core.doctype.user.user import test_password_strength
    from frappe.permissions import add_user_permission
    from frappe.utils.password import update_password

    from asoud_erp.services import account_state, security_audit

    doc = _setup(company, lock=True)
    _require_fiscal(company)
    if doc.first_hr_user:
        return _summary(doc, idempotent_replay=True)
    try:
        name, username, mail, mobile = validate_lead_inputs(
            full_name, username, contact, temporary_password
        )
    except ValueError as exc:
        frappe.throw(str(exc))
    # Serialise identity checks across simultaneous bootstrap requests.
    frappe.db.sql("select name from tabRole where name='HR Manager' for update")
    if not frappe.db.exists("Role", {"name": "HR Manager", "disabled": 0}):
        frappe.throw("نقش منابع انسانی در سرور فعال نیست.")
    if frappe.db.exists("User", {"username": username}):
        frappe.throw("نام کاربری قبلاً برای حساب دیگری ثبت شده است؛ نام دیگری انتخاب کنید.")
    if mail and frappe.db.exists("User", {"email": mail}):
        frappe.throw("ایمیل تماس قبلاً برای حساب دیگری ثبت شده است.")
    if mobile and frappe.db.exists("User", {"mobile_no": mobile}):
        frappe.throw("شماره موبایل قبلاً برای حساب دیگری ثبت شده است.")
    strength = test_password_strength(temporary_password, user_data=(name, username, mail or "", mobile or ""))
    feedback = strength.get("feedback") or {}
    if feedback.get("password_policy_validation_passed") is False:
        frappe.throw(format_password_policy_error(feedback))
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
    import frappe

    from asoud_erp.services import security_audit

    doc = _setup(company, lock=True)
    _require_fiscal(company)
    doc.flags.first_office_bootstrap = True
    doc.bootstrap_completed = 1
    doc.save(ignore_permissions=True)
    frappe.defaults.set_user_default("company", company)
    security_audit.record("office.bootstrap_complete", target_type="Company", target=company, company=company)
    return _summary(doc)
