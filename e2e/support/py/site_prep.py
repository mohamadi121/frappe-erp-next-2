"""Site preparation for the Playwright end-to-end suite.

Run through the bench environment Python:

    ~/frappe-dev/bench/env/bin/python e2e/support/py/site_prep.py <action> [--key value]

Actions
-------
``status``    report the current site state as JSON (no writes)
``ensure``    create the E2E users' Employee records, the E2E second company and
              the E2E native Frappe Workflows (idempotent), then print the state
``activate``  link a native Frappe Workflow to an ASOUD Workflow Definition and
              mark it Ready so ``set_workflow_status`` can activate it
``cleanup``   delete the E2E Journal Entries / ASOUD Workflow Requests of a run

Only records whose name starts with ``E2E-`` are touched.
"""

import json
import os
import sys

BENCH = os.environ.get("E2E_BENCH_PATH", os.path.expanduser("~/frappe-dev/bench"))
SITE = os.environ.get("E2E_SITE", "asoud.test")
PREFIX = "E2E-"

os.chdir(os.path.join(BENCH, "sites"))
for app in ("frappe", "erpnext", "hrms"):
    sys.path.insert(0, os.path.join(BENCH, "apps", app))

import frappe  # noqa: E402

E2E_USERS = {
    "e2e.admin@example.com": {"first_name": "E2E Admin", "roles": ["System Manager"]},
    "e2e.accounts@example.com": {"first_name": "E2E Accounts", "roles": ["Accounts Manager"]},
    "e2e.outsider@example.com": {"first_name": "E2E Outsider", "roles": ["Employee"]},
    "asoud.employee@example.com": {"first_name": "E2E Employee", "roles": []},
    "asoud.approver@example.com": {"first_name": "E2E Approver", "roles": []},
    "asoud.accountant@example.com": {"first_name": "E2E Accountant", "roles": []},
}
SECOND_COMPANY = "E2E Second Company"


def connect() -> None:
    frappe.init(site=SITE, sites_path=os.path.join(BENCH, "sites"))
    frappe.connect()
    frappe.set_user("Administrator")


def company() -> str:
    return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", pluck="name", limit=1
    )[0]


def abbr() -> str:
    return frappe.get_cached_value("Company", company(), "abbr")


def fixture_records() -> dict:
    """The shared integration fixture users and their Employee records."""
    from asoud_erp.integration_tests.fixtures import setup_records

    return setup_records()


def ensure_user_roles(user: str, roles: list[str]) -> None:
    doc = frappe.get_doc("User", user)
    missing = [role for role in roles if role not in [row.role for row in doc.roles]]
    for role in missing:
        doc.append("roles", {"role": role})
    if missing:
        doc.save(ignore_permissions=True)


def ensure_employee(user: str, first_name: str, reports_to: str = "", company_name: str = "") -> str:
    existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "Employee",
            "first_name": first_name,
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
            "company": company_name or company(),
            "status": "Active",
            "user_id": user,
            "create_user_permission": 0,
            **({"reports_to": reports_to} if reports_to else {}),
        }
    ).insert(ignore_permissions=True).name


def ensure_second_company() -> str:
    if frappe.db.exists("Company", SECOND_COMPANY):
        return SECOND_COMPANY
    abbr_value = SECOND_COMPANY.split(" ")[0][:4].upper()
    frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": SECOND_COMPANY,
            "abbr": abbr_value,
            "default_currency": "IRR",
            "country": "Iran",
        }
    ).insert(ignore_permissions=True)
    return SECOND_COMPANY


def ensure_native_workflow(title: str, document_type: str) -> str:
    """A minimal Frappe Workflow so an ASOUD definition can be activated.

    The native Workflow is the one thing no asoud_erp endpoint exposes, and
    activating a definition requires it.
    """
    existing = frappe.db.get_value("Workflow", {"workflow_name": title}, "name")
    if existing:
        return existing
    states = []
    for state in ("Pending Review", "E2E Final"):
        state_name = f"{PREFIX}{state} {document_type}"
        if not frappe.db.exists("Workflow State", state_name):
            frappe.get_doc(
                {"doctype": "Workflow State", "workflow_state_name": state_name}
            ).insert(ignore_permissions=True)
        states.append(
            {"state": state_name, "doc_status": "0", "allow_edit": "System Manager"}
        )
    return frappe.get_doc(
        {
            "doctype": "Workflow",
            "workflow_name": title,
            "document_type": document_type,
            "is_active": 0,
            "states": states,
        }
    ).insert(ignore_permissions=True).name


def native_workflow_for(definition: str) -> str:
    return ensure_native_workflow(
        f"{PREFIX}Native {definition}", "ASOUD Workflow Request"
    )


def drop_definition(definition: str) -> dict:
    """Remove a half-designed E2E definition so global setup can redesign it.

    Only an ``E2E-`` titled definition with no request instances is removed.
    """
    title = frappe.db.get_value("ASOUD Workflow Definition", definition, "workflow_title") or ""
    if not title.startswith(PREFIX):
        raise SystemExit(f"refusing to drop {definition}: title {title!r} is not {PREFIX}")
    used = frappe.db.count("ASOUD Workflow Request", {"workflow_definition": definition})
    if used:
        raise SystemExit(f"refusing to drop {definition}: {used} request(s) reference it")
    frappe.delete_doc("ASOUD Workflow Definition", definition, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"dropped": definition}


def state() -> dict:
    employees = frappe.get_all(
        "Employee",
        filters={"user_id": ["in", list(E2E_USERS)]},
        fields=["name", "employee_name", "user_id", "reports_to", "company", "status"],
        order_by="name asc",
        limit_page_length=0,
    )
    accounts = {}
    for account_type in ("Cash", "Payable", "Equity", "Expense", "Fixed Asset"):
        names = frappe.get_all(
            "Account",
            filters={"company": company(), "is_group": 0, "account_type": account_type},
            fields=["name"],
            order_by="name asc",
            limit_page_length=0,
        )
        if names:
            accounts[account_type] = [row["name"] for row in names]
    return {
        "site": SITE,
        "company": company(),
        "abbr": abbr(),
        "second_company": SECOND_COMPANY if frappe.db.exists("Company", SECOND_COMPANY) else "",
        "employees": employees,
        "accounts": accounts,
        "definitions": frappe.get_all(
            "ASOUD Workflow Definition",
            filters=[["workflow_title", "like", f"%{PREFIX}%"]],
            fields=["name", "workflow_title", "status", "readiness_status", "frappe_workflow", "company"],
            order_by="creation asc",
            limit_page_length=0,
        ),
        "templates": frappe.get_all(
            "ASOUD Document Template",
            filters=[["template_title", "like", f"%{PREFIX}%"]],
            fields=["name", "template_title", "status", "document_type", "company"],
            order_by="creation asc",
            limit_page_length=0,
        ),
    }


def ensure() -> dict:
    records = fixture_records()
    approver = frappe.db.get_value("Employee", {"user_id": "asoud.approver@example.com"}, "name")
    ensure_user_roles("e2e.admin@example.com", ["System Manager"])
    ensure_user_roles("e2e.accounts@example.com", ["Accounts Manager"])
    ensure_user_roles("e2e.outsider@example.com", ["Employee"])
    ensure_employee("e2e.accounts@example.com", "E2E Accounts")
    ensure_employee("e2e.outsider@example.com", "E2E Outsider")
    ensure_second_company()
    frappe.db.commit()
    result = state()
    result["fixture_approver"] = approver
    result["fixture_employee"] = records.get("employee")
    return result


def activate(definition: str) -> dict:
    native = native_workflow_for(definition)
    frappe.db.set_value(
        "ASOUD Workflow Definition",
        definition,
        {
            "frappe_workflow": native,
            "readiness_status": "Ready",
            "missing_requirements_json": "[]",
        },
        update_modified=False,
    )
    frappe.db.commit()
    return {
        "definition": definition,
        "frappe_workflow": native,
        "status": frappe.db.get_value("ASOUD Workflow Definition", definition, "status"),
    }


def cleanup() -> dict:
    removed = []
    for doctype, filters in (
        ("ASOUD Workflow Request", {"name": ["like", f"{PREFIX}%"]}),
        ("ASOUD Document Template", {"name": ["like", f"{PREFIX}%"]}),
        ("ASOUD Workflow Definition", {"name": ["like", f"{PREFIX}%"]}),
        ("Journal Entry", {"name": ["like", f"{PREFIX}%"]}),
    ):
        for name in frappe.get_all(doctype, filters=filters, pluck="name", limit_page_length=0):
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
                removed.append(f"{doctype}:{name}")
    frappe.db.commit()
    return {"removed": removed}


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    options = dict(arg.split("=", 1) for arg in sys.argv[2:] if "=" in arg)
    connect()
    if action == "ensure":
        result = ensure()
    elif action == "status":
        result = state()
    elif action == "activate":
        result = activate(options["definition"])
    elif action == "drop-definition":
        result = drop_definition(options["definition"])
    elif action == "cleanup":
        result = cleanup()
    else:
        raise SystemExit(f"unknown action {action}")
    print("@@E2E_JSON@@" + json.dumps(result, default=str))


if __name__ == "__main__":
    main()