import pytest

from asoud_erp.services.hr_contract import normalize_communication_payload, normalize_report_payload


def test_report_requires_and_normalizes_activities():
    result = normalize_report_payload({"activities": [{"title": " تحلیل ", "duration_minutes": 70, "progress": 120}]})
    assert result["activities"][0]["title"] == "تحلیل"
    assert result["activities"][0]["progress"] == 100


def test_empty_report_is_rejected():
    with pytest.raises(ValueError):
        normalize_report_payload({"activities": []})


def test_communication_requires_recipient_and_deduplicates():
    result = normalize_communication_payload({"subject": "نامه", "content": "متن", "recipients": ["a@test.ir", "a@test.ir"]})
    assert result["recipients"] == ["a@test.ir"]

