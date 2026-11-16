"""Pure regression: input validation for the batch instance-summary endpoint (PA-032).

``parse_instance_names`` accepts a list (or a JSON string of a list), de-duplicates,
and caps at 100 names. Anything else is a Persian ``ValueError``.
"""

import json

import pytest

from asoud_erp.services.workflow_instance_summaries import parse_instance_names


def test_accepts_a_list_and_deduplicates():
    assert parse_instance_names(["WFI-1", "WFI-2", "WFI-1"]) == ["WFI-1", "WFI-2"]


def test_accepts_a_json_string():
    assert parse_instance_names(json.dumps(["WFI-1", "WFI-2"])) == ["WFI-1", "WFI-2"]


def test_strips_whitespace():
    assert parse_instance_names([" WFI-1 ", "WFI-2"]) == ["WFI-1", "WFI-2"]


def test_rejects_non_list():
    with pytest.raises(ValueError):
        parse_instance_names("WFI-1")  # a bare string is not a list of names
    with pytest.raises(ValueError):
        parse_instance_names(None)


def test_rejects_bad_json_string():
    with pytest.raises(ValueError):
        parse_instance_names("{not json")


def test_rejects_empty_or_non_string_names():
    with pytest.raises(ValueError):
        parse_instance_names(["WFI-1", ""])
    with pytest.raises(ValueError):
        parse_instance_names(["WFI-1", 123])


def test_rejects_more_than_100_names():
    with pytest.raises(ValueError):
        parse_instance_names([f"WFI-{i}" for i in range(101)])


def test_allows_exactly_100_names():
    names = [f"WFI-{i}" for i in range(100)]
    assert parse_instance_names(names) == names
