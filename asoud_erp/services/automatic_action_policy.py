"""Version 2 automatic actions. Pure validation: no eval, database or privileges."""

import ast
import math
import operator
import re

ACTIONS = (
    "Create Request",
    "Create Document",
    "Update Fields",
    "Change Status",
    "Send Notification",
    "Calculate Value",
    "Link Record",
)
SOURCES = {"current", "stage", "constant", "system"}
SYSTEM_FIELDS = {"today": "Date", "now": "Datetime", "company": "Text", "initiator": "User"}
NUMERIC = {"Number", "Currency", "Int", "Float", "Percent"}
TEXT = {"Text", "Data", "Short Text", "Long Text", "Small Text", "SmallText", "Select"}
KEY = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
VARIABLE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


def bounded_int(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: expected integer {low}..{high}")
    return value


def identifier(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise ValueError("Invalid field identifier")
    return value


def text(value, label, limit=140):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} is required (maximum {limit} characters)")
    return value.strip()


def source(raw):
    if not isinstance(raw, dict) or set(raw) - {"source", "value", "stage", "transform", "empty"}:
        raise ValueError("Invalid field source")
    kind = raw.get("source")
    transform = raw.get("transform", "none")
    empty = raw.get("empty", "error")
    if kind not in SOURCES or transform not in {"none", "trim", "round2"} or empty not in {"error", "skip"}:
        raise ValueError("Invalid source, transformation or empty-value policy")
    value = raw.get("value")
    if kind != "constant":
        identifier(value)
    elif not isinstance(value, (str, int, float, bool)) or (isinstance(value, str) and len(value) > 2000):
        raise ValueError("Constant must be a scalar value")
    if kind == "system" and value not in SYSTEM_FIELDS:
        raise ValueError("Unknown system value")
    result = {"source": kind, "value": value, "transform": transform, "empty": empty}
    if kind == "stage":
        result["stage"] = text(raw.get("stage"), "Previous stage")
    elif raw.get("stage"):
        raise ValueError("Only a stage source may specify a previous stage")
    return result


def mappings(raw):
    if not isinstance(raw, dict) or not 1 <= len(raw) <= 30:
        raise ValueError("Map between 1 and 30 fields")
    return {identifier(key): source(value) for key, value in raw.items()}


def target(raw):
    if not isinstance(raw, dict) or set(raw) - {"source", "stage"}:
        raise ValueError("Invalid target record")
    if raw.get("source") == "current" and not raw.get("stage"):
        return {"source": "current"}
    if raw.get("source") == "stage":
        return {"source": "stage", "stage": text(raw.get("stage"), "Target stage")}
    raise ValueError("Target must be the current record or a previous stage output")


def validate_formula(expression, variables):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 300:
        raise ValueError("Formula must contain 1..300 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Invalid formula") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 80:
        raise ValueError("Formula is too complex")
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.USub,
        ast.UAdd,
    )
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError("Only numbers, variables and + - * / are allowed")
        if isinstance(node, ast.Name) and node.id not in variables:
            raise ValueError(f"Unknown formula variable: {node.id}")
        if isinstance(node, ast.Constant):
            number(node.value)
    return tree


def number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("A finite numeric value is required") from exc
    if not math.isfinite(result) or abs(result) > 1e15:
        raise ValueError("Numeric value is outside the permitted range")
    return result


def calculate(method, values, formula=""):
    operands = {key: number(value) for key, value in values.items()}
    if not operands:
        raise ValueError("Calculation requires inputs")
    if method == "sum":
        return number(sum(operands.values()))
    if method == "average":
        return number(sum(operands.values()) / len(operands))
    if method != "formula":
        raise ValueError("Unsupported calculation")
    tree = validate_formula(formula, operands)
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return number(node.value)
        if isinstance(node, ast.Name):
            return operands[node.id]
        if isinstance(node, ast.UnaryOp):
            return number(-visit(node.operand) if isinstance(node.op, ast.USub) else visit(node.operand))
        try:
            return number(operations[type(node.op)](visit(node.left), visit(node.right)))
        except ZeroDivisionError as exc:
            raise ValueError("Division by zero") from exc

    return visit(tree)


def normalize_action(raw):
    if not isinstance(raw, dict) or set(raw) - {
        "title",
        "description",
        "schema_version",
        "action_type",
        "operation",
        "execution",
    }:
        raise ValueError(
            "Unexpected automatic action settings (human assignment and audit switches are not allowed)"
        )
    if raw.get("schema_version") != 2:
        raise ValueError("Unsupported automatic action schema")
    kind = raw.get("action_type")
    if kind not in ACTIONS:
        raise ValueError("Unsupported automatic action")
    payload = raw.get("operation")
    if not isinstance(payload, dict):
        raise ValueError("Operation configuration is required")
    keys = {
        "Create Request": {"request_type", "mapping", "link_original"},
        "Create Document": {"doctype", "initial_state", "mapping", "link_original"},
        "Update Fields": {"target", "mapping"},
        "Change Status": {"target", "transition"},
        "Send Notification": {"recipients", "channels", "message"},
        "Calculate Value": {"target", "field", "method", "inputs", "formula"},
        "Link Record": {"target", "doctype", "lookup_field", "lookup", "relationship", "missing", "multiple"},
    }[kind]
    if set(payload) - keys:
        raise ValueError("Configuration contains fields from another action")
    result = {}
    if "target" in keys:
        result["target"] = target(payload.get("target"))
    if "mapping" in keys:
        result["mapping"] = mappings(payload.get("mapping"))
    if kind.startswith("Create"):
        link = payload.get("link_original", True)
        if type(link) is not bool:
            raise ValueError("Invalid link option")
        result["link_original"] = link
        key = "request_type" if kind == "Create Request" else "doctype"
        result[key] = text(payload.get(key), key)
        if kind == "Create Document":
            state = payload.get("initial_state", "Draft")
            if state not in {"Draft", "Submitted"}:
                raise ValueError("Invalid initial state")
            result["initial_state"] = state
    elif kind == "Change Status":
        result["transition"] = text(payload.get("transition"), "Workflow transition")
    elif kind == "Send Notification":
        recipients = payload.get("recipients")
        channels = payload.get("channels")
        if not isinstance(recipients, list) or not 1 <= len(recipients) <= 30:
            raise ValueError("Choose 1..30 recipients")
        result["recipients"] = list(dict.fromkeys(text(item, "Recipient") for item in recipients))
        if not isinstance(channels, list) or not channels or set(channels) - {"in_app", "email"}:
            raise ValueError("Choose in-app notification and/or email")
        result["channels"] = list(dict.fromkeys(channels))
        result["message"] = text(payload.get("message"), "Message", 2000)
        stripped = VARIABLE.sub("", result["message"])
        if "{{" in stripped or "}}" in stripped:
            raise ValueError("Invalid message variable")
    elif kind == "Calculate Value":
        result["field"] = identifier(payload.get("field"))
        result["inputs"] = mappings(payload.get("inputs"))
        method = payload.get("method")
        if method not in {"sum", "average", "formula"}:
            raise ValueError("Invalid calculation method")
        result["method"] = method
        if method == "formula":
            validate_formula(payload.get("formula"), result["inputs"])
            result["formula"] = payload["formula"]
        elif payload.get("formula"):
            raise ValueError("Hidden formula is not allowed")
    elif kind == "Link Record":
        result["doctype"] = text(payload.get("doctype"), "Linked record type")
        result["lookup_field"] = identifier(payload.get("lookup_field"))
        result["lookup"] = source(payload.get("lookup"))
        if payload.get("relationship") not in {"related", "supports", "follows"}:
            raise ValueError("Invalid relationship")
        if payload.get("missing") not in {"error", "skip"} or payload.get("multiple") != "error":
            raise ValueError("Ambiguous matches must stop; choose a missing-record policy")
        result.update({key: payload[key] for key in ("relationship", "missing", "multiple")})
    policy = raw.get("execution", {})
    if not isinstance(policy, dict) or set(policy) - {"extra_attempts", "retry_seconds", "timeout_seconds"}:
        raise ValueError("Invalid execution policy; audit cannot be disabled")
    execution = {
        "extra_attempts": bounded_int(policy.get("extra_attempts", 0), 0, 5, "Extra attempts"),
        "retry_seconds": bounded_int(policy.get("retry_seconds", 60), 30, 3600, "Retry interval"),
        "timeout_seconds": bounded_int(policy.get("timeout_seconds", 120), 10, 300, "Technical timeout"),
    }
    return {"schema_version": 2, "action_type": kind, "operation": result, "execution": execution}


def retry_delay(policy, failed_attempt, *, transient):
    if not transient or failed_attempt > policy["extra_attempts"]:
        return None
    return min(3600, policy["retry_seconds"] * 2 ** (failed_attempt - 1))


def resolve(entry, context):
    kind = entry["source"]
    if kind == "constant":
        value = entry["value"]
    elif kind == "stage":
        if entry["stage"] not in context.get("stages", {}):
            raise ValueError("The selected previous stage has not completed")
        value = context["stages"][entry["stage"]].get(entry["value"])
    else:
        value = context.get(kind, {}).get(entry["value"])
    if value is None or value == "" or value == []:
        if entry["empty"] == "error":
            raise ValueError(f"Source value is empty: {entry['value']}")
        return None
    if entry["transform"] == "trim":
        if not isinstance(value, str):
            raise ValueError("Trim requires text")
        value = value.strip()
    if entry["transform"] == "round2":
        value = round(number(value), 2)
    if value == "" and entry["empty"] == "error":
        raise ValueError("Source value is empty after transformation")
    return value
