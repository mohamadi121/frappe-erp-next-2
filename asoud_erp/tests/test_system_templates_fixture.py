"""The server's template field lists must equal the shared contract fixture (CONTRACT 7, 8.2)."""

import json
from pathlib import Path

import pytest

from asoud_erp.services.request_templates import form_fields

FIXTURE = Path(__file__).parent / "fixtures" / "system_templates.json"


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", ["purchase", "supply", "leave"])
def test_server_fields_equal_the_fixture(fixture, key):
    assert form_fields.FIELDS_BY_KEY[key] == fixture[key]


def test_fixture_has_exactly_the_three_templates(fixture):
    assert sorted(fixture) == ["leave", "purchase", "supply"]
    assert [len(fixture[key]) for key in ("purchase", "supply", "leave")] == [10, 11, 14]


def test_field_keys_are_unique_and_within_the_engine_cap(fixture):
    for key, fields in fixture.items():
        keys = [field["key"] for field in fields]
        assert len(keys) == len(set(keys)), key
        assert len(keys) <= 30, key


def test_visible_when_points_at_an_earlier_field(fixture):
    for fields in fixture.values():
        seen = set()
        for field in fields:
            rule = field.get("visible_when")
            if rule:
                assert rule["field"] in seen
            seen.add(field["key"])


def test_attachment_extension_lists():
    assert form_fields.ATTACHMENT_EXTENSIONS == ["pdf", "jpg", "jpeg", "png", "xls", "xlsx", "doc", "docx"]
    assert form_fields.LEAVE_ATTACHMENT_EXTENSIONS == ["jpg", "jpeg", "png", "pdf", "docx"]


def test_registered_specs_carry_the_fixture_fields_and_contract_metadata(fixture):
    from asoud_erp.services.request_templates import base

    specs = {spec.key: spec for spec in base.all_specs()}
    assert list(specs) == ["purchase", "supply", "leave"]
    meta = {
        "purchase": ("PR", "Purchase", "Purchase", "input"),
        "supply": ("SP", "Purchase", "Inventory", "input"),
        "leave": ("LV", "HR", "HR", "generated"),
    }
    for key, spec in specs.items():
        assert spec.form_fields == fixture[key]
        assert (spec.number_prefix, spec.category, spec.module_key, spec.subject_mode) == meta[key]
        assert spec.version == 1
        assert spec.approval == {"assignment_type": "Direct Manager"}
        assert spec.attachments["max_files"] == 10 and spec.attachments["max_mb"] == 10
    assert specs["purchase"].attachments["extensions"] == specs["supply"].attachments["extensions"]
    assert specs["leave"].attachments["extensions"] == ["jpg", "jpeg", "png", "pdf", "docx"]
    assert specs["leave"].build_subject is not None
    assert specs["purchase"].build_subject is None and specs["supply"].build_subject is None


def test_denormalize_follows_the_contract():
    from asoud_erp.services.request_templates import base

    specs = {spec.key: spec for spec in base.all_specs()}
    purchase = {"priority": "High", "needed_date": "2026-10-20", "project": "P-1", "org_unit": "ICU - WP"}
    assert specs["purchase"].denormalize(purchase) == {
        "priority": "High", "required_by": "2026-10-20", "project": "P-1", "department": "ICU - WP"}
    assert specs["supply"].denormalize({**purchase, "priority": None}) == {
        "priority": "Normal", "required_by": "2026-10-20", "project": "", "department": "ICU - WP"}
    daily = {"request_kind": "Daily", "start_date": "2026-10-10", "end_date": "2026-10-12", "org_unit": "D"}
    hourly = {"request_kind": "Hourly", "leave_date": "2026-10-11", "org_unit": "D"}
    assert specs["leave"].denormalize(daily) == {
        "priority": "Normal", "required_by": "2026-10-10", "project": "", "department": "D"}
    assert specs["leave"].denormalize(hourly)["required_by"] == "2026-10-11"
