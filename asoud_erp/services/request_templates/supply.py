"""Template ``supply``: request to supply goods or services (CONTRACT 3.5).

Importing this module needs no ``frappe`` (see ``purchase.py``). After final approval the supply
method decides the draft Material Request type, or no document at all.
"""

from asoud_erp.services.native_payloads import parse_delivery_location
from asoud_erp.services.request_templates.base import TemplateSpec, throw_error
from asoud_erp.services.request_templates.form_fields import ATTACHMENT_EXTENSIONS, SUPPLY_FIELDS

VERSION = 1
STOCK_ONLY_METHODS = ("Warehouse", "Transfer")


def available_for(company, user):
    from asoud_erp.services.request_templates import common

    return common.available_for(company, user)


def resolve_defaults(company, user):
    from asoud_erp.services.request_templates import common

    return common.resolve_defaults(SUPPLY_FIELDS, company, user)


def validate(ctx):
    from asoud_erp.services.request_templates import common

    common.check_requester(ctx)
    common.check_needed_date(ctx)
    kind, _name = common.check_delivery(ctx.company, ctx.values.get("delivery_location"))
    method = ctx.values.get("supply_method") or "Unspecified"
    if method == "Transfer" and kind != "warehouse":
        throw_error("DELIVERY_NOT_WAREHOUSE")
    if method in STOCK_ONLY_METHODS and any(not common.stock_flag(row) for row in common.item_rows(ctx.values)):
        throw_error("ITEM_NOT_STOCKABLE")
    return ctx.values


def denormalize(values):
    return {"priority": values.get("priority") or "Normal", "required_by": values.get("needed_date"),
            "project": "", "department": values.get("org_unit") or ""}


def summarize(values, request_row):
    from asoud_erp.services.request_templates import common

    summary = common.base_summary(values, request_row)
    delivery = parse_delivery_location(values.get("delivery_location"))
    label = ""
    if delivery:
        kind, name = delivery
        label = (common.label_of("Warehouse", name, "warehouse_name") if kind == "warehouse"
                 else common.label_of("Department", name, "department_name") if kind == "department"
                 else name)
    method = values.get("supply_method") or "Unspecified"
    return {**summary, "delivery_location": values.get("delivery_location") or "",
            "delivery_location_label": label, "supply_method": method,
            "supply_method_label": common.SUPPLY_METHOD_LABELS.get(method, method)}


def on_approved(request):
    from asoud_erp.services import request_native_documents as native

    return native.create_material_request(request, "supply")


SPEC = TemplateSpec(
    key="supply",
    title="درخواست تأمین کالا / خدمت",
    short_title="ثبت درخواست تأمین کالا / خدمت",
    description="درخواست تأمین کالا یا خدمت؛ بر اساس روش تأمین، پس از تأیید مدیر مستقیم درخواست مواد ایجاد می‌شود.",
    number_prefix="SP",
    category="Purchase",
    module_key="Inventory",
    icon_key="purchase",
    color_hex="#0E9F6E",
    version=VERSION,
    subject_mode="input",
    form_fields=SUPPLY_FIELDS,
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
