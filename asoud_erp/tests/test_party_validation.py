from asoud_erp.services.party_validation import (
    is_valid_iranian_legal_id,
    is_valid_iranian_mobile,
    is_valid_iranian_national_code,
    normalize_optional,
)


def test_optional_values_are_normalized() -> None:
    assert normalize_optional("   ") is None
    assert normalize_optional(" 09121234567 ") == "09121234567"


def test_individual_national_code_checksum() -> None:
    assert is_valid_iranian_national_code("0013542435")
    assert not is_valid_iranian_national_code("1111111111")
    assert not is_valid_iranian_national_code("0013542438")


def test_legal_id_and_mobile_shapes() -> None:
    assert is_valid_iranian_legal_id("14001234567")
    assert not is_valid_iranian_legal_id("11111111111")
    assert is_valid_iranian_mobile("09121234567")
    assert is_valid_iranian_mobile("+989121234567")
    assert not is_valid_iranian_mobile("02112345678")
