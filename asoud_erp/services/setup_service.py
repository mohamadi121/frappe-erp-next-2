import re

ALLOWED_OFFICE_TYPES = {"Personal", "Legal"}
ALLOWED_DISPLAY_CURRENCIES = {"Rial", "Toman"}
ALLOWED_CHART_TEMPLATES = {"Iran Standard", "Service", "Commercial", "Manufacturing"}
ALLOWED_ENABLED_ROLES = {
    "System Manager",
    "Accounts Manager",
    "Accounts User",
    "Stock User",
    "Sales User",
}


def normalize_digits(value: str | None) -> str:
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return re.sub(r"\D", "", str(value or "").translate(translation))


def validate_economic_code(value: str | None) -> str | None:
    normalized = normalize_digits(value)
    if not normalized:
        return None
    if not 10 <= len(normalized) <= 14 or len(set(normalized)) == 1:
        raise ValueError("Iranian economic code must contain 10 to 14 valid digits")
    return normalized


def abbreviation_seed(title: str) -> str:
    latin_words = re.findall(r"[A-Za-z0-9]+", title.upper())
    if latin_words:
        value = "".join(word[0] for word in latin_words[:5])
    else:
        value = "ASD"
    return (value or "ASD")[:5]


def unique_abbreviation(title: str, exists) -> str:
    seed = abbreviation_seed(title)
    if not exists(seed):
        return seed
    for number in range(2, 10000):
        suffix = str(number)
        candidate = f"{seed[: max(1, 5 - len(suffix))]}{suffix}"
        if not exists(candidate):
            return candidate
    raise ValueError("A unique company abbreviation could not be generated")


def normalize_enabled_roles(roles: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(str(role).strip() for role in roles if str(role).strip()))
    if set(normalized) - ALLOWED_ENABLED_ROLES:
        raise ValueError("One or more initial roles are not valid")
    if "System Manager" not in normalized:
        normalized.insert(0, "System Manager")
    return normalized
