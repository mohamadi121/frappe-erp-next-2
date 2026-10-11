import re

from asoud_erp.services.digits import normalize_numeric_text, to_ascii_digits


def normalize_optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def normalize_numeric(value: str | None) -> str | None:
    """Normalise a numeric identifier column: strip, ASCII digits, None when empty."""
    return normalize_numeric_text(value)


def is_valid_iranian_national_code(value: str) -> bool:
    code = re.sub(r"\D", "", to_ascii_digits(value))
    if len(code) != 10 or len(set(code)) == 1:
        return False
    checksum = sum(int(code[index]) * (10 - index) for index in range(9)) % 11
    expected = checksum if checksum < 2 else 11 - checksum
    return int(code[-1]) == expected


def is_valid_iranian_legal_id(value: str) -> bool:
    normalized = to_ascii_digits(value)
    return bool(re.fullmatch(r"\d{11}", normalized)) and len(set(normalized)) > 1


def is_valid_iranian_mobile(value: str) -> bool:
    normalized = to_ascii_digits(value).replace(" ", "").replace("-", "")
    return bool(re.fullmatch(r"(?:\+98|0098|0)?9\d{9}", normalized))
