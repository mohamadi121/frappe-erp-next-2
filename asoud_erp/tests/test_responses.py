from asoud_erp.api.v1.responses import failure, success


def test_success_contract():
    response = success({"name": "test"})
    assert response["ok"] is True
    assert response["meta"]["api_version"] == "v1"


def test_failure_contract():
    response = failure("VALIDATION_ERROR", "invalid")
    assert response["ok"] is False
    assert response["error"]["code"] == "VALIDATION_ERROR"

