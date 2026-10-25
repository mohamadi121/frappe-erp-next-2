"""HR onboarding endpoints: register personnel with an account, first HR lead, temporary password."""

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services import hr_onboarding as service


@frappe.whitelist(methods=["POST"])
def register_personnel(company: str, first_name: str, last_name: str, mobile: str, email: str,
                       national_id: str | None = None, gender: str | None = None,
                       birth_date: str | None = None, date_of_joining: str | None = None,
                       job_title: str | None = None, department: str | None = None,
                       roles: str | list | None = None, activation: str = "invite",
                       detail_groups: str | list | None = None, request_id: str | None = None) -> dict:
    """HR Manager / System Manager: person (reused when known) -> personnel file -> account -> roles -> activation."""
    return success(service.register(
        company, first_name, last_name, mobile, email, national_id=national_id, gender=gender,
        birth_date=birth_date, date_of_joining=date_of_joining, job_title=job_title, department=department,
        roles=_list(roles), activation=activation, detail_groups=_list(detail_groups), request_id=request_id))


@frappe.whitelist(methods=["POST"])
def bootstrap_hr_lead(company: str, first_name: str, last_name: str, mobile: str, email: str,
                      national_id: str | None = None, activation: str = "invite",
                      gender: str | None = None, birth_date: str | None = None,
                      date_of_joining: str | None = None, request_id: str | None = None) -> dict:
    """System administrator only: introduce the first HR lead without any prior HR account.
    The person gets the ``HR Manager`` role and the same secure activation as any personnel."""
    return success(service.register(
        company, first_name, last_name, mobile, email, national_id=national_id, activation=activation,
        gender=gender, birth_date=birth_date, date_of_joining=date_of_joining,
        hr_lead=True, request_id=request_id))


@frappe.whitelist(methods=["POST"])
def issue_temporary_password(party_profile: str) -> dict:
    """New temporary password (shown once) that must be changed at the next sign-in."""
    return success(service.issue_temporary_password(party_profile))


def _list(value):
    if value in (None, ""):
        return []
    value = frappe.parse_json(value) if isinstance(value, str) else value
    return [str(v) for v in value] if isinstance(value, list) else []
