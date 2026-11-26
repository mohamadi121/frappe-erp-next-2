"""First-run flow: first office and the system administrator's essential profile."""

import json

import frappe
from frappe.utils import now_datetime

from asoud_erp.services import account_state, security_audit
from asoud_erp.services.credential_policy import (
    clean_name,
    normalize_email,
    normalize_mobile,
    normalize_national_id,
)
from asoud_erp.services.digits import normalize_numeric_text
from asoud_erp.services.login_state import first_office_exists
from asoud_erp.services.personnel_contract import validate_profile_update
from asoud_erp.services.system_admin import is_system_admin

NOT_ADMIN = "این مرحله فقط برای مدیر کل سیستم است."
ADMIN_PERSONAL_FIELDS = {"father_name": 140, "birth_date": 10, "phone": 11,
                         "address_line": 2000, "postal_code": 10}


def own_admin_person(user: str):
    """Use the first-login identity link, not an office, name or national-ID match."""
    if not is_system_admin(user):
        return None
    name = frappe.db.get_value("ASOUD Party Profile", {"user": user}, "name")
    return frappe.get_doc("ASOUD Party Profile", name) if name else None


def require_admin() -> str:
    user = frappe.session.user
    if not is_system_admin(user):
        security_audit.record("onboarding.denied", result="denied", details={"reason": "not_system_admin"},
                              commit=True)
        frappe.throw(NOT_ADMIN, frappe.PermissionError)
    return user


def lock_bootstrap() -> None:
    # One global lock for first-office creation; held until the request commits.
    frappe.db.sql("select name from tabRole where name=%s for update", ("System Manager",))


def first_office_record() -> dict | None:
    settings = frappe.get_single("ASOUD Settings")
    company = settings.first_office_company or frappe.db.get_value(
        "ASOUD Company Setup", {"office_saved": 1}, "company", order_by="creation asc")
    return {"company": company} if company else None


def mark_first_office(company: str, user: str) -> None:
    settings = frappe.get_single("ASOUD Settings")
    settings.first_office_company = company
    settings.first_office_created_by = user
    settings.first_office_created_on = now_datetime()
    settings.save(ignore_permissions=True)
    frappe.db.set_value("ASOUD Company Setup", company, "office_admin", user, update_modified=False)
    frappe.defaults.set_user_default("company", company, user=user)


# --- admin profile -----------------------------------------------------------------------


def person_for_user(user: str, national_id: str | None):
    """The ASOUD Party Profile of this account: linked, via its Employee, or by national id."""
    name = frappe.db.get_value("ASOUD Party Profile", {"user": user}, "name")
    if name:
        return name
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if employee:
        name = frappe.db.get_value("ASOUD Party Profile", {"employee": employee}, "name")
        if name:
            return name
    if national_id:
        name = frappe.db.get_value("ASOUD Party Profile", {"national_id": national_id}, "name")
        if name:
            linked = frappe.db.get_value("ASOUD Party Profile", name, "user")
            if linked and linked != user:
                frappe.throw("این کد ملی برای شخص دیگری با حساب کاربری دیگر ثبت شده است.", frappe.ValidationError)
            return name
    return None


def read_admin_profile(user: str) -> dict:
    row = frappe.db.get_value("User", user, ["first_name", "last_name", "mobile_no", "enabled"], as_dict=True)
    person = person_for_user(user, None)
    profile = frappe.db.get_value("ASOUD Party Profile", person,
                                  ["national_id", "email", *ADMIN_PERSONAL_FIELDS], as_dict=True) if person else None
    national_id = profile.national_id if profile else None
    state = account_state.get(user)
    return {
        "username": user, "role": "مدیر کل سیستم", "active": bool(row.enabled),
        "first_name": row.first_name or "", "last_name": row.last_name or "",
        "mobile": row.mobile_no or "", "national_id": national_id or "",
        "email": (profile.email if profile else "") or "",
        "personal_details": {key: str(profile.get(key) or "") for key in ADMIN_PERSONAL_FIELDS} if profile else {},
        "mobile_verified": bool(state.get("mobile_verified")), "email_verified": bool(state.get("email_verified")),
        "completed": bool(row.first_name and row.last_name and row.mobile_no),
    }


def save_admin_profile(first_name, last_name, mobile, national_id=None, email=None, personal_details=None) -> dict:
    user = require_admin()
    try:
        first = clean_name(first_name, "نام")
        last = clean_name(last_name, "نام خانوادگی")
        mobile_n = normalize_mobile(mobile)
        if not mobile_n:
            raise ValueError("شماره موبایل الزامی است.")
        nid = normalize_national_id(national_id)
        mail = normalize_email(email)
    except ValueError as exc:
        frappe.throw(str(exc), frappe.ValidationError)

    frappe.db.sql("select name from tabUser where name=%s for update", (user,))
    clash = frappe.db.get_value("User", {"mobile_no": mobile_n, "name": ["!=", user]}, "name")
    if clash:
        frappe.throw("این شماره موبایل برای حساب دیگری ثبت شده است.", frappe.ValidationError)
    person = person_for_user(user, nid)
    before_mobile = frappe.db.get_value("User", user, "mobile_no")
    before_mail = frappe.db.get_value("ASOUD Party Profile", person, "email") if person else None
    extra = {}
    if personal_details is not None:
        if not person or frappe.db.get_value("ASOUD Party Profile", person, "user") != user:
            frappe.throw("ابتدا مشخصات اولیه حساب خود را ثبت کنید.", frappe.PermissionError)
        try:
            raw = json.loads(personal_details) if isinstance(personal_details, str) else personal_details
            if not isinstance(raw, dict) or set(raw) - ADMIN_PERSONAL_FIELDS.keys():
                raise ValueError("فیلدهای تکمیلی پرونده معتبر نیستند.")
            for key, value in raw.items():
                if not isinstance(value, str):
                    raise ValueError("اطلاعات تکمیلی باید به صورت متن وارد شود.")
                value = value.strip()
                if key in {"phone", "postal_code"}:
                    value = normalize_numeric_text(value)
                if len(value) > ADMIN_PERSONAL_FIELDS[key]:
                    raise ValueError("طول یکی از فیلدهای تکمیلی بیش از حد مجاز است.")
                extra[key] = value or None
            previous = frappe.db.get_value("ASOUD Party Profile", person, list(ADMIN_PERSONAL_FIELDS), as_dict=True)
            validate_profile_update(extra, previous or {})
        except (ValueError, TypeError) as exc:
            frappe.throw(str(exc), frappe.ValidationError)
    # The login id (User.name / User.email) is never rewritten here; the optional e-mail is a
    # contact detail of the person record.
    doc = frappe.get_doc("User", user)
    doc.first_name, doc.last_name, doc.mobile_no = first, last, mobile_n
    doc.save(ignore_permissions=True)

    full = f"{first} {last}"
    values = {"display_name": full, "mobile": mobile_n, "party_type": "Individual", "user": user, **extra}
    if nid:
        values["national_id"] = nid
    if mail:
        values["email"] = mail
    if person:
        profile = frappe.get_doc("ASOUD Party Profile", person, for_update=True)
        profile.update(values)
        profile.save(ignore_permissions=True)
    else:
        office = first_office_record()
        profile = frappe.get_doc({"doctype": "ASOUD Party Profile", "roles_text": "[]",
                                  "company": office["company"] if office else None, **values})
        profile.insert(ignore_permissions=True)

    state = account_state.ensure(user, lock=True)
    if (before_mobile or "") != mobile_n:
        state.mobile_verified = 0
    if mail and (before_mail or "") != mail:
        state.email_verified = 0
    state.admin_profile_completed_on = now_datetime()
    state.save(ignore_permissions=True)
    security_audit.record("admin.profile_complete", target_type="User", target=user,
                          details={"fields": ["first_name", "last_name", "mobile"]
                                   + (["national_id"] if nid else []) + (["email"] if mail else []) + list(extra)})
    return read_admin_profile(user) | {"person": profile.name}


__all__ = ["first_office_exists"]
