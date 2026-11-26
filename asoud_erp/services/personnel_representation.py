"""Short-lived, auditable app delegation without changing either user's login session."""
import hashlib
import re
import secrets
from urllib.parse import unquote

import frappe

from asoud_erp.services import account_state, security_audit, session_guard
from asoud_erp.services.request_access import company_access
from asoud_erp.services.system_admin import is_system_admin

TTL = 1800
SCHEME = "Asoud-Delegated"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
BASE = "asoud_erp.api.v1."
FORBIDDEN_MODULES = {"account_security", "account", "setup_reset", "first_office_setup",
                     "user_access", "role_management", "role_access", "access_profiles", "hr_onboarding"}
PROTECTED_RESOURCES = {"user", "role", "role profile", "has role", "user permission",
                       "custom docperm", "doctype", "docperm", "server script", "system settings",
                       "sessions", "asoud account token", "asoud account state",
                       "asoud access assignment", "asoud role definition"}


def _key(token):
    return "asoud:personnel-delegation:" + hashlib.sha256(token.encode()).hexdigest()


def enabled():
    return frappe.conf.get("asoud_enable_personnel_representation", 1) in (1, "1")


def _secure_request(request):
    if request and (request.is_secure or (
        frappe.conf.get("developer_mode") and request.host.split(":")[0] in {"localhost", "127.0.0.1"}
    )):
        return True
    return False


def _active_parent(sid):
    from frappe.sessions import get_expired_threshold

    return bool(sid and sid != "Guest" and frappe.db.sql(
        "select sid from tabSessions where sid=%s and user=%s and status=%s and lastupdate > %s",
        (sid, "Administrator", "Active", get_expired_threshold()),
    ))


def _eligible(company, employee, user):
    if not user or user in {"Guest", "Administrator"} or is_system_admin(user):
        return False
    if not frappe.db.exists("Employee", {
        "name": employee, "company": company, "user_id": user, "status": "Active",
    }) or not frappe.db.get_value("User", user, "enabled"):
        return False
    state = account_state.get(user)
    return not (state["activation_pending"] or state["must_change_password"]
                or account_state.temp_password_expired(user)) and company_access(company, user)


def _audit(action, state, **details):
    # A delegated request is not allowed to execute if its attribution cannot be written.
    frappe.get_doc(security_audit.build_row(
        actor="Administrator", action=action, target_type="User", target=state["user"],
        company=state["company"], occurred_on=frappe.utils.now_datetime(),
        details={"delegation": state["audit_id"], **details},
    )).insert(ignore_permissions=True)


def start(company, employee, reason):
    if (not enabled() or frappe.session.user != "Administrator" or not _active_parent(frappe.session.sid)):
        frappe.throw("ورود به نمای پرسنل فقط با نشست امن مدیر اصلی مجاز است.", frappe.PermissionError)
    if not _secure_request(frappe.request):
        frappe.throw("برای ورود به نمایندگی، با نشانی امن (HTTPS) به سرور وصل شوید.", frappe.PermissionError)
    reason = (reason or "").strip()
    if not 5 <= len(reason) <= 300:
        frappe.throw("دلیل نمایندگی را بین ۵ تا ۳۰۰ نویسه وارد کنید.")
    user, name = frappe.db.get_value("Employee", {"name": employee, "company": company},
                                    ["user_id", "employee_name"]) or (None, None)
    if not _eligible(company, employee, user):
        frappe.throw("حساب فعال و مجاز این پرسنل در دفتر انتخاب‌شده یافت نشد.", frappe.PermissionError)
    token = secrets.token_urlsafe(32)
    state = {"company": company, "employee": employee, "user": user,
             "parent": frappe.session.sid, "audit_id": secrets.token_hex(12)}
    _audit("auth.personnel_representation_start", state, reason=reason)
    frappe.cache.set_value(_key(token), state, expires_in_sec=TTL)
    return {"credential": token, "employee_name": name, "expires_in": TTL}


def allowed_request(path, cmd=None):
    # Frappe also dispatches via form_dict.cmd, so do not let it override the checked path.
    path = unquote(path)
    if path.startswith("/api/method/"):
        method = session_guard.method_of(path)
        if not method or (cmd and cmd != method):
            return False
        if method in {"frappe.auth.get_logged_user", BASE + "session.logout"}:
            return True
        if not method.startswith(BASE):
            return False
        module, _, function = method.removeprefix(BASE).partition(".")
        if not function or "." in function or module in FORBIDDEN_MODULES:
            return False
        if module == "auth" and function != "current_user":
            return False
        if module == "session" and function not in {"login_state", "select_office"}:
            return False
        return True
    if cmd:
        return False
    if path.startswith("/api/resource/"):
        doctype = path.removeprefix("/api/resource/").split("/")[0].strip().casefold()
        return bool(doctype and doctype not in PROTECTED_RESOURCES and not doctype.startswith("asoud security"))
    return path.startswith("/private/files/")


def authenticate():
    request = getattr(frappe.local, "request", None)
    header = frappe.get_request_header("Authorization", "") if request else ""
    scheme, _, token = header.partition(" ")
    if scheme.casefold() != SCHEME.casefold():
        return
    if (not enabled() or not _secure_request(request) or not TOKEN_PATTERN.fullmatch(token)
            or frappe.session.user != "Guest"):
        raise frappe.AuthenticationError
    key = _key(token)
    state = frappe.cache.get_value(key)
    if not state or not _active_parent(state["parent"]) or not _eligible(
        state["company"], state["employee"], state["user"]
    ):
        frappe.cache.delete_value(key)
        raise frappe.AuthenticationError
    args = frappe.local.form_dict
    if not allowed_request(request.path, args.get("cmd")):
        frappe.throw("این عملیات امنیتی در حالت نمایندگی مجاز نیست.", frappe.PermissionError)
    frappe.set_user(state["user"])
    frappe.local.form_dict = args
    frappe.local.asoud_personnel_representation = (key, state)


def active():
    return getattr(frappe.local, "asoud_personnel_representation", None)


def stop():
    key, state = active()
    frappe.cache.delete_value(key)
    _audit("auth.personnel_representation_end", state)
    return {"revoked": True}


def audit_request():
    """Called immediately before Frappe dispatch; records the real actor for writes."""
    current = active()
    if current and frappe.request.method not in {"GET", "HEAD", "OPTIONS"}:
        _, state = current
        _audit("auth.personnel_representation_request", state,
               route=frappe.request.path, method=frappe.request.method)
