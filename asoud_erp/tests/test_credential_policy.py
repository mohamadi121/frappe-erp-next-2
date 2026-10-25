import pytest

from asoud_erp.services.credential_policy import (
    clean_name,
    normalize_email,
    normalize_mobile,
    normalize_national_id,
    password_errors,
    rate_limit_state,
)


@pytest.mark.parametrize("raw", ["09123456789", "۰۹۱۲۳۴۵۶۷۸۹", "+98 912 345 6789", "0098-912-345-6789",
                                 "9123456789", "٠٩١٢٣٤٥٦٧٨٩"])
def test_mobile_accepts_iranian_spellings_and_persian_digits(raw):
    assert normalize_mobile(raw) == "09123456789"


@pytest.mark.parametrize("raw", ["08123456789", "0912345678", "abc", "۰۹۱۲۳۴۵۶۷۸", "+1 202 555 0100"])
def test_mobile_rejects_other_values(raw):
    with pytest.raises(ValueError):
        normalize_mobile(raw)


def test_mobile_empty_is_none():
    assert normalize_mobile("") is None and normalize_mobile(None) is None


def test_national_id_checksum_and_persian_digits():
    assert normalize_national_id("0013542419") == "0013542419"
    assert normalize_national_id("۰۰۱۳۵۴۲۴۱۹") == "0013542419"
    assert normalize_national_id(None) is None and normalize_national_id("") is None
    for bad in ("0013542418", "1111111111", "123", "00135424190"):
        with pytest.raises(ValueError):
            normalize_national_id(bad)


def test_email_validation_and_lowercasing():
    assert normalize_email(" Admin@Example.COM ") == "admin@example.com"
    assert normalize_email("") is None
    for bad in ("admin", "a@b", "a b@c.com", "@c.com"):
        with pytest.raises(ValueError):
            normalize_email(bad)


def test_names_required_and_clean():
    assert clean_name("  علی   رضا ", "نام") == "علی رضا"
    for bad in ("", "   ", "a1", "<b>x</b>"):
        with pytest.raises(ValueError):
            clean_name(bad, "نام")


def test_password_policy_length_repeat_and_same_as_old():
    assert password_errors("Str0ng-Pass-Phrase!", "Str0ng-Pass-Phrase!", current="old-password-123") == []
    assert any("12" in e for e in password_errors("short1!", "short1!"))
    assert any("یکسان نیستند" in e for e in password_errors("Str0ng-Pass-Phrase!", "other"))
    assert any("رمز فعلی" in e for e in password_errors("Same-Password-123", "Same-Password-123",
                                                      current="Same-Password-123"))
    assert password_errors("a" * 129, "a" * 129)
    assert any("ساده" in e for e in password_errors("aaaaaaaaaaaaaa", "aaaaaaaaaaaaaa"))


def test_password_must_not_contain_username():
    errors = password_errors("hello-sara-secret-1", None, identifiers=("sara@example.com",))
    assert any("نام کاربری" in e for e in errors)


def test_rate_limit_window():
    now = 1000.0
    assert rate_limit_state([], now, 900, 5) == (False, 0)
    stamps = [now - 10 * i for i in range(5)]
    blocked, retry = rate_limit_state(stamps, now, 900, 5)
    assert blocked and 0 < retry <= 900
    assert rate_limit_state([now - 2000] * 9, now, 900, 5) == (False, 0)
