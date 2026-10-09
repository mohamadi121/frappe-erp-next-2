from datetime import date

import pytest

from asoud_erp.services.request_templates.base import (
    NUMBER_PREFIXES,
    number_pattern,
    number_prefix,
    series_key,
)


def test_series_key_uses_the_jalali_year():
    assert series_key("PR", date(2026, 10, 6)) == "PR-1405-"
    assert series_key("SP", date(2026, 10, 6)) == "SP-1405-"
    assert series_key("LV", date(2026, 10, 6)) == "LV-1405-"


def test_series_rolls_over_at_nowruz():
    assert series_key("PR", date(2026, 3, 20)) == "PR-1404-"
    assert series_key("PR", date(2026, 3, 21)) == "PR-1405-"
    assert series_key("LV", date(2027, 3, 20)) == "LV-1405-"
    assert series_key("LV", date(2027, 3, 21)) == "LV-1406-"


def test_custom_request_types_keep_the_legacy_series():
    assert series_key(None) == "REQ-"
    assert series_key("") == "REQ-"
    assert number_pattern(None) == "REQ-.#####"


@pytest.mark.parametrize("prefix", ["PR", "SP", "LV"])
def test_pattern_has_four_digits(prefix):
    assert number_pattern(prefix, date(2026, 10, 6)) == f"{prefix}-1405-.####"


def test_known_templates_have_a_prefix_without_their_spec_module():
    assert NUMBER_PREFIXES == {"purchase": "PR", "supply": "SP", "leave": "LV"}
    assert number_prefix("leave") == "LV"
    assert number_prefix("") is None and number_prefix(None) is None
    assert number_prefix("custom-type") is None
