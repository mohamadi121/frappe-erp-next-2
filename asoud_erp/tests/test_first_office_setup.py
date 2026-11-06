import pytest

from asoud_erp.services.first_office_setup import (
    INTERNAL_SUFFIX,
    format_password_policy_error,
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


@pytest.mark.parametrize("username", [None, "", "ab", "1ali", "ali-x", "نام", "a" * 41])
def test_username_format_has_field_specific_error(username):
    with pytest.raises(ValueError, match="نام کاربری"):
        validate_lead_inputs("علی", username, "09123456789", "SecurePass123")


@pytest.mark.parametrize("contact", [None, "", "   "])
def test_missing_contact_has_field_specific_error(contact):
    with pytest.raises(ValueError, match="شماره موبایل یا ایمیل"):
        validate_lead_inputs("علی", "ali_user", contact, "SecurePass123")


@pytest.mark.parametrize("password", [None, "", "short", "aaaaaaaa", "12345678"])
def test_weak_password_has_field_specific_error(password):
    with pytest.raises(ValueError, match="رمز موقت"):
        validate_lead_inputs("علی", "ali_user", "09123456789", password)


def test_format_password_policy_error_fallback_on_empty():
    assert format_password_policy_error(None) == "رمز موقت ضعیف است؛ رمز قوی‌تری با حروف و نویسه‌های متنوع انتخاب کنید."
    assert format_password_policy_error({}) == "رمز موقت ضعیف است؛ رمز قوی‌تری با حروف و نویسه‌های متنوع انتخاب کنید."
    assert format_password_policy_error({"warning": "", "suggestions": []}) == "رمز موقت ضعیف است؛ رمز قوی‌تری با حروف و نویسه‌های متنوع انتخاب کنید."


def test_format_password_policy_error_translates_warning():
    msg = format_password_policy_error({"warning": "This is similar to a commonly used password.", "suggestions": []})
    assert msg.startswith("رمز موقت ضعیف است؛ ")
    assert "این رمز شبیه یکی از رمزهای پرکاربرد است." in msg


def test_format_password_policy_error_translates_warning_and_suggestions():
    feedback = {
        "warning": "This is similar to a commonly used password.",
        "suggestions": [
            "Add another word or two. Uncommon words are better.",
            "Predictable substitutions like '@' instead of 'a' don't help very much.",
        ],
    }
    msg = format_password_policy_error(feedback)
    assert msg.startswith("رمز موقت ضعیف است؛ ")
    assert "این رمز شبیه یکی از رمزهای پرکاربرد است." in msg
    assert "پیشنهاد:" in msg
    assert "یک یا دو کلمه دیگر اضافه کنید" in msg
    assert "جایگزینی‌های قابل پیش‌بینی" in msg


def test_format_password_policy_error_common_patterns():
    top10 = format_password_policy_error({"warning": "This is a top-10 common password.", "suggestions": []})
    assert "۱۰ رمز عبور بسیار رایج و ناامن است" in top10

    seq = format_password_policy_error({"warning": 'Sequences like "abc" or "6543" are easy to guess.', "suggestions": ["Avoid sequences."]})
    assert "توالی حروف یا اعداد" in seq
    assert "از دنباله‌ها و توالی حروف یا اعداد بپرهیزید" in seq

    recent_year = format_password_policy_error({"warning": "Recent years are easy to guess.", "suggestions": ["Avoid recent years."]})
    assert "استفاده از سال‌های اخیر" in recent_year
    assert "از سال‌های اخیر بپرهیزید" in recent_year


def test_format_password_policy_error_unmapped_text_stays_in_persian():
    msg = format_password_policy_error({"warning": "Unknown custom zxcvbn warning", "suggestions": ["Some unmapped suggestion"]})
    assert msg.startswith("رمز موقت ضعیف است؛ ")
    assert "Unknown custom zxcvbn warning" not in msg
    assert "Some unmapped suggestion" not in msg
    assert "به‌راحتی قابل حدس است" in msg

