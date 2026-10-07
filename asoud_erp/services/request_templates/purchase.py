"""Template ``purchase``: employee purchase requisition (CONTRACT 3.4).

Importing this module needs no ``frappe``: the spec is metadata plus thin callables that import
the site-dependent helpers (``common``) when called. After final approval a draft Material Request
of type Purchase is created (``request_native_documents``).
"""

from asoud_erp.services.request_templates.base import TemplateSpec, throw_error
from asoud_erp.services.request_templates.form_fields import ATTACHMENT_EXTENSIONS, PURCHASE_FIELDS

VERSION = 1


def available_for(company, user):
    from asoud_erp.services.request_templates import common

    return common.available_for(company, user)


def resolve_defaults(company, user):
    from asoud_erp.services.request_templates import common

    return common.resolve_defaults(PURCHASE_FIELDS, company, user)


def validate(ctx):
    from asoud_erp.services.request_templates import common

    common.check_requester(ctx)
    if common.cost_center_required(ctx.company) and not ctx.values.get("cost_center"):
        throw_error("COST_CENTER_REQUIRED")
    common.check_needed_date(ctx)
    return ctx.values


def denormalize(values):
    return {"priority": values.get("priority") or "Normal", "required_by": values.get("needed_date"),
            "project": values.get("project") or "", "department": values.get("org_unit") or ""}


def summarize(values, request_row):
    from asoud_erp.services.request_templates import common

    return common.base_summary(values, request_row)


def on_approved(request):
    from asoud_erp.services import request_native_documents as native

    return native.create_material_request(request, "purchase")


SPEC = TemplateSpec(
    key="purchase",
    title="درخواست خرید کالا",
    short_title="ثبت درخواست خرید کالا",
    description="درخواست خرید کالا توسط کارکنان؛ پس از تأیید مدیر مستقیم، درخواست مواد (خرید) ایجاد می‌شود.",
    number_prefix="PR",
    category="Purchase",
    module_key="Purchase",
    icon_key="purchase",
    color_hex="#1769F6",
    version=VERSION,
    subject_mode="input",
    form_fields=PURCHASE_FIELDS,
    attachments={"max_files": 10, "max_mb": 10, "extensions": list(ATTACHMENT_EXTENSIONS)},
    approval={"assignment_type": "Direct Manager"},
    available_for=available_for,
    resolve_defaults=resolve_defaults,
    validate=validate,
    build_subject=None,
    denormalize=denormalize,
    summarize=summarize,
    on_approved=on_approved,
)
