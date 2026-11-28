"""Machine-readable manifest of the ``asoud_erp.api.v1`` contract.

Pure (no ``frappe`` import, no importing the API modules): the manifest is derived
from the source AST of ``api/v1`` plus the classification registry. That keeps the
three producers — the ``api_contract.manifest`` endpoint, ``scripts/gen_api_manifest.py``
and the stale-manifest guard test — on one code path, and lets the guard test run in
the lightweight CI without a bench.

Type hints are captured as their source text (``str``, ``int``, ``str | None``), not
resolved to runtime types, so no module is imported and the output is stable.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from asoud_erp.api.v1 import registry

#: The pilot tool set (plan A-WP2 §2.4): low-risk reads plus the one self-service write.
PILOT_METHODS: frozenset[str] = frozenset(
    {
        "asoud_erp.api.v1.auth.current_user",
        "asoud_erp.api.v1.session.login_state",
        "asoud_erp.api.v1.dashboard.get_home_summary",
        "asoud_erp.api.v1.selling.selling_options",
        "asoud_erp.api.v1.selling.list_sales_invoices",
        "asoud_erp.api.v1.selling.get_sales_invoice",
        "asoud_erp.api.v1.stock.list_items",
        "asoud_erp.api.v1.stock.stock_balance",
        "asoud_erp.api.v1.leave_request.get_leave_balance",
        "asoud_erp.api.v1.leave_request.preview_leave_request",
        "asoud_erp.api.v1.workflow_runtime.list_my_workflow_tasks",
        "asoud_erp.api.v1.workflow_runtime.get_workflow_task",
        "asoud_erp.api.v1.workflow_request.list_my_requests",
        "asoud_erp.api.v1.workflow_request.get_request",
        "asoud_erp.api.v1.forms.get_form",
        "asoud_erp.api.v1.support.create_issue",
    }
)

#: Protocol methods that are not tools: the offline-outbox entry point.
_PROTOCOL_METHODS: frozenset[str] = frozenset({"asoud_erp.api.v1.sync.execute_mutation"})

_GENERATED_BY = "scripts/gen_api_manifest.py"


def _http_methods(decorator: ast.Call) -> list[str]:
    for keyword in decorator.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
            values = [elt.value for elt in keyword.value.elts if isinstance(elt, ast.Constant)]
            if values:
                return values
    # No ``methods=`` means Frappe accepts both GET and POST.
    return ["GET", "POST"]


def _allow_guest(decorator: ast.Call) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg == "allow_guest":
            if keyword.value is None:
                return True
            if isinstance(keyword.value, ast.Constant):
                return bool(keyword.value.value)
    return False


def _first_docstring_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        text = node.body[0].value.value
        if isinstance(text, str):
            for line in text.strip().splitlines():
                line = line.strip()
                if line:
                    return line
    return None


def _parameter(name: str, annotation: ast.expr | None, default: ast.expr | None) -> dict:
    param = {
        "name": name,
        "type": ast.unparse(annotation) if annotation is not None else None,
        "required": default is None,
        "default": None,
    }
    if default is not None:
        try:
            param["default"] = ast.literal_eval(default)
        except (ValueError, SyntaxError):
            param["default"] = None
    return param


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, dict]:
    args = node.args
    defaults = args.defaults
    # ``defaults`` is right-aligned against the positional arguments.
    positional = [a.arg for a in args.args]
    default_by_name = dict(zip(positional[len(positional) - len(defaults):], defaults))
    params: dict[str, dict] = {}
    for arg in args.args:
        params[arg.arg] = _parameter(arg.arg, arg.annotation, default_by_name.get(arg.arg))
    for arg in args.kwonlyargs:
        params[arg.arg] = _parameter(arg.arg, arg.annotation, args.kw_defaults.get(arg.arg))
    return params


def collect_specs(api_dir: Path) -> list[dict]:
    """One spec per ``@frappe.whitelist``-decorated function under ``api_dir``."""
    specs: list[dict] = []
    for path in sorted(api_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", None) == "whitelist"):
                    continue
                specs.append(
                    {
                        "name": f"asoud_erp.api.v1.{path.stem}.{node.name}",
                        "http": _http_methods(decorator),
                        "allow_guest": _allow_guest(decorator),
                        "description": _first_docstring_line(node),
                        "parameters": _parameters(node),
                    }
                )
    return specs


def build_manifest(specs: list[dict]) -> dict:
    """Classify the specs and return the manifest, excluding guest and protocol methods."""
    methods: dict[str, dict] = {}
    for spec in specs:
        name = spec["name"]
        if spec["allow_guest"] or name in _PROTOCOL_METHODS:
            continue
        methods[name] = {
            "name": name,
            "kind": registry.classify(name),
            "effectful": registry.is_impactful(name),
            "pilot": name in PILOT_METHODS,
            "http": spec["http"],
            "description": spec["description"],
            "parameters": spec["parameters"],
        }
    return {
        "api_version": "v1",
        "generated_by": _GENERATED_BY,
        "method_count": len(methods),
        "methods": {name: methods[name] for name in sorted(methods)},
    }


def build_from_dir(api_dir: Path) -> dict:
    return build_manifest(collect_specs(api_dir))


def manifest_to_json(manifest: dict) -> str:
    """Canonical serialization: sorted keys, Persian kept readable, one trailing newline."""
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
