"""Translate Persian and Arabic-Indic numerals to ASCII at a storage boundary.

Identifier and number columns (national codes, economic codes, registration and
postal codes, phone numbers, account/card numbers, IBANs, fiscal years, code digit
counts) must hold ASCII digits so ERPNext validators, search and integrations keep
working when a user types Persian (۰-۹) or Arabic-Indic (٠-٩) numerals. Free text is
never routed through here, but text columns that legitimately mix letters and digits
(such as an IBAN) still get their digits translated; only the Persian decimal «٫»
and thousands «٬» separators are translated when the whole value is number-like.
"""

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ASCII_DIGITS = "0123456789"

_DIGIT_TRANSLATION = str.maketrans(
    PERSIAN_DIGITS + ARABIC_INDIC_DIGITS, ASCII_DIGITS + ASCII_DIGITS
)
_SEPARATOR_TRANSLATION = str.maketrans({"٫": ".", "٬": ""})
_NUMBER_CHARACTERS = frozenset(ASCII_DIGITS + ".,٫٬")


def _is_number_like(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and all(character in _NUMBER_CHARACTERS for character in stripped)


def to_ascii_digits(value):
    """Return ``value`` with Persian/Arabic-Indic digits as ASCII digits.

    ``None`` and non-strings pass through unchanged. The Persian decimal and
    thousands separators are translated only when the value is made of digits and
    separators, so prose that happens to contain a digit is left otherwise intact.
    """
    if not isinstance(value, str):
        return value
    translated = value.translate(_DIGIT_TRANSLATION)
    if _is_number_like(translated):
        translated = translated.translate(_SEPARATOR_TRANSLATION)
    return translated


def normalize_numeric_text(value):
    """Strip ``value`` and translate its digits, returning ``None`` when empty.

    ``None`` stays ``None`` and non-strings pass through, so the helper is safe on
    optional API arguments before they are written to a numeric column.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    normalized = to_ascii_digits(value.strip())
    return normalized or None


def normalize_column_rows(rows, field):
    """Pure per-row logic of the digit migration patch.

    ``rows`` is an iterable of mappings with a ``name`` and a ``field`` value.
    Returns ``(name, normalized)`` pairs only for rows whose value actually
    changes, so a repeated run of the patch writes nothing.
    """
    updates = []
    for row in rows:
        value = row.get(field)
        if not isinstance(value, str):
            continue
        normalized = to_ascii_digits(value)
        if normalized != value:
            updates.append((row.get("name"), normalized))
    return updates
