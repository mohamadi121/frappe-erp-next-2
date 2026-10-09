"""Template ``leave``: daily and hourly leave on the generic request engine (CONTRACT 3.6).

Importing this module needs no ``frappe``: the spec is metadata plus thin callables that import
the site-dependent rules (``leave_rules``) when called, so the registry can be loaded by pure unit
tests. After final approval a daily request becomes an approved Leave Application and an hourly one
a Leave Ledger Entry (``request_native_documents``).
"""

from asoud_erp.services.request_templates.base import TemplateSpec
from asoud_erp.services.request_templates.form_fields import LEAVE_ATTACHMENT_EXTENSIONS, LEAVE_FIELDS

VERSION = 1


def available_for(company, user):
    from asoud_erp.services.request_templates import common

    return common.available_for(company, user)


def resolve_defaults(company, user):
    from asoud_erp.services.request_templates import common

    return common.resolve_defaults(LEAVE_FIELDS, company, user)


def validate(ctx):
    from asoud_erp.services.request_templates import leave_rules

    return leave_rules.validate(ctx)


def build_subject(values):
    from asoud_erp.services.request_templates import leave_rules

    return leave_rules.build_subject(values)


def denormalize(values):
    return {"priority": "Normal", "required_by": values.get("start_date") or values.get("leave_date"),
            "project": "", "department": values.get("org_unit") or ""}


def summarize(values, request_row):
    from asoud_erp.services.request_templates import leave_rules

    return leave_rules.summarize(values, request_row)


def on_approved(request):
    from asoud_erp.services import request_native_documents as native

    return native.create_leave_document(request)


SPEC = TemplateSpec(
    key="leave",
    title="درخواست مرخصی",
    short_title="ثبت درخواست مرخصی",
    description="درخواست مرخصی روزانه یا ساعتی؛ پس از تأیید مدیر مستقیم مرخصی در سیستم منابع انسانی ثبت می‌شود.",
    number_prefix="LV",
    category="HR",
    module_key="HR",
    icon_key="leave",
    color_hex="#0E9F6E",
    version=VERSION,
    subject_mode="generated",
    form_fields=LEAVE_FIELDS,
    attachments={"max_files": 10, "max_mb": 10, "extensions": list(LEAVE_ATTACHMENT_EXTENSIONS)},
    approval={"assignment_type": "Direct Manager"},
    available_for=available_for,
    resolve_defaults=resolve_defaults,
    validate=validate,
    build_subject=build_subject,
    denormalize=denormalize,
    summarize=summarize,
    on_approved=on_approved,
)
