import re
from decimal import Decimal, InvalidOperation

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
    # Reuse the existing legal-identity checksum; do not maintain two algorithms.
    from asoud_erp.services.office_validation import identity

    try:
        return bool(identity(value, legal=True))
    except ValueError:
        return False


def is_valid_iranian_mobile(value: str) -> bool:
    normalized = to_ascii_digits(value).replace(" ", "").replace("-", "")
    return bool(re.fullmatch(r"(?:\+98|0098|0)?9\d{9}", normalized))


def normalize_iban(value) -> str:
    return re.sub(r"\s", "", to_ascii_digits(str(value or ""))).upper()


def valid_iban(value) -> bool:
    code = normalize_iban(value)
    if not re.fullmatch(r"IR[0-9]{24}", code):
        return False
    # ISO 13616: move the country/check digits, then I=18, R=27.
    return int(code[4:] + "1827" + code[2:4]) % 97 == 1


def valid_card(value) -> bool:
    code = re.sub(r"[\s-]", "", to_ascii_digits(str(value or "")))
    if not re.fullmatch(r"[0-9]{16}", code) or len(set(code)) == 1:
        return False
    total = 0
    for index, character in enumerate(code):
        digit = int(character) * (2 if index % 2 == 0 else 1)
        total += digit - 9 if digit > 9 else digit
    return total % 10 == 0


def financial_amount(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("مبلغ معتبر نیست.")
    text = to_ascii_digits(str(value or "0")).replace(",", "").replace("٬", "").replace("٫", ".")
    try:
        amount = Decimal(text)
        if not amount.is_finite() or not Decimal(0) <= amount <= Decimal(10**15):
            raise ValueError("مبلغ باید بین صفر و حد مجاز سامانه باشد.")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("مبلغ حداکثر دو رقم اعشار دارد.")
        return amount
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("مبلغ معتبر نیست.") from exc
