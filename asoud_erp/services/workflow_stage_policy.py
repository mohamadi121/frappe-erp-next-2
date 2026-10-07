import re
from typing import Any

from asoud_erp.services.request_lookup import ITEM_SCOPES, SOURCE_FIELD_TYPES

STAGE_TYPES = {"User Task", "Approval", "Condition", "System Action", "Wait", "End"}
ROLE_BASED_TYPES = {"User Task": "assignee_roles", "Approval": "approver_roles"}
FORM_FIELD_TYPES = {
    "Short Text", "Long Text", "Number", "Currency", "Date", "Choice", "Attachment", "Checkbox",
    "Multi Choice", "User", "Department", "Item Table", "Table", "Time", "System Select", "Auto",
}
# Values of these types are ERPNext record names, validated against User, Department and Item.
LINK_FIELD_TYPES = {"User", "Department", "Item Table"}
CHOICE_FIELD_TYPES = {"Choice", "Multi Choice"}
NO_DEFAULT_FIELD_TYPES = {"Attachment", "Item Table", "User", "Department", "Table", "System Select", "Auto"}
TEXT_FIELD_TYPES = {"Short Text", "Long Text"}
AUTO_KINDS = {"request_number", "request_date", "leave_duration"}
FIELD_WIDGETS = {"segmented", "chips", "dropdown", "textarea"}
CHOICE_WIDGETS = {"segmented", "chips", "dropdown"}
# default_source -> the field types it can fill.
DEFAULT_SOURCES = {
    "session_user": {"User"},
    "employee_department": {"Department"},
    "employee_branch": {"System Select"},
    "today": {"Date"},
}
REQUIRED_BY_SETTINGS = {"request_cost_center_required"}
MAX_ROW_LIMIT = 100
TIME_DEFAULT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TABLE_COLUMN_TYPES = {"Short Text", "Number", "Currency", "Date", "Choice", "Attachment"}
REQUEST_CATEGORIES = {"Finance", "HR", "Purchase", "IT", "General", "Other"}
ASSIGNMENT_TYPES = {"Role", "Department", "Employee", "Initiator", "Initiator Department", "Direct Manager"}
# Assignment types resolved from the request initiator; they need no target list.
INITIATOR_ASSIGNMENTS = {"Initiator", "Initiator Department", "Direct Manager"}
SYSTEM_ACTION_TYPES = {"Send Notification", "Assign Role", "Change Status", "Create Document"}


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _normalize_form_fields(values: Any) -> list[dict[str, Any]]:
    if values in (None, []):
        return []
    if not isinstance(values, list) or len(values) > 30:
        raise ValueError("Form fields must be a list with at most 30 items")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for position, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise ValueError("Invalid form field")
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        field_type = item.get("type")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", key) or key in keys:
            raise ValueError("Form field keys must be unique safe identifiers")
        if not 2 <= len(label) <= 80:
            raise ValueError("Form field label is required")
        if field_type not in FORM_FIELD_TYPES:
            raise ValueError("Unsupported form field type")
        columns = []
        if field_type == "Table":
            raw_columns = item.get("columns")
            if not isinstance(raw_columns, list) or not 1 <= len(raw_columns) <= 12:
                raise ValueError("Tables require between 1 and 12 columns")
            if any(not isinstance(column, dict) or column.get("type") not in TABLE_COLUMN_TYPES
                   for column in raw_columns):
                raise ValueError("Unsupported table column type")
            columns = _normalize_form_fields(raw_columns)
        options = _unique_strings(item.get("options"))
        if field_type in CHOICE_FIELD_TYPES and len(options) < 2:
            raise ValueError("Choice fields require at least two options")
        if field_type not in CHOICE_FIELD_TYPES:
            options = []
        default_value = str(item.get("default_value") or "").strip()
        if len(default_value) > 140:
            raise ValueError("Form field default value is too long")
        if field_type in NO_DEFAULT_FIELD_TYPES and default_value:
            raise ValueError("This form field type has no default value")
        if field_type in CHOICE_FIELD_TYPES and default_value and default_value not in options:
            raise ValueError("Choice default value must be one of the options")
        if field_type == "Time" and default_value and not TIME_DEFAULT.fullmatch(default_value):
            raise ValueError("Time default value must be HH:MM")
        keys.add(key)
        result.append({
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required", False)),
            "options": options,
            "default_value": default_value,
            "help_text": str(item.get("help_text") or "").strip()[:200],
            "show_in_list": bool(item.get("show_in_list", False)),
            "position": position,
            **({"columns": columns} if field_type == "Table" else {}),
            **_field_extensions(item, field_type, options),
        })
    for field in result:
        rule = field.get("visible_when")
        if rule and (rule["field"] == field["key"] or rule["field"] not in keys):
            raise ValueError("A conditional field must depend on another field of the form")
    return result


def _field_extensions(item: dict[str, Any], field_type: str, options: list[str]) -> dict[str, Any]:
    """Optional presentation and validation attributes; only the ones that are set are kept."""
    result: dict[str, Any] = {}
    if field_type == "System Select":
        source = item.get("source")
        if source not in SOURCE_FIELD_TYPES:
            raise ValueError("A system select field needs a supported source")
        result["source"] = source
    elif item.get("source") not in (None, ""):
        raise ValueError("Only system select fields have a source")
    if field_type == "Auto":
        if item.get("auto") not in AUTO_KINDS:
            raise ValueError("An auto field needs a supported kind")
        result["auto"] = item["auto"]
    elif item.get("auto") not in (None, ""):
        raise ValueError("Only auto fields have a kind")
    if item.get("visible_when") not in (None, {}):
        result["visible_when"] = _visible_when(item["visible_when"])
    if item.get("option_labels") not in (None, {}):
        result["option_labels"] = _option_labels(item["option_labels"], field_type, options)
    if item.get("widget") not in (None, ""):
        result["widget"] = _widget(item["widget"], field_type)
    if item.get("default_source") not in (None, ""):
        source = item["default_source"]
        if source not in DEFAULT_SOURCES or field_type not in DEFAULT_SOURCES[source]:
            raise ValueError("Unsupported default source for this field type")
        result["default_source"] = source
    if "editable" in item:
        result["editable"] = bool(item["editable"])
    if item.get("min_date") not in (None, ""):
        if item["min_date"] != "today" or field_type != "Date":
            raise ValueError("Only date fields support a minimum date of today")
        result["min_date"] = "today"
    if item.get("max_length") not in (None, ""):
        limit = item["max_length"]
        if type(limit) is not int or not 1 <= limit <= 10000 or field_type not in TEXT_FIELD_TYPES:
            raise ValueError("Maximum length applies to text fields, between 1 and 10000")
        result["max_length"] = limit
    if item.get("required_by_setting") not in (None, ""):
        if item["required_by_setting"] not in REQUIRED_BY_SETTINGS:
            raise ValueError("Unsupported required-by setting")
        result["required_by_setting"] = item["required_by_setting"]
    if field_type == "Item Table" and item.get("row_options") is not None:
        result["row_options"] = _row_options(item["row_options"])
    elif item.get("row_options") is not None:
        raise ValueError("Only item tables have row options")
    return result


def _visible_when(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, dict) or not isinstance(rule.get("field"), str):
        raise ValueError("Invalid conditional field rule")
    if ("equals" in rule) == ("in" in rule):
        raise ValueError("A conditional field rule needs either equals or in")
    scalar = (str, int, float, bool)
    if "equals" in rule:
        if not isinstance(rule["equals"], scalar):
            raise ValueError("Invalid conditional field value")
        return {"field": rule["field"], "equals": rule["equals"]}
    values = rule["in"]
    if not isinstance(values, list) or not 1 <= len(values) <= 20 or any(
            not isinstance(value, scalar) for value in values):
        raise ValueError("Invalid conditional field values")
    return {"field": rule["field"], "in": values}


def _option_labels(labels: Any, field_type: str, options: list[str]) -> dict[str, str]:
    if field_type != "Choice" or not isinstance(labels, dict):
        raise ValueError("Option labels apply to choice fields")
    result = {}
    for stored, label in labels.items():
        if stored not in options or not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            raise ValueError("Option labels must label existing options")
        result[stored] = label.strip()
    return result


def _widget(widget: Any, field_type: str) -> str:
    if widget not in FIELD_WIDGETS:
        raise ValueError("Unsupported field widget")
    if widget in CHOICE_WIDGETS and field_type not in CHOICE_FIELD_TYPES:
        raise ValueError("This widget is only for choice fields")
    if widget == "textarea" and field_type not in TEXT_FIELD_TYPES:
        raise ValueError("This widget is only for text fields")
    return widget


def _row_options(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Invalid item row options")
    scope = raw.get("item_scope", "all")
    if scope not in ITEM_SCOPES:
        raise ValueError("Unsupported item scope")
    try:
        minimum, maximum = int(raw.get("min_rows", 0)), int(raw.get("max_rows", MAX_ROW_LIMIT))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid item row limits") from error
    if not 0 <= minimum <= maximum <= MAX_ROW_LIMIT:
        raise ValueError("Invalid item row limits")
    return {"item_scope": scope, "note": bool(raw.get("note", False)),
            "attachment": bool(raw.get("attachment", False)), "min_rows": minimum, "max_rows": maximum}


def _normalize_form_layout(values: Any, fields: list[dict]) -> list[dict]:
    """Presentation metadata only; never replaces native request fields."""
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 37:
        raise ValueError("Invalid form layout")
    allowed = {"base:number", "base:author", "base:department", "base:date",
               "base:status", "base:description", "base:attachments"}
    allowed.update(field["key"] for field in fields)
    seen = set()
    result = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("Invalid form placement")
        key = item.get("key")
        if not isinstance(key, str) or key not in allowed or key in seen:
            raise ValueError("Unknown or duplicate form placement")
        if type(item.get("span")) is not int or item["span"] not in (1, 2):
            raise ValueError("Invalid form width")
        seen.add(key)
        result.append({"key": key, "span": item["span"]})
    return result


def _normalize_assignment(raw: dict[str, Any], prefix: str) -> dict[str, Any]:
    assignment_type = str(raw.get("assignment_type") or "Role")
    if assignment_type not in ASSIGNMENT_TYPES:
        raise ValueError("Invalid assignment type")
    roles = _unique_strings(raw.get(f"{prefix}_roles"))
    departments = _unique_strings(raw.get(f"{prefix}_departments"))
    employees = _unique_strings(raw.get(f"{prefix}_employees"))
    selected = {
        "Role": roles,
        "Department": departments,
        "Employee": employees,
    }.get(assignment_type, ["initiator"])
    if not selected:
        raise ValueError("At least one assignment target is required")
    return {
        "assignment_type": assignment_type,
        f"{prefix}_roles": roles if assignment_type == "Role" else [],
        f"{prefix}_departments": departments if assignment_type == "Department" else [],
        f"{prefix}_employees": employees if assignment_type == "Employee" else [],
    }


def normalize_stage_config(stage_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    if stage_type not in STAGE_TYPES:
        raise ValueError("Unsupported stage type")
    title = str(raw.get("title") or "").strip()
    if len(title) < 2:
        raise ValueError("Stage title is required")

    if stage_type == "User Task":
        activity_type = raw.get("activity_type")
        if activity_type not in {"Data Entry", "Review", "Correction", "Task"}:
            raise ValueError("Invalid user task activity")
        assignment = _normalize_assignment(raw, "assignee")
        fields = _normalize_form_fields(raw.get("form_fields"))
        return {
            "title": title,
            "activity_type": activity_type,
            **assignment,
            "instructions": str(raw.get("instructions") or "").strip(),
            "form_fields": fields,
            **({"form_layout": _normalize_form_layout(raw["form_layout"], fields)}
               if "form_layout" in raw else {}),
            "document_access": _document_access(raw),
            "allow_reject": bool(raw.get("allow_reject", False)),
            "allow_return": bool(raw.get("allow_return", False)),
            "comment_required": bool(raw.get("comment_required", False)),
            "reject_comment_required": bool(raw.get("reject_comment_required", False)),
            "allow_draft": bool(raw.get("allow_draft", True)),
            "require_all_fields": bool(raw.get("require_all_fields", False)),
            "allow_edit_after_submit": bool(raw.get("allow_edit_after_submit", False)),
            "description": _description(raw),
            **_deadline_policy(raw),
        }

    if stage_type == "Approval":
        assignment = _normalize_assignment(raw, "approver")
        mode = raw.get("approval_mode")
        if mode not in {"Any", "All"}:
            raise ValueError("Invalid approval mode")
        return {
            "title": title,
            **assignment,
            "approval_mode": mode,
            "form_fields": _normalize_form_fields(raw.get("form_fields")),
            "document_access": _document_access(raw),
            "allow_reject": bool(raw.get("allow_reject", True)),
            "allow_return": bool(raw.get("allow_return", True)),
            "comment_required": bool(raw.get("comment_required", False)),
            "reject_comment_required": bool(raw.get("reject_comment_required", False)),
            "description": _description(raw),
            **_deadline_policy(raw),
        }

    if stage_type == "Condition":
        source_kind = raw.get("source_kind") or "Document"
        if source_kind not in {"Document", "Form"}:
            raise ValueError("Invalid condition source")
        source_field = str(raw.get("source_field") or "").strip()
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", source_field):
            raise ValueError("Invalid condition field")
        operator = raw.get("operator")
        if operator not in {"Equals", "Not Equals", "Greater Than", "Less Than", "Contains", "Is Set"}:
            raise ValueError("Invalid condition operator")
        compare_value = str(raw.get("compare_value") or "").strip()
        if operator != "Is Set" and not compare_value:
            raise ValueError("Condition comparison value is required")
        return {
            "title": title,
            "source_kind": source_kind,
            "source_field": source_field,
            "operator": operator,
            "compare_value": compare_value,
        }

    if stage_type == "System Action":
        return {"title": title, "description": _description(raw), **_system_action(raw)}

    if stage_type == "Wait":
        wait_type = raw.get("wait_type")
        if wait_type not in {"Duration", "Date", "Event"}:
            raise ValueError("Invalid wait type")
        value = str(raw.get("wait_value") or "").strip()
        if not value:
            raise ValueError("Wait value is required")
        if wait_type == "Duration" and (not value.isdigit() or not 1 <= int(value) <= 3650):
            raise ValueError("Wait duration must be between 1 and 3650")
        unit = raw.get("wait_unit") or "Day"
        if wait_type == "Duration" and unit not in {"Minute", "Hour", "Day"}:
            raise ValueError("Invalid wait unit")
        return {"title": title, "wait_type": wait_type, "wait_value": value, "wait_unit": unit}

    outcome = raw.get("outcome")
    if outcome not in {"Completed", "Rejected", "Cancelled", "Stopped"}:
        raise ValueError("Invalid workflow outcome")
    return {"title": title, "outcome": outcome, "result_label": str(raw.get("result_label") or "").strip()}


def _description(raw: dict[str, Any]) -> str:
    return str(raw.get("description") or "").strip()[:500]


def _system_action(raw: dict[str, Any]) -> dict[str, Any]:
    """Automatic actions run by the workflow engine; calling external APIs is not offered."""
    if "schema_version" in raw:
        from asoud_erp.services.automatic_action_policy import normalize_action

        return normalize_action(raw)
    action_type = raw.get("action_type")
    if action_type not in SYSTEM_ACTION_TYPES:
        raise ValueError("Unsafe or unsupported system action")
    if action_type == "Create Document":
        template = str(raw.get("document_template") or "").strip()
        if not template or len(template) > 140:
            raise ValueError("A document template is required")
        return {
            "action_type": action_type,
            "document_template": template,
            "transfer_values": bool(raw.get("transfer_values", True)),
            "document_remark": str(raw.get("document_remark") or "").strip()[:500],
        }
    if action_type == "Change Status":
        status = str(raw.get("request_status") or "").strip()
        if not 2 <= len(status) <= 60:
            raise ValueError("A request status label is required")
        return {"action_type": action_type, "request_status": status}
    target_roles = _unique_strings(raw.get("target_roles"))
    notify_initiator = action_type == "Send Notification" and bool(raw.get("notify_initiator", False))
    if not target_roles and not notify_initiator:
        raise ValueError("At least one target role is required")
    message = str(raw.get("message") or "").strip()
    if action_type == "Send Notification" and not message:
        raise ValueError("A notification message is required")
    return {
        "action_type": action_type,
        "target_roles": target_roles,
        "notify_initiator": notify_initiator,
        "message": message[:1000],
    }


def _document_access(raw: dict[str, Any]) -> str:
    value = str(raw.get("document_access") or "Read Only")
    if value not in {"Read Only", "Edit", "Limited Edit"}:
        raise ValueError("Invalid document access mode")
    return value


def _deadline_policy(raw: dict[str, Any]) -> dict[str, Any]:
    value = raw.get("deadline_value")
    if value in (None, "", 0, "0"):
        return {
            "deadline_value": 0,
            "deadline_unit": "Hour",
            "reminder_before_minutes": 0,
            "escalation_roles": [],
            "reassign_on_overdue": False,
        }
    try:
        value = int(value)
        reminder = int(raw.get("reminder_before_minutes") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid deadline value") from error
    if not 1 <= value <= 3650 or not 0 <= reminder <= 525600:
        raise ValueError("Deadline or reminder is outside the allowed range")
    unit = raw.get("deadline_unit") or "Hour"
    if unit not in {"Minute", "Hour", "Day"}:
        raise ValueError("Invalid deadline unit")
    roles = _unique_strings(raw.get("escalation_roles"))
    reassign = bool(raw.get("reassign_on_overdue", False))
    if reassign and not roles:
        raise ValueError("Automatic reassignment requires an escalation role")
    return {
        "deadline_value": value,
        "deadline_unit": unit,
        "reminder_before_minutes": reminder,
        "escalation_roles": roles,
        "reassign_on_overdue": reassign,
    }
