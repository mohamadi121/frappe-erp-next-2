import pytest

from asoud_erp.services import office_validation as rules


@pytest.mark.parametrize('value', ['09123456789', '۰۹۱۲۳۴۵۶۷۸۹'])
def test_mobile_normalizes_exactly_eleven_digits(value):
    assert rules.mobile(value) == '09123456789'


@pytest.mark.parametrize('value', ['9123456789', '091234567890', '02112345678', '09abcdefghi'])
def test_mobile_rejects_wrong_length_prefix_and_text(value):
    with pytest.raises(ValueError):
        rules.mobile(value)


@pytest.mark.parametrize('value', ['02112345678', '۰۲۱۱۲۳۴۵۶۷۸'])
def test_landline_normalizes_eleven_digits(value):
    assert rules.landline(value) == '02112345678'


@pytest.mark.parametrize('value', ['2112345678', '021123456789', '0211234567', '0abcdefghij'])
def test_landline_rejects_bad_format(value):
    with pytest.raises(ValueError):
        rules.landline(value)


@pytest.mark.parametrize('legal,length', [(False, 10), (True, 11)])
def test_identity_length_never_bypasses_checksum(legal, length):
    for code in ('1' * (length + 1), '1' * (length - 1), '1' * length):
        with pytest.raises(ValueError):
            rules.identity(code, legal=legal)
