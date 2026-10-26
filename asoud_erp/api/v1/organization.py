import base64
import json

import frappe

from asoud_erp.api.v1.responses import success
from asoud_erp.services.organization_contract import validate_rows
from asoud_erp.services.organization_employees import normalize_assignments
from asoud_erp.services.organization_units import (
    lock_company,
    references,
    unit,
    validate_parent,
    validate_position_units,
)


def _access(company, write=False):
    frappe.get_doc("Company", company).check_permission("read")
    allowed = {"System Manager", "HR Manager"} if write else {"System Manager", "HR Manager", "HR User"}
    if not allowed.intersection(frappe.get_roles()):
        frappe.throw("Not permitted", frappe.PermissionError)


def _snapshot(doc):
    rows = json.loads(doc.structure_json or "[]")
    ids = {r.get("department_id") for r in rows if r.get("department_id")}
    if ids and frappe.has_permission("Department", "read"):
        titles = {r.name: r.department_name for r in frappe.get_list(
            "Department", filters={"company": doc.company, "name": ["in", sorted(ids)]},
            fields=["name", "department_name"], limit_page_length=0)}
        for row in rows:
            if row.get("department_id") in titles:
                row["department"] = titles[row["department_id"]]
    return {"rows": rows, "revision": doc.revision or 0}


@frappe.whitelist()
def get_chart(company):
    _access(company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    return success(_snapshot(frappe.get_doc("ASOUD Organization Chart", name)) if name else {"rows": [], "revision": 0})


@frappe.whitelist(methods=["POST"])
def save_chart(payload):
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or not data.get("company"):
        frappe.throw("Company and organization payload are required")
    company = data["company"]
    _access(company, write=True)
    # Serialize both initial creation and later revision checks per company.
    frappe.db.sql("select name from tabCompany where name=%s for update", company)
    # Lock the company's native employees in a stable order before checking
    # status, assignments and manager changes.
    frappe.db.sql("select name from tabEmployee where company=%s order by name for update", company)
    try:
        rows = validate_rows(data.get("rows"))
        revision = int(data.get("revision", 0))
    except (ValueError, TypeError) as error:
        frappe.throw(str(error))
    rows = normalize_assignments(rows, company)
    validate_position_units(rows, company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    doc = frappe.get_doc("ASOUD Organization Chart", name) if name else frappe.new_doc("ASOUD Organization Chart")
    current = _snapshot(doc)
    def intent(items):
        return [{key: value for key, value in row.items() if key != "assignment_history"} for row in items]
    unchanged = intent(current["rows"]) == intent(rows)
    if unchanged and revision != current["revision"]:
        return success(current)
    if not unchanged and revision != current["revision"]:
        frappe.throw("Organization chart changed on server; review before retrying", frappe.TimestampMismatchError)
    frappe.db.savepoint("organization_save")
    try:
        doc.company = company
        doc.structure_json = json.dumps(rows, ensure_ascii=False)
        doc.save()
        result = _snapshot(doc)
        result["warnings"] = doc.flags.organization_warnings or []
        return success(result)
    except Exception:
        frappe.db.rollback(save_point="organization_save")
        raise


@frappe.whitelist()
def list_employees(company):
    _access(company)
    employees = frappe.get_list(
        "Employee", filters={"company": company, "status": "Active"},
        fields=["name", "employee_name", "employee_number"], order_by="employee_name", limit_page_length=0,
    )
    return success({"employees": [
        {"id": "employee:" + row.name, "display_name": row.employee_name or row.name,
         "personnel_code": row.employee_number or row.name}
        for row in employees
    ]})


@frappe.whitelist()
def list_units(company):
    _access(company)
    rows = frappe.get_list("Department", filters={"company": company},
        fields=["name", "department_name", "parent_department", "is_group", "disabled", "modified"],
        order_by="lft asc", limit_page_length=0)
    return success({"units": rows, "can_manage":
        bool({"System Manager", "HR Manager"}.intersection(frappe.get_roles()))
        and frappe.has_permission("Department", "write")})


@frappe.whitelist(methods=["POST"])
def save_unit(company, payload):
    _access(company, write=True)
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict):
        frappe.throw("اطلاعات واحد معتبر نیست.")
    lock_company(company)
    name = data.get("name")
    doc = unit(name, company, "write") if name else frappe.new_doc("Department")
    if name and str(data.get("modified") or "") != str(doc.modified):
        frappe.throw("اطلاعات واحد تغییر کرده؛ دوباره بارگذاری کنید.", frappe.TimestampMismatchError)
    title = str(data.get("title") or "").strip()
    if not title:
        frappe.throw("عنوان واحد الزامی است.")
    parent = str(data.get("parent") or "").strip()
    validate_parent(name, parent, company)
    if parent and not frappe.get_doc("Department", parent).is_group:
        frappe.throw("ابتدا گزینه پذیرش زیرواحد را در واحد بالادستی فعال کنید.")
    doc.company, doc.department_name = company, title
    doc.parent_department = parent or None
    doc.is_group = int(bool(data.get("is_group")))
    if name and not doc.is_group and frappe.db.exists("Department", {"parent_department": name}):
        frappe.throw("واحد دارای زیرواحد باید پذیرش زیرواحد داشته باشد.")
    doc.save()
    return success({"name": doc.name, "modified": str(doc.modified)})


@frappe.whitelist(methods=["POST"])
def delete_unit(company, name, modified):
    _access(company, write=True)
    lock_company(company)
    doc = unit(name, company, "delete")
    if str(doc.modified) != str(modified):
        frappe.throw("اطلاعات واحد تغییر کرده؛ دوباره بارگذاری کنید.", frappe.TimestampMismatchError)
    blockers = _unit_delete_blockers(doc, company)
    if blockers:
        frappe.throw("\n".join(blockers))
    if references(name, company):
        frappe.throw("واحد دارای جایگاه سازمانی است؛ حذف مجاز نیست.")
    if frappe.db.exists("Department", {"parent_department": name}):
        frappe.throw("واحد دارای زیرواحد است؛ حذف مجاز نیست.")
    # Native static/dynamic links, including historical records, block deletion.
    frappe.delete_doc("Department", name)
    return success({"deleted": name})


def _unit_delete_blockers(doc, company):
    from frappe.model.delete_doc import check_if_doc_is_dynamically_linked, check_if_doc_is_linked

    blockers = []
    positions = len(references(doc.name, company))
    children = frappe.db.count("Department", {"parent_department": doc.name})
    if positions:
        blockers.append(f"این واحد دارای {positions} جایگاه یا سابقه مرتبط است.")
    if children:
        blockers.append(f"این واحد دارای {children} زیرواحد است.")
    for check in (check_if_doc_is_linked, check_if_doc_is_dynamically_linked):
        try:
            check(doc)
        except frappe.LinkExistsError:
            frappe.clear_last_message()
            # Do not reveal linked documents outside the caller's permissions.
            blockers.append("واحد به اطلاعات یا سوابق دیگری در سیستم متصل است؛ حذف مجاز نیست.")
    return list(dict.fromkeys(blockers))


@frappe.whitelist()
def preview_delete_unit(company, name, modified):
    _access(company, write=True)
    doc = unit(name, company, "delete")
    if str(doc.modified) != str(modified):
        frappe.throw("اطلاعات واحد تغییر کرده؛ دوباره بارگذاری کنید.", frappe.TimestampMismatchError)
    blockers = _unit_delete_blockers(doc, company)
    return success({"can_delete": not blockers, "blockers": blockers, "modified": str(doc.modified)})


@frappe.whitelist()
def preview_delete_position(company, code, revision):
    from asoud_erp.services.organization_assignments import deletion_review
    from asoud_erp.services.request_access import require_company

    _access(company, write=True)
    require_company(company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    if not name:
        frappe.throw("جایگاه موردنظر در ساختار فعلی وجود ندارد.")
    doc = frappe.get_doc("ASOUD Organization Chart", name)
    doc.check_permission("write")
    current = _snapshot(doc)
    try:
        expected = int(revision)
    except (TypeError, ValueError):
        frappe.throw("نسخه ساختار معتبر نیست.")
    if expected != current["revision"]:
        frappe.throw("ساختار تغییر کرده است؛ دوباره بارگذاری کنید.", frappe.TimestampMismatchError)
    try:
        result = deletion_review(current["rows"], code)
    except ValueError as error:
        frappe.throw(str(error))
    return success({**result, "revision": current["revision"]})


@frappe.whitelist()
def employee_photo(company, employee):
    _access(company)
    name = str(employee).removeprefix("employee:")
    doc = frappe.get_doc("Employee", name)
    doc.check_permission("read")
    if doc.company != company:
        frappe.throw("پرسنل متعلق به این شرکت نیست.", frappe.PermissionError)
    if not doc.image:
        return success({"content": None})
    files = frappe.get_list("File", filters={"attached_to_doctype": "Employee",
        "attached_to_name": name, "file_url": doc.image}, pluck="name", limit_page_length=1)
    if not files:
        return success({"content": None})
    file = frappe.get_doc("File", files[0])
    file.check_permission("read")
    content = file.get_content()
    if not isinstance(content, bytes):
        return success({"content": None})
    from io import BytesIO

    from PIL import Image, ImageOps

    try:
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((160, 160))
            output = BytesIO()
            image.save(output, format="JPEG", quality=80)
    except (OSError, ValueError, Image.DecompressionBombError):
        return success({"content": None})
    return success({"content": base64.b64encode(output.getvalue()).decode("ascii")})


@frappe.whitelist()
def preview_import(company, payload):
    from asoud_erp.services.organization_import import plan

    _access(company, write=True)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    current = _snapshot(frappe.get_doc("ASOUD Organization Chart", name)) if name else {"rows": [], "revision": 0}
    result = plan(company, payload, current["rows"])
    result["revision"] = current["revision"]
    return success(result)


@frappe.whitelist(methods=["POST"])
def apply_import(company, payload, revision):
    from asoud_erp.services.organization_import import apply_units, plan

    _access(company, write=True)
    lock_company(company)
    name = frappe.db.get_value("ASOUD Organization Chart", {"company": company}, "name")
    current = _snapshot(frappe.get_doc("ASOUD Organization Chart", name)) if name else {"rows": [], "revision": 0}
    if int(revision) != current["revision"]:
        frappe.throw("ساختار پس از پیش‌نمایش تغییر کرده است.", frappe.TimestampMismatchError)
    result = plan(company, payload, current["rows"])
    frappe.db.savepoint("organization_import")
    try:
        apply_units(result["units"], company)
        return save_chart(dict(company=company, revision=revision, rows=result["rows"]))
    except Exception:
        frappe.db.rollback(save_point="organization_import")
        raise

