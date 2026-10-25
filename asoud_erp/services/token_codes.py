"""One-time code generation and verification (pure). Only a salted HMAC of the code is stored."""

import hashlib
import hmac
import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
CODE_LENGTH = 10
MAX_ATTEMPTS = 5


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def new_salt() -> str:
    return secrets.token_hex(16)


def normalize_code(value) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def hash_code(code: str, salt: str) -> str:
    return hmac.new(salt.encode(), normalize_code(code).encode(), hashlib.sha256).hexdigest()


def matches(code: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code, salt), expected_hash or "")


def usable(*, consumed, expired, attempts) -> bool:
    return not consumed and not expired and attempts < MAX_ATTEMPTS
