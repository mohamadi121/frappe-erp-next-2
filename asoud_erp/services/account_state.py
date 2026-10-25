"""Per-account security state (ASOUD Account State): temporary password, profile completion, verification."""

import frappe
from frappe.utils import add_to_date, now_datetime

DOCTYPE = "ASOUD Account State"
_CACHE = "asoud_must_change_password"


def _exists() -> bool:
    return bool(frappe.db.table_exists(DOCTYPE))


def get(user: str) -> dict:
    if not _exists() or not frappe.db.exists(DOCTYPE, user):
        return {"must_change_password": 0, "temp_password_expires_on": None, "password_changed_on": None,
                "admin_profile_completed_on": None, "mobile_verified": 0, "email_verified": 0,
                "activation_pending": 0}
    return dict(frappe.db.get_value(DOCTYPE, user, [
        "must_change_password", "temp_password_expires_on", "password_changed_on",
        "admin_profile_completed_on", "mobile_verified", "email_verified", "activation_pending"],
        as_dict=True))


def ensure(user: str, lock: bool = False):
    if frappe.db.exists(DOCTYPE, user):
        return frappe.get_doc(DOCTYPE, user, for_update=lock)
    doc = frappe.get_doc({"doctype": DOCTYPE, "user": user})
    doc.insert(ignore_permissions=True)
    return doc


def must_change_password(user: str) -> bool:
    """Cheap per-request check (redis cached); expired temporary passwords stay «must change»."""
    if not user or user in {"Guest"} or not _exists():
        return False
    cached = frappe.cache.hget(_CACHE, user)
    if cached is not None:
        return bool(cached)
    value = bool(frappe.db.get_value(DOCTYPE, user, "must_change_password")) if frappe.db.exists(
        DOCTYPE, user) else False
    frappe.cache.hset(_CACHE, user, int(value))
    return value


def set_must_change(user: str, flag: bool, *, expires_in_hours: int | None = None) -> None:
    doc = ensure(user, lock=True)
    doc.must_change_password = int(bool(flag))
    doc.temp_password_expires_on = (
        add_to_date(now_datetime(), hours=expires_in_hours) if flag and expires_in_hours else None)
    doc.save(ignore_permissions=True)
    frappe.cache.hdel(_CACHE, user)


def mark_password_changed(user: str) -> None:
    doc = ensure(user, lock=True)
    doc.must_change_password = 0
    doc.temp_password_expires_on = None
    doc.activation_pending = 0
    doc.password_changed_on = now_datetime()
    doc.save(ignore_permissions=True)
    frappe.cache.hdel(_CACHE, user)
    frappe.db.set_value("User", user, "last_password_reset_date", frappe.utils.today(),
                        update_modified=False)


def temp_password_expired(user: str) -> bool:
    state = get(user)
    expiry = state.get("temp_password_expires_on")
    return bool(state.get("must_change_password") and expiry and frappe.utils.get_datetime(expiry) < now_datetime())
