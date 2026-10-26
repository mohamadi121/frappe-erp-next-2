"""First-run endpoints for the system administrator: first office and essential profile."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import onboarding as service
from asoud_erp.services import security_audit
from asoud_erp.services.login_state import first_office_exists


@frappe.whitelist(methods=["POST"])
def create_first_office(
    office_type: str,
    company_name: str,
    national_id: str | None = None,
    economic_code: str | None = None,
    auto_generate_detail_code: int | bool = 1,
    owner_full_name: str | None = None,
    registration_number: str | None = None,
    activity_type: str | None = None,
    company_type: str | None = None,
    parent_office: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    website: str | None = None,
    province: str | None = None,
    city: str | None = None,
    address: str | None = None,
    postal_code: str | None = None,
    fiscal_year: str | None = None,
    chart_template: str | None = None,
    description: str | None = None,
) -> dict:
    """Create the deployment's first office with the existing office form logic (``setup.save_office``).

    Idempotent: when an office already exists nothing is created and the existing one is returned with
    ``created = false``. Serialised by a global lock, so concurrent calls create exactly one office.
    """
    from asoud_erp.api.v1.setup import save_office

    user = service.require_admin()
    service.lock_bootstrap()
    if first_office_exists():
        existing = service.first_office_record()
        security_audit.record("office.create_first", result="denied", target_type="Company",
                              target=existing["company"], details={"reason": "already_exists"}, commit=True)
        from asoud_erp.api.v1.setup import _serialize_setup, _setup

        return success({"created": False, "already_exists": True,
                        "office": _serialize_setup(_setup(existing["company"]))})
    frappe.db.savepoint("asoud_first_office")
    try:
        office = save_office(
            office_type=office_type, company_name=company_name, national_id=national_id,
            economic_code=economic_code, auto_generate_detail_code=auto_generate_detail_code,
            owner_full_name=owner_full_name, registration_number=registration_number,
            activity_type=activity_type, company_type=company_type, parent_office=parent_office, phone=phone,
            email=email, website=website, province=province, city=city, address=address,
            postal_code=postal_code, fiscal_year=fiscal_year, chart_template=chart_template,
            description=description)["data"]
        service.mark_first_office(office["company"], user)
    except Exception:
        try:
            frappe.db.rollback(save_point="asoud_first_office")
        except Exception:
            # ERPNext commits inside Company creation, which releases the savepoint; the original
            # error (shown to the user) must not be replaced by «SAVEPOINT does not exist».
            frappe.log_error("first office rollback skipped: savepoint was released")
        raise
    security_audit.record("office.create_first", target_type="Company", target=office["company"],
                          company=office["company"], details={"office_type": office_type})
    return success({"created": True, "already_exists": False, "office": office})


@frappe.whitelist()
def get_admin_profile() -> dict:
    """Current identity data of the administrator (read-only username/role, editable names)."""
    user = service.require_admin()
    return success(service.read_admin_profile(user))


@frappe.whitelist(methods=["POST"])
def save_admin_profile(first_name: str, last_name: str, mobile: str, national_id: str | None = None,
                       email: str | None = None) -> dict:
    """Attach essential identity data to the existing admin account and its person record.

    Creates no account, role, personnel file or accounting detail code. Mobile/e-mail stay
    unverified until ownership is proven."""
    return success(service.save_admin_profile(first_name, last_name, mobile, national_id, email))
