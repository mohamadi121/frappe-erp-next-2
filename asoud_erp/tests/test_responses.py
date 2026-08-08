from asoud_erp.api.v1.responses import failure, success


def test_success_contract():
    response = success({"name": "test"})
    assert response["ok"] is True
    assert response["meta"]["api_version"] == "v1"
    assert response["data"] == {"name": "test"}


def test_failure_contract():
    response = failure("VALIDATION_ERROR", "invalid")
    assert response["ok"] is False
    assert response["error"]["code"] == "VALIDATION_ERROR"
    assert response["error"]["message"] == "invalid"
    assert response["meta"]["api_version"] == "v1"


def test_success_accepts_empty_payload():
    response = success()
    assert response == {"ok": True, "data": None, "meta": {"api_version": "v1"}}


def test_success_merges_metadata():
    response = success([], meta={"created_count": 2})
    assert response["meta"] == {"api_version": "v1", "created_count": 2}
