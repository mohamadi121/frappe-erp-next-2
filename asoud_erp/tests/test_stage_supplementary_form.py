import pytest

from asoud_erp.services import stage_supplementary_form as ssf


def test_read_binding_returns_dict_or_none():
    assert ssf.read_binding({"supplementary_form": {"form": "f", "revision": "r"}}) == {"form": "f", "revision": "r"}
    assert ssf.read_binding({"form_fields": []}) is None
    assert ssf.read_binding(None) is None
    # A non-dict binding is not a binding.
    assert ssf.read_binding({"supplementary_form": "f"}) is None


@pytest.mark.parametrize("binding", [
    {"form": "f"},                       # missing revision
    {"revision": "r"},                   # missing form
    {"form": "", "revision": "r"},       # empty form
    {"form": "f", "revision": ""},       # empty revision
    {"form": 1, "revision": "r"},        # wrong type
    {"form": "f", "revision": 2},        # wrong type
])
def test_validate_binding_shape_rejects_bad(binding):
    with pytest.raises(ValueError):
        ssf.validate_binding_shape(binding)


def test_validate_binding_shape_accepts_good():
    assert ssf.validate_binding_shape({"form": "f", "revision": "r", "title": "x"}) == {"form": "f", "revision": "r"}


def test_merge_and_strip_round_trip():
    merged = ssf.merge_supplementary({"a": 1}, {"form": "f", "revision": "r"}, {"x": "y"})
    assert merged["a"] == 1
    assert merged[ssf.RESERVED_KEY] == {"form": "f", "revision": "r", "values": {"x": "y"}}
    # The original response is not mutated.
    original = {"a": 1}
    ssf.merge_supplementary(original, {"form": "f", "revision": "r"}, {"x": "y"})
    assert original == {"a": 1}
    assert ssf.strip_supplementary(merged) == {"a": 1}


def test_supplementary_of_reads_stored_entry():
    stored = ssf.merge_supplementary({}, {"form": "f", "revision": "r"}, {"x": "y"})
    assert ssf.supplementary_of(stored) == {"form": "f", "revision": "r", "values": {"x": "y"}}
    assert ssf.supplementary_of({"a": 1}) is None
    assert ssf.supplementary_of({ssf.RESERVED_KEY: "not-a-dict"}) is None


def test_without_required_clears_top_level_and_columns():
    schema = {"sections": [{"fields": [
        {"key": "a", "required": True, "type": "Text"},
        {"key": "t", "type": "Table", "required": True,
         "columns": [{"key": "c", "required": True, "type": "Text"}]},
    ]}]}
    result = ssf.without_required(schema)
    assert result["sections"][0]["fields"][0]["required"] is False
    assert result["sections"][0]["fields"][1]["required"] is False
    assert result["sections"][0]["fields"][1]["columns"][0]["required"] is False
    # The input schema is not mutated.
    assert schema["sections"][0]["fields"][0]["required"] is True
    assert schema["sections"][0]["fields"][1]["columns"][0]["required"] is True
