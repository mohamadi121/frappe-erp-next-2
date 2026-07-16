import pytest

from asoud_erp.services.setup_service import (
    normalize_digits,
    normalize_enabled_roles,
    unique_abbreviation,
    validate_economic_code,
)


def test_normalize_persian_digits():
    assert normalize_digits("۱۲۳-۴۵") == "12345"


def test_economic_code_validation():
    assert validate_economic_code("۱۲۳۴۵۶۷۸۹۰") == "1234567890"
    with pytest.raises(ValueError):
        validate_economic_code("1111111111")


def test_unique_abbreviation_handles_collisions():
    assert unique_abbreviation("ASOUD ERP", lambda value: value in {"AE", "AE2"}) == "AE3"


def test_system_manager_is_always_an_enabled_business_role():
    assert normalize_enabled_roles(["Accounts Manager"]) == ["System Manager", "Accounts Manager"]


def test_unknown_enabled_role_is_rejected():
    with pytest.raises(ValueError):
        normalize_enabled_roles(["Administrator"])
