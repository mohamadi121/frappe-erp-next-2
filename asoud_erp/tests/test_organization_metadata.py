import pytest

from asoud_erp.services.organization_metadata import description_value


def test_description_optional_text_and_boundaries():
    assert description_value(None) == ""
    assert description_value("") == ""
    assert description_value("  توضیحات واحد\n  ") == "توضیحات واحد"
    assert description_value("آ" * 2000) == "آ" * 2000


@pytest.mark.parametrize("value", [1, {}, [], True, "آ" * 2001])
def test_invalid_description_is_rejected(value):
    with pytest.raises(ValueError):
        description_value(value)
