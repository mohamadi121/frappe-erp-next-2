"""The single module vocabulary and the legacy-key read path (PA-054)."""

import pytest

from asoud_erp.services.modules import (
    LEGACY_MODULE_KEYS,
    MODULE_DOCTYPES,
    MODULE_KEYS,
    normalize_module_key,
)
from asoud_erp.services.workflow_contract import serialize_workflow


def test_canonical_module_keys_are_the_template_set() -> None:
    assert MODULE_KEYS == ("Finance", "Purchase", "Selling", "Stock", "HR", "Admin", "IT")


@pytest.mark.parametrize(
    "legacy, canonical",
    [
        ("Accounting", "Finance"),
        ("Sales", "Selling"),
        ("Inventory", "Stock"),
        ("Support", "Admin"),
    ],
)
def test_legacy_keys_map_to_canonical(legacy, canonical) -> None:
    assert LEGACY_MODULE_KEYS[legacy] == canonical
    assert normalize_module_key(legacy) == canonical


@pytest.mark.parametrize("key", MODULE_KEYS)
def test_canonical_keys_pass_through(key) -> None:
    assert normalize_module_key(key) == key


def test_unknown_key_is_none() -> None:
    assert normalize_module_key("Nope") is None
    assert normalize_module_key(None) is None


def test_saved_workflow_with_a_legacy_module_key_still_loads() -> None:
    # A definition written before the vocabulary was unified stores "Accounting";
    # the app must see the canonical "Finance".
    result = serialize_workflow(
        {
            "readiness_status": "Ready",
            "missing_requirements_json": "[]",
            "module_key": "Accounting",
        }
    )
    assert result["module_key"] == "Finance"


def test_canonical_module_key_is_unchanged_on_read() -> None:
    result = serialize_workflow(
        {
            "readiness_status": "Ready",
            "missing_requirements_json": "[]",
            "module_key": "Selling",
        }
    )
    assert result["module_key"] == "Selling"


# --- PA-050: the HR module targets the standard payroll/attendance documents ---

def test_hr_module_targets_the_standard_payroll_and_attendance_documents() -> None:
    hr = MODULE_DOCTYPES["HR"]
    for doctype in (
        "Leave Application",
        "Job Applicant",
        "Employee Advance",
        "Asset Movement",
        "Shift Request",
        "Salary Slip",
        "Attendance",
    ):
        assert doctype in hr


def test_every_module_targets_at_least_one_document() -> None:
    for key, doctypes in MODULE_DOCTYPES.items():
        assert doctypes, f"module {key} has no target documents"
