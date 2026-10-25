"""HR onboarding: person -> personnel file -> login account -> role -> secure activation.

Reuses what exists instead of creating a parallel path:
* the person is an ``ASOUD Party Profile`` (found by login link / Employee link / national id);
* the personnel file is the ERPNext ``Employee`` created by ``party._ensure_employee``;
* the account is created or linked by ``auth.sync_employee_access`` (no duplicate User,
  no second Employee for one login);
* tafsili codes are made only on request, only through ``party._sync_floating_details``
  (the existing accounting coding).
"""

import secrets
import string

import frappe

from asoud_erp.services import account_recovery, account_state, security_audit
from asoud_erp.services.credential_policy import (
    clean_name,
    normalize_email,
    normalize_mobile,
    normalize_national_id,
)
from asoud_erp.services.delegation import DELEGATE_ROLE
from asoud_erp.services.system_admin import is_system_admin

TEMP_PASSWORD_HOURS = 72


def temporary_password() -> str:
    """14 random characters guaranteed to satisfy the policy."""
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%*-_"]
    chars = [secrets.choice(pool) for pool in pools]
    chars += [secrets.choice("".join(pools)) for _ in range(10)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def find_person(national_id: str | None, mobile: str | None, user: str | None):
    """The existing ASOUD Party Profile of this human, or None. Never matches on a weak key alone
    when it would merge two different people."""
    if user:
        name = frappe.db.get_value("ASOUD Party Profile", {"user": user}, "name")
        if name:
            return name
    if national_id:
        name = frappe.db.get_value("ASOUD Party Profile", {"national_id": national_id}, "name")
        if name:
            return name
    if mobile:
        names = frappe.get_all("ASOUD Party Profile", filters={"mobile": mobile}, pluck="name",
                               limit_page_length=2)
        if len(names) == 1 and not national_id:
            return names[0]
    return None


def _register_gate(company: str) -> None:
    from asoud_erp.services.erp_documents import require_roles
    from asoud_erp.services.request_access import require_company

    require_roles(("System Manager", "HR Manager"), company=company)
    require_company(company)


def register(company, first_name, last_name, mobile, email, *, national_id=None, gender=None,
             birth_date=None, date_of_joining=None, job_title=None, department=None, roles=None,
             activation="invite", detail_groups=None, hr_lead=False, request_id=None) -> dict:
    """Idempotent personnel registration. Returns ids, never a stored secret (a temporary password
    appears exactly once, in this response)."""
    from asoud_erp.api.v1 import auth, party
    from asoud_erp.api.v1.role_management import _lock_definitions
    from asoud_erp.services.role_assignment_service import assign

    actor = frappe.session.user
    admin = is_system_admin(actor)
    _register_gate(company)
    if hr_lead and not admin:
        frappe.throw("تعیین اولین مسئول منابع انسانی فقط توسط مدیر کل سیستم انجام می‌شود.", frappe.PermissionError)
    if activation not in ("invite", "temporary_password"):
        frappe.throw("روش فعال‌سازی معتبر نیست.")
    try:
        first = clean_name(first_name, "نام")
        last = clean_name(last_name, "نام خانوادگی")
        mobile_n = normalize_mobile(mobile)
        nid = normalize_national_id(national_id)
        mail = normalize_email(email)
    except ValueError as exc:
        frappe.throw(str(exc), frappe.ValidationError)
    if not mail:
        frappe.throw("ایمیل ورود پرسنل الزامی است (نام کاربری حساب).", frappe.ValidationError)
    if not mobile_n:
        frappe.throw("شماره موبایل الزامی است.", frappe.ValidationError)
    if not frappe.db.exists("Company", company):
        frappe.throw("دفتر یافت نشد.")

    if not employee_exists_for(mail) and not (gender and birth_date and date_of_joining):
        frappe.throw("جنسیت، تاریخ تولد و تاریخ شروع به کار برای ایجاد پرونده پرسنلی الزامی است.",
                     frappe.ValidationError)

    # Everything below is serialised: two simultaneous registrations of the same person must
    # end with exactly one Person, one Employee and one User.
    _lock_definitions()
    if request_id:
        done = frappe.db.get_value("ASOUD Personnel Operation", {"request_id": request_id},
                                   ["party", "action"], as_dict=True)
        if done and done.action == "register_personnel":
            return replay(done.party, mail)

    existing_user = frappe.db.get_value("User", mail, ["name", "enabled"], as_dict=True)
    person = find_person(nid, mobile_n, existing_user.name if existing_user else None)
    employee_name = None
    if person:
        profile = frappe.get_doc("ASOUD Party Profile", person, for_update=True)
        if profile.employee:
            emp = frappe.db.get_value("Employee", profile.employee, ["company", "user_id", "status"], as_dict=True)
            if emp and emp.company != company:
                frappe.throw("این شخص پرسنل دفتر دیگری است؛ پرونده پرسنلی تکراری ساخته نمی‌شود.",
                             frappe.ValidationError)
            employee_name = profile.employee
            if emp and emp.user_id and emp.user_id != mail:
                frappe.throw("این پرسنل قبلاً به حساب کاربری دیگری متصل است.", frappe.ValidationError)
    else:
        profile = frappe.new_doc("ASOUD Party Profile")

    title = f"{first} {last}"
    profile.update({"party_type": "Individual", "display_name": title, "company": company, "mobile": mobile_n,
                    "email": mail, "national_id": nid or profile.get("national_id"),
                    "employee_gender": gender or profile.get("employee_gender"),
                    "birth_date": birth_date or profile.get("birth_date"),
                    "date_of_joining": date_of_joining or profile.get("date_of_joining"),
                    "job_title": job_title or profile.get("job_title"),
                    "department": department or profile.get("department")})
    roles_text = ["Employee"]
    profile.roles_text = frappe.as_json(roles_text)
    from asoud_erp.services.role_assignment_service import precheck

    for code in roles or []:
        precheck(code, company)  # escalation / scope refusal happens before anything is written
    frappe.db.savepoint("asoud_register_personnel")
    # The system administrator holds no native Employee right; creating the very first HR lead is
    # authorised above (admin-only), so the personnel writes run as the site superuser for this block.
    elevated = bool(hr_lead and admin)
    if elevated:
        frappe.set_user("Administrator")
    try:
        profile.employee = party._ensure_employee(
            employee_name, title, company, profile.employee_gender, profile.birth_date,
            profile.date_of_joining, mobile_n, mail)
        # The explicit HR gate above authorises this write (HR Manager has no create right on the
        # party DocType, by design: the profile is only ever made through this audited path).
        if profile.is_new():
            profile.insert(ignore_permissions=True)
        else:
            profile.save(ignore_permissions=True)
        result = auth.sync_employee_access(profile.name, mail, ["employee"])["data"]
        user = result["user_id"]
        profile.db_set("user", user)
        if mobile_n and not frappe.db.exists("User", {"mobile_no": mobile_n, "name": ["!=", user]}):
            frappe.db.set_value("User", user, "mobile_no", mobile_n)
        granted = []
        for code in roles or []:
            granted.append(assign(user, code, company if _scope_of(code) == "office" else None))
        if hr_lead:
            _grant_native(user, "HR Manager")
        groups = list(detail_groups or [])
        if groups:
            _tafsili(party, profile, title, groups)
        activation_info = _activate(user, mail, activation)
        if request_id:
            frappe.get_doc({"doctype": "ASOUD Personnel Operation", "party": profile.name,
                            "request_id": request_id, "action": "register_personnel",
                            "fingerprint": profile.name}).insert(ignore_permissions=True)
    except Exception:
        try:
            frappe.db.rollback(save_point="asoud_register_personnel")
        except Exception:
            pass
        raise
    finally:
        if elevated:
            frappe.set_user(actor)
    security_audit.record("hr.personnel_register" if not hr_lead else "hr.first_lead_register",
                          target_type="ASOUD Party Profile", target=profile.name, company=company,
                          details={"employee": profile.employee, "user": user, "reused_person": bool(person),
                                   "activation": activation, "roles": list(roles or [])})
    return {"person": profile.name, "employee": profile.employee, "user": user, "company": company,
            "reused_person": bool(person), "account_created": not bool(existing_user),
            "roles": granted, "activation": activation_info, "hr_lead": bool(hr_lead)}


def employee_exists_for(mail: str) -> bool:
    return bool(frappe.db.exists("Employee", {"user_id": mail}))


def replay(person: str, mail: str) -> dict:
    profile = frappe.db.get_value("ASOUD Party Profile", person, ["employee", "user", "company"], as_dict=True)
    return {"person": person, "employee": profile.employee, "user": profile.user, "company": profile.company,
            "replayed": True, "activation": {"method": None}}


def _scope_of(code: str) -> str:
    return frappe.db.get_value("ASOUD Role Definition", code, "scope") or "global"


def _grant_native(user: str, role: str) -> None:
    doc = frappe.get_doc("User", user)
    if role not in {r.role for r in doc.roles}:
        doc.append("roles", {"role": role})
        doc.save(ignore_permissions=True)


def _tafsili(party, profile, title, groups) -> None:
    allowed = {"System Manager", "Accounts Manager", "Accounts User"}
    if not allowed & set(frappe.get_roles()):
        frappe.throw("ایجاد کد تفصیلی نیازمند دسترسی حسابداری است.", frappe.PermissionError)
    groups = party._parse_detail_groups(groups)
    party._sync_floating_details(profile.name, title, ["Employee"], primary_role="Employee",
                                 detail_groups=groups)


def _activate(user: str, mail: str, method: str) -> dict:
    state = account_state.ensure(user, lock=True)
    state.activation_pending = 1
    state.save(ignore_permissions=True)
    if method == "temporary_password":
        from frappe.utils.password import update_password

        password = temporary_password()
        update_password(user, password)
        account_state.set_must_change(user, True, expires_in_hours=TEMP_PASSWORD_HOURS)
        security_audit.record("account.temporary_password_issue", target_type="User", target=user)
        return {"method": "temporary_password", "temporary_password": password,
                "expires_in_hours": TEMP_PASSWORD_HOURS, "must_change_on_first_login": True,
                "note": "این رمز فقط همین یک بار نمایش داده می‌شود."}
    if not account_recovery.recovery_available():
        frappe.throw("برای ارسال دعوت‌نامه، حساب ایمیل خروجی تنظیم نشده است؛ از روش رمز موقت استفاده کنید.",
                     frappe.ValidationError)
    code = account_recovery.issue(user, "activation")
    frappe.sendmail(
        recipients=[mail], subject="فعال‌سازی حساب آسود",
        message=(f"<p>برای فعال‌سازی حساب خود در آسود، کد زیر را در برنامه وارد کنید و رمز شخصی خود را تعیین کنید:"
                 f"</p><p><b dir='ltr'>{code}</b></p><p>این کد تا {account_recovery.TTL_MINUTES['activation'] // 60} "
                 "ساعت معتبر و یک‌بارمصرف است.</p>"), now=True)
    security_audit.record("account.invitation_send", target_type="User", target=user)
    return {"method": "invite", "expires_in_hours": account_recovery.TTL_MINUTES["activation"] // 60,
            "sent_to": mail[:2] + "***" + mail[mail.index("@"):]}


def issue_temporary_password(person: str) -> dict:
    """Re-issue a temporary password for personnel whose account never signed in (HR / admin)."""
    from asoud_erp.services.request_access import require_company

    profile = frappe.db.get_value("ASOUD Party Profile", person, ["company", "user", "employee"], as_dict=True)
    if not profile or not profile.user:
        frappe.throw("برای این پرسنل حساب کاربری وجود ندارد.")
    require_company(profile.company)
    from asoud_erp.services.erp_documents import require_roles

    require_roles(("System Manager", "HR Manager"), company=profile.company)
    if profile.user == frappe.session.user:
        frappe.throw("برای حساب خودتان از «تغییر رمز عبور» استفاده کنید.", frappe.PermissionError)
    if {"System Manager"} & set(frappe.get_roles(profile.user)) and not is_system_admin():
        frappe.throw("حساب مدیر کل را فقط مدیر کل سیستم می‌تواند مدیریت کند.", frappe.PermissionError)
    return _activate(profile.user, "", "temporary_password")


__all__ = ["register", "issue_temporary_password", "DELEGATE_ROLE"]
