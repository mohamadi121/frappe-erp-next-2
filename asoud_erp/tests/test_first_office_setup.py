import pytest

from asoud_erp.services.first_office_setup import (
    INTERNAL_SUFFIX,
    internal_email,
    validate_lead_inputs,
)


def test_internal_email_detection():
    assert internal_email(f"test{INTERNAL_SUFFIX}") is True
    assert internal_email(f"User Name <abc123{INTERNAL_SUFFIX}>") is True
    assert internal_email("test@example.com") is False
    assert internal_email("test@users.asoud.invalid.org") is False
    assert internal_email("") is False
    assert internal_email(None) is False


def test_validate_lead_inputs_success_with_mobile():
    name, username, mail, mobile = validate_lead_inputs(
        "علی رضایی", "ali_rezaei", "09123456789", "SecurePassword123"
    )
    assert name == "علی رضایی"
    assert username == "ali_rezaei"
    assert mail is None
    assert mobile == "09123456789"


def test_validate_lead_inputs_success_with_email():
    name, username, mail, mobile = validate_lead_inputs(
        "سارا محمدی", "sara_m", "sara@example.com", "SecurePassword123"
    )
    assert name == "سارا محمدی"
    assert username == "sara_m"
    assert mail == "sara@example.com"
    assert mobile is None


def test_validate_lead_inputs_rejects_invalid_username():
    with pytest.raises(ValueError, match="نام کاربری"):
        validate_lead_inputs("علی", "admin", "09123456789", "SecurePass123")

    with pytest.raises(ValueError, match="نام کاربری"):
        validate_lead_inputs("علی", "12username", "09123456789", "SecurePass123")

    with pytest.raises(ValueError, match="نام کاربری"):
        validate_lead_inputs("علی", "ab", "09123456789", "SecurePass123")


def test_validate_lead_inputs_rejects_invalid_password():
    with pytest.raises(ValueError, match="رمز موقت"):
        validate_lead_inputs("علی", "ali_user", "09123456789", "short")


def test_validate_lead_inputs_rejects_internal_email_contact():
    with pytest.raises(ValueError, match="ایمیل تماس واقعی"):
        validate_lead_inputs(
            "علی", "ali_user", f"fake{INTERNAL_SUFFIX}", "SecurePass123"
        )
