import json

import pytest

from asoud_erp.services import token_codes
from asoud_erp.services.security_audit import build_row, redact


def test_redact_removes_secrets_at_any_depth():
    cleaned = redact({"user": "a", "password": "x", "nested": {"api_key": "k", "Authorization": "t", "ok": 1},
                      "list": [{"token": "z", "name": "n"}], "new_password": "p", "sid": "s"})
    flat = json.dumps(cleaned, ensure_ascii=False)
    for secret in ('"x"', '"k"', '"t"', '"z"', '"p"', '"s"'):
        assert secret not in flat
    assert cleaned["user"] == "a" and cleaned["nested"]["ok"] == 1 and cleaned["list"][0]["name"] == "n"


def test_redact_bounds_size():
    assert len(redact("x" * 5000)) <= 501
    assert len(redact({str(i): i for i in range(500)})) == 50


def test_build_row_has_actor_action_time_source_result():
    row = build_row(actor="a@x", action="auth.login", result="failure", source="1.2.3.4", target="a@x",
                    details={"password": "secret", "reason": "bad"}, occurred_on="2026-01-01 00:00:00")
    assert row["actor"] == "a@x" and row["action"] == "auth.login" and row["result"] == "failure"
    assert row["source"] == "1.2.3.4" and row["occurred_on"] == "2026-01-01 00:00:00"
    assert "secret" not in row["details"] and "bad" in row["details"]
    with pytest.raises(ValueError):
        build_row(actor="a", action="x", result="maybe")


def test_codes_are_unambiguous_random_and_hashed():
    code = token_codes.new_code()
    assert len(code) == token_codes.CODE_LENGTH and set(code) <= set(token_codes.ALPHABET)
    assert token_codes.new_code() != code
    salt = token_codes.new_salt()
    digest = token_codes.hash_code(code, salt)
    assert code not in digest
    assert token_codes.matches(code.lower(), salt, digest)  # user may type lower case
    assert token_codes.matches(" " + code[:5] + "-" + code[5:] + " ", salt, digest)
    assert not token_codes.matches("WRONGCODE1", salt, digest)
    assert not token_codes.matches(code, token_codes.new_salt(), digest)


def test_token_usable_rules():
    assert token_codes.usable(consumed=None, expired=False, attempts=0)
    assert not token_codes.usable(consumed="x", expired=False, attempts=0)
    assert not token_codes.usable(consumed=None, expired=True, attempts=0)
    assert not token_codes.usable(consumed=None, expired=False, attempts=token_codes.MAX_ATTEMPTS)
