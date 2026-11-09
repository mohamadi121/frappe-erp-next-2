import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import cint, now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.jalali import current_jalali_year
from asoud_erp.services.request_access import require_company
from asoud_erp.services.workflow_contract import (
    ALLOWED_WORKFLOW_STATUSES,
    design_details_summary,
    serialize_workflow,
)
from asoud_erp.services.workflow_stage_policy import (
    REQUEST_CATEGORIES,
    ROLE_BASED_TYPES,
    normalize_stage_config,
)
from asoud_erp.services.workflow_user_action_policy import condition_fields as action_condition_fields

ALLOWED_STATUSES = ALLOWED_WORKFLOW_STATUSES
MODULE_DOCTYPES = {
    "Purchase": ("Material Request", "Purchase Order"),
    "Accounting": ("Payment Request", "Expense Claim", "Journal Entry"),
    "Sales": ("Quotation", "Sales Order"),
    "Inventory": ("Stock Entry",),
    "Support": ("Issue", "ASOUD Workflow Request"),
    "HR": ("Leave Application", "Job Applicant"),
}
STAGE_TITLES = {
    "User Task": "اقدام کاربر",
    "Approval": "تأیید یا رد",
    "Condition": "شرط و مسیر",
    "System Action": "اقدام خودکار",
    "Wait": "انتظار و زمان‌بندی",
    "End": "پایان فرایند",
}


def _stage_dict(row: dict) -> dict:
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    return result


def _transition_dict(row: dict) -> dict:
    result = dict(row)
    result["condition"] = json.loads(result.pop("condition_json") or "{}")
    return result


def _design_payload(definition: str) -> dict:
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    stages = frappe.get_all(
        "ASOUD Workflow Stage",
        filters={"workflow_definition": definition},
        fields=[
            "name", "stage_key", "stage_type", "stage_subtype", "stage_title",
            "sequence_no", "config_json", "configuration_status", "position_x", "position_y",
        ],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    transitions = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition},
        fields=["name", "from_stage", "to_stage", "transition_label", "condition_json", "sequence_no"],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    return {
        "workflow": serialize_workflow(workflow.as_dict()),
        "stages": [_stage_dict(row) for row in stages],
        "transitions": [_transition_dict(row) for row in transitions],
        "details_summary": design_details_summary(stages, transitions),
    }


@frappe.whitelist()
def list_workflows(
    search: str | None = None,
    status: str | None = None,
    company: str | None = None,
    order_by: str = "modified desc",
) -> dict:
    require_roles(("System Manager", "Accounts Manager", "Accounts User", "HR Manager"))
    if status and status not in ALLOWED_STATUSES:
        frappe.throw(_("Invalid workflow status"))
    allowed_order = {
        "modified desc": "modified desc",
        "modified asc": "modified asc",
        "title asc": "workflow_title asc",
        "code asc": "workflow_code asc",
    }
    filters: dict = {}
    if status:
        filters["status"] = status
    if company:
        require_company(company)
        filters["company"] = company
    or_filters = None
    if search:
        term = f"%{search.strip()}%"
        or_filters = {"workflow_title": ["like", term], "workflow_code": ["like", term]}
    rows = frappe.get_all(
        "ASOUD Workflow Definition",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "workflow_code", "workflow_title", "company", "target_doctype",
            "process_description", "module_key", "creation_mode",
            "frappe_workflow", "status", "readiness_status", "pending_reason",
            "missing_requirements_json", "version_no", "steps_count", "icon_key",
            "color_hex", "short_title", "request_category", "show_in_request_list",
            "allow_user_submission", "modified", "modified_by", "is_system_template", "template_key",
        ],
        order_by=allowed_order.get(order_by, "modified desc"),
        limit_page_length=200,
    )
    from asoud_erp.services.workflow_contract import is_system_workflow

    can_delete = bool(frappe.has_permission('ASOUD Workflow Definition', 'delete'))
    starts = frappe.get_all('ASOUD Workflow Stage', filters={'workflow_definition': ['in', [r.name for r in rows] or ['']],
        'stage_type': 'Start'}, fields=['workflow_definition', 'config_json'], limit_page_length=200)
    start_configs = {}
    for start in starts:
        try:
            config = json.loads(start.config_json or '{}')
        except (TypeError, ValueError):
            config = {}
        start_configs[start.workflow_definition] = config if isinstance(config, dict) else {}
    user_roles = set(frappe.get_roles())
    for row in rows:
        row['can_delete'] = can_delete and not is_system_workflow(row)
        config = start_configs.get(row.name, {})
        allowed_roles = config.get('initiator_roles')
        allowed_roles = [role for role in allowed_roles if isinstance(role, str)] if isinstance(allowed_roles, list) else []
        row['can_start_manual'] = (row.status == 'Active' and row.readiness_status == 'Ready'
            and config.get('start_settings_version') == 1 and config.get('trigger_type') == 'Manual'
            and bool(user_roles.intersection(allowed_roles)))
    return success([serialize_workflow(row) for row in rows], meta={"total": len(rows)})


@frappe.whitelist()
def workflow_form_options() -> dict:
    require_roles(("System Manager", "Accounts Manager", "HR Manager"))
    modules = []
    for key, doctypes in MODULE_DOCTYPES.items():
        options = [
            {"name": doctype, "available": bool(frappe.db.exists("DocType", doctype))}
            for doctype in doctypes
        ]
        modules.append({"key": key, "doctypes": options})
    companies = frappe.get_all("Company", pluck="name", order_by="name asc")
    roles = frappe.get_all(
        "Role",
        filters={"disabled": 0, "name": ["not in", ["All", "Guest"]]},
        pluck="name",
        order_by="name asc",
    )
    departments = frappe.get_all(
        "Department",
        filters={"disabled": 0},
        fields=["name", "department_name", "company", "parent_department", "is_group"],
        order_by="lft asc",
        limit_page_length=0,
    )
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "employee_name", "department", "company", "user_id", "designation"],
        order_by="employee_name asc",
        limit_page_length=0,
    )
    return success({
        "modules": modules,
        "companies": companies,
        "roles": roles,
        "departments": departments,
        "employees": employees,
    })


@frappe.whitelist(methods=["POST"])
def create_workflow_draft(
    workflow_title: str,
    module_key: str,
    target_doctype: str,
    company: str | None = None,
    process_description: str | None = None,
    creation_mode: str = "Custom",
    icon_key: str | None = None,
    color_hex: str | None = None,
) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    title = (workflow_title or "").strip()
    if len(title) < 3:
        frappe.throw(_("Workflow title must contain at least 3 characters"))
    if module_key not in MODULE_DOCTYPES:
        frappe.throw(_("Invalid workflow module"))
    if target_doctype != "ASOUD Workflow Request" and target_doctype not in MODULE_DOCTYPES[module_key]:
        frappe.throw(_("The selected DocType does not belong to this module"))
    if not frappe.db.exists("DocType", target_doctype):
        frappe.throw(_("The selected DocType is not installed"))
    if company:
        if not frappe.db.exists("Company", company):
            frappe.throw(_("The selected company does not exist"))
        require_company(company)
    if creation_mode not in {"Custom", "Template"}:
        frappe.throw(_("Invalid workflow creation mode"))

    code = make_autoname(f"WF-{current_jalali_year()}-.###")
    doc = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Definition",
            "workflow_code": code,
            "workflow_title": title,
            "process_description": (process_description or "").strip(),
            "company": company,
            "module_key": module_key,
            "creation_mode": creation_mode,
            "target_doctype": target_doctype,
            "status": "Inactive",
            "readiness_status": "Pending",
            "pending_reason": _("Workflow stages and transitions are not complete"),
            "missing_requirements_json": '["Workflow stages", "Transitions", "Frappe Workflow"]',
            "icon_key": icon_key,
            "color_hex": color_hex,
        }
    )
    doc.insert()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": doc.name,
            "stage_key": f"start-{frappe.generate_hash(length=10)}",
            "stage_type": "Start",
            "stage_title": _("Start"),
            "sequence_no": 0,
            "configuration_status": "Pending",
            "config_json": json.dumps(
                {
                    "trigger_type": "Manual",
                    "initiator_roles": [],
                    "subject_source": "Referenced Document",
                    "pass_mode": "Direct",
                }
            ),
        }
    ).insert()
    return success(serialize_workflow(doc.as_dict()))


@frappe.whitelist()
def get_workflow_design(definition: str) -> dict:
    require_roles(("System Manager", "Accounts Manager", "Accounts User", "HR Manager"))
    doc = frappe.get_doc("ASOUD Workflow Definition", definition)
    if doc.company:
        require_company(doc.company)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def save_start_settings(
    definition: str,
    trigger_type: str,
    initiator_roles: str | list[str],
    subject_source: str,
    pass_mode: str = "Direct",
    settings: str | dict | None = None,
) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    if settings is not None:
        from asoud_erp.services.workflow_start_settings import save

        return success(_stage_dict(save(definition, settings).as_dict()))
    frappe.db.sql('select name from `tabASOUD Workflow Definition` where name=%s for update', (definition,))
    if trigger_type not in {"Manual", "Document Event", "System", "API"}:
        frappe.throw(_("Invalid start trigger"))
    if subject_source not in {"Referenced Document", "ASOUD Record", "General Subject"}:
        frappe.throw(_("Invalid workflow subject source"))
    if pass_mode not in {"Direct", "Conditional"}:
        frappe.throw(_("Invalid start pass mode"))
    values = json.loads(initiator_roles) if isinstance(initiator_roles, str) else initiator_roles
    roles = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    missing_roles = [role for role in roles if not frappe.db.exists("Role", role)]
    if missing_roles:
        frappe.throw(_("One or more initiator roles do not exist"))
    stage_name = frappe.db.get_value(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": "Start"}, "name"
    )
    if not stage_name:
        frappe.throw(_("Workflow start stage does not exist"))
    stage = frappe.get_doc("ASOUD Workflow Stage", stage_name)
    if json.loads(stage.config_json or '{}').get('start_settings_version') == 1:
        frappe.throw('تنظیمات این شروع با فرم جدید مدیریت می‌شود؛ نسخهٔ برنامه را به‌روزرسانی کنید.')
    stage.config_json = json.dumps(
        {
            "trigger_type": trigger_type,
            "initiator_roles": roles,
            "subject_source": subject_source,
            "pass_mode": pass_mode,
        },
        ensure_ascii=False,
    )
    stage.configuration_status = "Complete" if roles or trigger_type != "Manual" else "Pending"
    stage.save()
    return success(_stage_dict(stage.as_dict()))


@frappe.whitelist(methods=["POST"])
def add_workflow_stage(definition: str, stage_type: str, after_stage: str) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    previous = frappe.get_doc("ASOUD Workflow Stage", after_stage)
    if previous.workflow_definition != definition:
        frappe.throw(_("The selected previous stage belongs to another workflow"))
    if previous.stage_type == "End":
        frappe.throw(_("A stage cannot be added after the end stage"))
    existing_next = frappe.db.exists("ASOUD Workflow Transition", {"from_stage": previous.name})
    if existing_next:
        frappe.throw(_("Linear designer already has a stage after the selected stage"))
    sequence = int(previous.sequence_no or 0) + 1
    stage = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": definition,
            "stage_key": f"stage-{frappe.generate_hash(length=10)}",
            "stage_type": stage_type,
            "stage_title": STAGE_TITLES[stage_type],
            "sequence_no": sequence,
            "configuration_status": "Pending" if stage_type != "End" else "Complete",
            "config_json": "{}",
            "position_y": sequence * 180,
        }
    )
    stage.insert()
    transition = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": previous.name,
            "to_stage": stage.name,
            "sequence_no": sequence,
            "condition_json": "{}",
        }
    )
    transition.insert()
    definition_doc = frappe.get_doc("ASOUD Workflow Definition", definition)
    definition_doc.steps_count = frappe.db.count(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": ["!=", "Start"]}
    )
    definition_doc.version_no = int(definition_doc.version_no or 1) + 1
    definition_doc.save()
    return success(_design_payload(definition))


def _assert_stage_in_definition(stage_name: str, definition: str):
    stage = frappe.get_doc("ASOUD Workflow Stage", stage_name)
    if stage.workflow_definition != definition:
        frappe.throw(_("Stage does not belong to the selected workflow"))
    return stage


def _touch_workflow(definition: str) -> None:
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.steps_count = frappe.db.count(
        "ASOUD Workflow Stage",
        {"workflow_definition": definition, "stage_type": ["!=", "Start"]},
    )
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()


@frappe.whitelist(methods=["POST"])
def update_stage_positions(definition: str, positions: str | dict) -> dict:
    """Persist designer coordinates without changing workflow semantics."""
    require_roles(("System Manager", "Accounts Manager"))
    values = json.loads(positions) if isinstance(positions, str) else positions
    if not isinstance(values, dict) or len(values) > 250:
        frappe.throw(_("Invalid stage positions"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    for stage_name, point in values.items():
        if not isinstance(point, dict):
            frappe.throw(_("Invalid stage position"))
        stage = _assert_stage_in_definition(stage_name, definition)
        try:
            x = float(point.get("x", 0))
            y = float(point.get("y", 0))
        except (TypeError, ValueError):
            frappe.throw(_("Invalid stage position"))
        if not (-10000 <= x <= 10000 and -10000 <= y <= 10000):
            frappe.throw(_("Stage position is outside the allowed canvas"))
        stage.db_set({"position_x": x, "position_y": y}, update_modified=False)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def connect_workflow_stages(
    definition: str,
    from_stage: str,
    to_stage: str,
    action: str,
    condition: str | dict | None = None,
) -> dict:
    """Create a named route; backward routes are deliberately supported."""
    require_roles(("System Manager", "Accounts Manager"))
    action = (action or "").strip()
    if not action or len(action) > 140 or from_stage == to_stage:
        frappe.throw(_("Invalid workflow transition"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    source = _assert_stage_in_definition(from_stage, definition)
    if source.stage_type == 'Condition':
        from asoud_erp.services.workflow_condition_binding import assert_editable

        assert_editable(definition)
        raw = json.loads(condition) if isinstance(condition, str) else condition
        if not isinstance(raw, dict) or type(raw.get('result')) is not bool:
            frappe.throw('خروجی شرط باید برقرار یا برقرار نیست باشد.')
        if to_stage:
            destination = _assert_stage_in_definition(to_stage, definition)
            if destination.stage_type == 'Start':
                frappe.throw('خروجی شرط نمی‌تواند به شروع فرایند متصل شود.')
        existing = frappe.get_all('ASOUD Workflow Transition',
            filters={'workflow_definition': definition, 'from_stage': from_stage},
            fields=['name', 'condition_json'], limit_page_length=1001)
        matches = [row for row in existing if json.loads(row.condition_json or '{}').get('result') is raw['result']]
        if len(matches) > 1 or len(existing) > 1000:
            frappe.throw('مسیرهای خروجی شرط تکراری یا نامعتبرند؛ ابتدا طراحی را بازبینی کنید.')
        if matches:
            edge = frappe.get_doc('ASOUD Workflow Transition', matches[0].name)
            if to_stage:
                edge.to_stage = to_stage
                edge.save()
            else:
                edge.delete()
        elif to_stage:
            frappe.get_doc(dict(doctype='ASOUD Workflow Transition', workflow_definition=definition,
                from_stage=from_stage, to_stage=to_stage, condition_json=json.dumps({'result': raw['result']}),
                transition_label='شرط برقرار است' if raw['result'] else 'شرط برقرار نیست',
                sequence_no=1 if raw['result'] else 2)).insert()
        _touch_workflow(definition)
        return success(_design_payload(definition))
    _assert_stage_in_definition(to_stage, definition)
    if source.stage_type == "End":
        frappe.throw(_("The end stage cannot have an outgoing route"))
    if frappe.db.exists(
        "ASOUD Workflow Transition",
        {
            "workflow_definition": definition,
            "from_stage": from_stage,
            "transition_label": action,
        },
    ):
        frappe.throw(_("This action already has a route from the selected stage"))
    raw_condition = json.loads(condition) if isinstance(condition, str) else (condition or {})
    if not isinstance(raw_condition, dict):
        frappe.throw(_("Transition condition must be an object"))
    canonical_actions = {
        "تأیید": "Approve",
        "رد": "Reject",
        "بازگشت برای اصلاح": "Return",
        "ارجاع": "Forward",
        "ادامه": "Complete",
    }
    raw_condition.setdefault("action", canonical_actions.get(action, action))
    sequence = frappe.db.count(
        "ASOUD Workflow Transition",
        {"workflow_definition": definition, "from_stage": from_stage},
    ) + 1
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "transition_label": action,
            "condition_json": json.dumps(raw_condition, ensure_ascii=False),
            "sequence_no": sequence,
        }
    ).insert()
    _touch_workflow(definition)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def insert_workflow_stage(
    definition: str, transition: str, stage_type: str
) -> dict:
    """Split one existing route into source -> new stage -> old destination."""
    require_roles(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    edge = frappe.get_doc("ASOUD Workflow Transition", transition)
    if edge.workflow_definition != definition:
        frappe.throw(_("Transition does not belong to the selected workflow"))
    source = _assert_stage_in_definition(edge.from_stage, definition)
    destination = _assert_stage_in_definition(edge.to_stage, definition)
    sequence = max(int(source.sequence_no or 0) + 1, 1)
    stage = frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Stage",
            "workflow_definition": definition,
            "stage_key": f"stage-{frappe.generate_hash(length=10)}",
            "stage_type": stage_type,
            "stage_title": STAGE_TITLES[stage_type],
            "sequence_no": sequence,
            "configuration_status": "Complete" if stage_type == "End" else "Pending",
            "config_json": "{}",
            "position_x": (float(source.position_x or 0) + float(destination.position_x or 0)) / 2,
            "position_y": (float(source.position_y or 0) + float(destination.position_y or 0)) / 2,
        }
    ).insert()
    original = {
        "label": edge.transition_label,
        "condition": edge.condition_json or "{}",
        "sequence": edge.sequence_no,
    }
    edge.delete()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": source.name,
            "to_stage": stage.name,
            "transition_label": original["label"],
            "condition_json": original["condition"],
            "sequence_no": original["sequence"],
        }
    ).insert()
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Transition",
            "workflow_definition": definition,
            "from_stage": stage.name,
            "to_stage": destination.name,
            "transition_label": _("Continue"),
            "condition_json": "{}",
            "sequence_no": 1,
        }
    ).insert()
    _touch_workflow(definition)
    return success(_design_payload(definition))


@frappe.whitelist()
def workflow_condition_fields(definition: str, stage: str | None = None) -> dict:
    require_roles(("System Manager", "Accounts Manager", "HR Manager"))
    company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
    if company:
        require_company(company)
    target_doctype = frappe.db.get_value("ASOUD Workflow Definition", definition, "target_doctype")
    if not target_doctype or not frappe.db.exists("DocType", target_doctype):
        frappe.throw(_("Workflow target DocType does not exist"))
    allowed_types = {"Data", "Select", "Link", "Int", "Float", "Currency", "Check", "Date", "Datetime"}
    fields = [
        {"fieldname": field.fieldname, "label": field.label or field.fieldname, "fieldtype": field.fieldtype, "source": "Document"}
        for field in frappe.get_meta(target_doctype).fields
        if field.fieldname and field.fieldtype in allowed_types and not field.hidden
    ]
    stage_filters = {"workflow_definition": definition, "stage_type": "User Task"}
    if stage:
        condition = frappe.get_doc("ASOUD Workflow Stage", stage)
        if condition.workflow_definition != definition or condition.stage_type != "Condition":
            frappe.throw(_("Selected stage is not a condition in this workflow"))
        stage_filters["sequence_no"] = ["<", condition.sequence_no]
    stage_rows = frappe.get_all(
        "ASOUD Workflow Stage",
        filters=stage_filters,
        fields=["config_json"],
        order_by="sequence_no asc",
        limit_page_length=0,
    )
    for row in stage_rows:
        fields.extend(action_condition_fields(json.loads(row.config_json or '{}')))
        for field in json.loads(row.config_json or "{}").get("form_fields", []):
            if field.get("type") in {
                "Short Text", "Long Text", "Number", "Currency", "Date", "Choice", "Checkbox",
                "User", "Department",
            }:
                fields.append({
                    "fieldname": field.get("key"),
                    "label": field.get("label") or field.get("key"),
                    "fieldtype": field.get("type"),
                    "source": "Form",
                })
    from asoud_erp.services.workflow_submission_source import condition_fields

    source_fields = condition_fields(definition)
    if frappe.db.get_value('ASOUD Workflow Definition', definition, 'source_form'):
        fields = [item for item in fields if item['source'] != 'Document']
    fields.extend(source_fields)
    fields = list({(item["source"], item["fieldname"]): item for item in fields}.values())
    result = {"doctype": target_doctype, "fields": fields}
    if stage:
        from asoud_erp.services.workflow_condition_binding import catalog

        result['condition_fields_v2'] = catalog(definition, stage)
    return success(result)


@frappe.whitelist(methods=["POST"])
def test_workflow_condition(definition: str, stage: str, config: str | dict, samples: str | dict) -> dict:
    """Evaluate a condition with caller-supplied sample values; it never writes anything."""
    require_roles(("System Manager", "Accounts Manager", "HR Manager"))
    company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
    if company:
        require_company(company)
    raw = json.loads(config) if isinstance(config, str) else config
    if not isinstance(raw, dict):
        frappe.throw(_("Stage configuration must be an object"))
    raw_samples = json.loads(samples) if isinstance(samples, str) else samples
    if not isinstance(raw_samples, dict):
        frappe.throw('نمونه‌ها باید یک شیء با کلید شناسهٔ شرط باشند.')
    from asoud_erp.services.workflow_condition import EMPTY_OPERATORS, evaluate_group, normalize_group
    from asoud_erp.services.workflow_condition_binding import catalog, validate_bindings

    try:
        normalized = normalize_group(raw)
        validate_bindings(normalized, catalog(definition, stage))
    except ValueError as error:
        frappe.throw(str(error))
    frappe.db.savepoint('asoud_condition_test')
    try:
        rows, errored = [], False
        for row in normalized['conditions']:
            if row['operator'] not in EMPTY_OPERATORS and row['id'] not in raw_samples:
                rows.append(dict(id=row['id'], result=None, error='برای این شرط مقدار نمونه وارد نشده است.'))
                errored = True
                continue
            one_row = dict(normalized, conditions=[row])
            try:
                result = evaluate_group(one_row, lambda rule, _row=row: raw_samples.get(_row['id']))
                rows.append(dict(id=row['id'], result=result, error=None))
            except ValueError as error:
                rows.append(dict(id=row['id'], result=None, error=str(error)))
                errored = True
        final = None if errored else evaluate_group(normalized, lambda rule: raw_samples.get(rule['id']))
        return success({"result": final, "rows": rows})
    finally:
        frappe.db.rollback(save_point='asoud_condition_test')


@frappe.whitelist(methods=["POST"])
def add_condition_branch(
    definition: str,
    condition_stage: str,
    stage_type: str,
    result: int | bool | str,
) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    if stage_type not in STAGE_TITLES:
        frappe.throw(_("Invalid workflow stage type"))
    truthy = result is True or str(result).lower() in {"1", "true"}
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    condition = frappe.get_doc("ASOUD Workflow Stage", condition_stage)
    if condition.workflow_definition != definition or condition.stage_type != "Condition":
        frappe.throw(_("Selected stage is not a condition in this workflow"))
    if json.loads(condition.config_json or '{}').get('condition_version') == 2:
        from asoud_erp.services.workflow_condition_binding import assert_editable

        assert_editable(definition)
    transitions = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition, "from_stage": condition.name},
        fields=["condition_json"],
        limit_page_length=0,
    )
    if any(json.loads(row.condition_json or "{}").get("result") is truthy for row in transitions):
        frappe.throw(_("This condition result already has a branch"))
    sequence = int(condition.sequence_no or 0) + 1
    stage = frappe.get_doc({
        "doctype": "ASOUD Workflow Stage",
        "workflow_definition": definition,
        "stage_key": f"stage-{frappe.generate_hash(length=10)}",
        "stage_type": stage_type,
        "stage_title": STAGE_TITLES[stage_type],
        "sequence_no": sequence,
        "configuration_status": "Pending" if stage_type != "End" else "Complete",
        "config_json": "{}",
        "position_x": 180 if truthy else -180,
        "position_y": sequence * 180,
    }).insert()
    frappe.get_doc({
        "doctype": "ASOUD Workflow Transition",
        "workflow_definition": definition,
        "from_stage": condition.name,
        "to_stage": stage.name,
        "transition_label": _("Yes") if truthy else _("No"),
        "condition_json": json.dumps({"result": truthy}),
        "sequence_no": 1 if truthy else 2,
    }).insert()
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.steps_count = frappe.db.count(
        "ASOUD Workflow Stage", {"workflow_definition": definition, "stage_type": ["!=", "Start"]}
    )
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()
    return success(_design_payload(definition))


def _assert_form_is_editable(definition: str, stage) -> None:
    """The form of a system template is owned by its code spec; approvers stay editable."""
    if not frappe.db.get_value("ASOUD Workflow Definition", definition, "is_system_template"):
        return
    from asoud_erp.api.v1.workflow_request import form_stage_name

    if form_stage_name(definition) == stage.name:
        frappe.throw(_("فرم این نوع درخواست توسط سیستم مدیریت می‌شود"))


def _validate_supplementary_binding(definition: str, raw: dict) -> dict | None:
    """Validate an Approval stage's ``supplementary_form`` binding and return it with a title."""
    from asoud_erp.services import stage_supplementary_form as ssf

    binding = ssf.read_binding(raw)
    if binding is None:
        return None
    try:
        binding = ssf.validate_binding_shape(binding)
    except ValueError as error:
        frappe.throw(_(str(error)))
    form = frappe.db.get_value(
        "ASOUD Form", binding["form"],
        ["name", "company", "kind", "disabled"], as_dict=True)
    if not form:
        frappe.throw(_("فرم تکمیلی مرحله پیدا نشد."))
    if form.kind != "Stage":
        frappe.throw(_("فرم تکمیلی مرحله باید از نوع فرم مرحله باشد."))
    company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
    if company and form.company != company:
        frappe.throw(_("فرم تکمیلی مرحله باید متعلق به همین دفتر باشد."))
    if form.disabled:
        frappe.throw(_("فرم تکمیلی مرحله غیرفعال است."))
    revision = frappe.db.get_value(
        "ASOUD Form Revision", binding["revision"], ["name", "form", "schema_json"], as_dict=True)
    if not revision or revision.form != binding["form"]:
        frappe.throw(_("نسخهٔ انتخاب‌شده متعلق به این فرم نیست."))
    schema = json.loads(revision.schema_json)
    return {**binding, "title": schema.get("title", "")}


@frappe.whitelist(methods=["POST"])
def save_stage_settings(definition: str, stage: str, config: str | dict) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    frappe.db.sql('select name from `tabASOUD Workflow Definition` where name=%s for update', (definition,))
    doc = frappe.get_doc("ASOUD Workflow Stage", stage)
    if doc.workflow_definition != definition:
        frappe.throw(_("Stage does not belong to the selected workflow"))
    if doc.stage_type == "Start":
        frappe.throw(_("Use the start settings endpoint for the start stage"))
    _assert_form_is_editable(definition, doc)
    raw = json.loads(config) if isinstance(config, str) else config
    if not isinstance(raw, dict):
        frappe.throw(_("Stage configuration must be an object"))
    supplementary = None
    if "supplementary_form" in raw:
        if doc.stage_type != "Approval":
            frappe.throw(_("فرم تکمیلی فقط برای مرحلهٔ تأیید قابل تنظیم است."))
        supplementary = _validate_supplementary_binding(definition, raw)
        if supplementary is not None and (raw.get("form_fields") or raw.get("form_layout")):
            frappe.throw(_("با انتخاب فرم تکمیلی، فیلدهای درون‌خطی مرحله باید خالی باشند."))
    if (doc.stage_type == 'Condition' and json.loads(doc.config_json or '{}').get('condition_version') == 2
            and raw.get('condition_version') != 2):
        frappe.throw('برای حفظ شروط ترکیبی، این مرحله را با نسخهٔ به‌روز برنامه ویرایش کنید.')
    if doc.stage_type == 'User Task' and raw.get('submission_source'):
        start_config = frappe.db.get_value('ASOUD Workflow Stage',
            {'workflow_definition': definition, 'stage_type': 'Start'}, 'config_json')
        if json.loads(start_config or '{}').get('start_settings_version') == 1:
            frappe.throw('انتخاب درخواست یا سند فقط از تنظیمات شروع فرایند انجام می‌شود.')
    if doc.stage_type == 'User Task' and 'submission_source' not in raw:
        previous_source = json.loads(doc.config_json or '{}').get('submission_source')
        if previous_source:
            raw = {**raw, 'submission_source': previous_source}
    try:
        normalized = normalize_stage_config(doc.stage_type, raw)
        if normalized.get('form_fields'):
            from asoud_erp.services.form_execution.stage_validation import validate_for_workflow

            validate_for_workflow(definition, normalized['form_fields'])
    except ValueError as error:
        frappe.throw(_(str(error)))
    if supplementary is not None:
        normalized["supplementary_form"] = supplementary

    role_field = ROLE_BASED_TYPES.get(doc.stage_type)
    if doc.stage_type == "User Task":
        if normalized.get('action_contract_version') == 1:
            from asoud_erp.services.workflow_user_action import validate_design

            validate_design(definition, normalized)
        from asoud_erp.services.workflow_submission_source import bind

        bind(definition, doc.name, normalized)
        from asoud_erp.services.user_task_output import validate_target
        validate_target(definition, normalized)
    roles = normalized.get(role_field, []) if role_field else normalized.get("target_roles", [])
    if roles and any(not frappe.db.exists("Role", role) for role in roles):
        frappe.throw(_("One or more selected roles do not exist"))
    if doc.stage_type in ROLE_BASED_TYPES:
        prefix = "assignee" if doc.stage_type == "User Task" else "approver"
        departments = normalized.get(f"{prefix}_departments", [])
        employees = normalized.get(f"{prefix}_employees", [])
        if departments and any(not frappe.db.exists("Department", value) for value in departments):
            frappe.throw(_("One or more selected departments do not exist"))
        if employees:
            active_employees = frappe.get_all(
                "Employee",
                filters={"name": ["in", employees], "status": "Active"},
                fields=["name", "user_id"],
            )
            if {row.name for row in active_employees} != set(employees):
                frappe.throw(_("One or more selected employees do not exist or are inactive"))
            if any(not row.user_id for row in active_employees):
                frappe.throw(_("Selected employees must have an ERPNext user account for inbox assignment"))
            company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
            if company and frappe.db.count(
                "Employee", {"name": ["in", employees], "company": ["!=", company]}
            ):
                frappe.throw(_("Selected employees must belong to the workflow company"))
    if doc.stage_type == "Condition":
        if normalized.get('condition_version') == 2:
            from asoud_erp.services.workflow_condition_binding import (
                assert_editable,
                catalog,
                validate_bindings,
            )

            assert_editable(definition)
            try:
                validate_bindings(normalized, catalog(definition, stage))
            except ValueError as error:
                frappe.throw(str(error))
        elif normalized["source_kind"] == "Document":
            target_doctype = frappe.db.get_value("ASOUD Workflow Definition", definition, "target_doctype")
            meta = frappe.get_meta(target_doctype)
            field = meta.get_field(normalized["source_field"])
            allowed_types = {"Data", "Select", "Link", "Int", "Float", "Currency", "Check", "Date", "Datetime"}
            if not field or field.fieldtype not in allowed_types or field.hidden:
                frappe.throw(_("The selected condition field is not allowed"))
        else:
            configs = frappe.get_all(
                "ASOUD Workflow Stage",
                filters={
                    "workflow_definition": definition,
                    "stage_type": "User Task",
                    "sequence_no": ["<", doc.sequence_no],
                },
                pluck="config_json",
                limit_page_length=0,
            )
            form_keys = {
                field.get("key")
                for config in configs
                for field in json.loads(config or "{}").get("form_fields", [])
            }
            for config in configs:
                form_keys.update(item['fieldname'] for item in action_condition_fields(json.loads(config or '{}')))
            from asoud_erp.services.workflow_submission_source import condition_fields

            form_keys.update(item['fieldname'] for item in condition_fields(definition))
            if normalized["source_field"] not in form_keys:
                frappe.throw(_("The selected form field does not exist in this workflow"))

    if doc.stage_type == "System Action" and normalized.get("schema_version") == 2:
        from asoud_erp.services.automatic_action_metadata import validate_config

        validate_config(definition, stage, normalized)
    if (doc.stage_type == "System Action" and normalized.get("schema_version") != 2
            and normalized["action_type"] == "Create Document"):
        company = frappe.db.get_value("ASOUD Workflow Definition", definition, "company")
        template = frappe.db.get_value(
            "ASOUD Document Template", normalized["document_template"], ["company", "status"], as_dict=True
        )
        if not template or template.status != "Active" or (company and template.company != company):
            frappe.throw(_("The selected document template is not active for this company"))

    doc.stage_title = normalized.pop("title")
    doc.config_json = json.dumps(normalized, ensure_ascii=False)
    doc.configuration_status = "Complete"
    doc.save()
    workflow = frappe.get_doc("ASOUD Workflow Definition", definition)
    workflow.version_no = int(workflow.version_no or 1) + 1
    workflow.save()
    return success(_design_payload(definition))


ROUTE_ACTIONS = {
    "Approval": ("Approve", "Reject", "Return"),
    "User Task": ("Complete", "Reject", "Return"),
    "System Action": ("Success", "Error"),
}
ROUTE_LABELS = {
    "Approve": "تأیید",
    "Reject": "رد",
    "Return": "بازگشت برای اصلاح",
    "Complete": "ادامه",
    "Success": "موفقیت",
    "Error": "خطا",
}


@frappe.whitelist(methods=["POST"])
def save_stage_routes(definition: str, stage: str, routes: str | dict) -> dict:
    """Set a stage's exit routes by decision, e.g. {"Approve": stage, "Reject": ""}.

    An empty target removes the route: Reject then ends the request as rejected,
    Return goes back to the latest editable task and Error stops the instance.
    Setting the main route (Approve/Complete/Success) replaces the unlabeled
    default route the designer created.
    """
    require_roles(("System Manager", "Accounts Manager"))
    frappe.db.sql(
        "select name from `tabASOUD Workflow Definition` where name = %s for update",
        (definition,),
    )
    source = _assert_stage_in_definition(stage, definition)
    allowed = ROUTE_ACTIONS.get(source.stage_type)
    if not allowed:
        frappe.throw(_("This stage has no decision routes"))
    raw = json.loads(routes) if isinstance(routes, str) else routes
    if not isinstance(raw, dict) or set(raw) - set(allowed):
        frappe.throw(_("Invalid workflow routes"))
    existing = frappe.get_all(
        "ASOUD Workflow Transition",
        filters={"workflow_definition": definition, "from_stage": stage},
        fields=["name", "transition_label", "condition_json"],
        limit_page_length=0,
    )
    removed = set()
    for action, target in raw.items():
        target = str(target or "").strip()
        if target:
            destination = _assert_stage_in_definition(target, definition)
            if target == stage or destination.stage_type == "Start":
                frappe.throw(_("Invalid workflow transition"))
            if (source.stage_type == "System Action" and action == "Error"
                    and json.loads(source.config_json or "{}").get("schema_version") == 2
                    and destination.stage_type != "User Task"):
                frappe.throw(_("Automatic action error routes must target a human task"))
        for row in existing:
            if row.name in removed:
                continue
            row_action = str(json.loads(row.condition_json or "{}").get("action") or "")
            if not row_action:
                row_action = {label: key for key, label in ROUTE_LABELS.items()}.get(
                    row.transition_label or "", row.transition_label or ""
                )
            if row_action.casefold() == action.casefold() or (action == allowed[0] and not row_action):
                frappe.delete_doc("ASOUD Workflow Transition", row.name, ignore_permissions=True)
                removed.add(row.name)
        if target:
            frappe.get_doc(
                {
                    "doctype": "ASOUD Workflow Transition",
                    "workflow_definition": definition,
                    "from_stage": stage,
                    "to_stage": target,
                    "transition_label": ROUTE_LABELS[action],
                    "condition_json": json.dumps({"action": action}),
                    "sequence_no": allowed.index(action) + 1,
                }
            ).insert()
    _touch_workflow(definition)
    return success(_design_payload(definition))


@frappe.whitelist(methods=["POST"])
def update_request_type_info(
    name: str,
    workflow_title: str,
    short_title: str | None = None,
    process_description: str | None = None,
    request_category: str | None = None,
    icon_key: str | None = None,
    color_hex: str | None = None,
    show_in_request_list: int | str = 1,
    allow_user_submission: int | str = 1,
    module_key: str | None = None,
) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    doc = frappe.get_doc("ASOUD Workflow Definition", name)
    # Also used by the start-node metadata editor. Never change its reference
    # DocType, company, graph or start permissions when editing presentation.
    if module_key is not None and module_key not in MODULE_DOCTYPES:
        frappe.throw(_("Invalid workflow module"))
    title = (workflow_title or "").strip()
    if len(title) < 3:
        frappe.throw(_("Workflow title must contain at least 3 characters"))
    if request_category and request_category not in REQUEST_CATEGORIES:
        frappe.throw(_("Invalid request category"))
    doc.workflow_title = title
    doc.process_description = (process_description or "").strip()
    if module_key is not None:
        doc.module_key = module_key
    doc.icon_key = icon_key
    doc.color_hex = color_hex
    if doc.target_doctype == "ASOUD Workflow Request":
        doc.short_title = (short_title or "").strip()[:140]
        doc.request_category = request_category or ""
        doc.show_in_request_list = cint(show_in_request_list)
        doc.allow_user_submission = cint(allow_user_submission)
    doc.save()
    return success(serialize_workflow(doc.as_dict()))


@frappe.whitelist(methods=["POST"])
def set_workflow_status(name: str, status: str) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        frappe.throw('وضعیت انتخاب‌شده برای گردش‌کار معتبر نیست.')
    if not isinstance(name, str) or not name.strip() or len(name) > 140:
        frappe.throw('گردش‌کار انتخاب‌شده معتبر نیست.')
    if not frappe.db.exists('ASOUD Workflow Definition', name):
        frappe.throw('گردش‌کار انتخاب‌شده دیگر در دسترس نیست.')
    doc = frappe.get_doc("ASOUD Workflow Definition", name, for_update=True)
    require_company(doc.company)
    doc.check_permission('write')
    doc.status = status
    doc.archived_on = now_datetime() if status == "Archived" else None
    doc.save()
    from asoud_erp.services.workflow_contract import is_system_workflow

    row = doc.as_dict()
    row['can_delete'] = bool(doc.has_permission('delete')) and not is_system_workflow(row)
    return success(serialize_workflow(row))


@frappe.whitelist(methods=["POST"])
def delete_workflow(name=None) -> dict:
    require_roles(("System Manager", "Accounts Manager"))
    if not isinstance(name, str) or not name.strip() or len(name) > 140:
        frappe.throw('شناسهٔ گردش‌کار معتبر نیست.')
    if not frappe.db.exists("ASOUD Workflow Definition", name):
        frappe.throw('گردش‌کار موردنظر یافت نشد.')
    doc = frappe.get_doc("ASOUD Workflow Definition", name)
    if doc.company:
        require_company(doc.company)
    doc.check_permission('delete')
    # Native on_trash owns authorization, serialization, history and cleanup.
    frappe.db.savepoint('delete_workflow_api')
    try:
        frappe.delete_doc("ASOUD Workflow Definition", name)
    except frappe.LinkExistsError:
        frappe.db.rollback(save_point='delete_workflow_api')
        frappe.clear_messages()
        frappe.throw('این گردش‌کار یا مراحل آن وابستگی دارد؛ برای حفظ اطلاعات، حذف انجام نشد.')
    except Exception:
        frappe.db.rollback(save_point='delete_workflow_api')
        raise
    return success({"name": name, "deleted": True})
