"""Input parsing for the batch instance-summary endpoint (PA-032).

Pure logic: accepts a list (or a JSON string of a list) of instance names,
de-duplicates it, and caps it so a single cartable load cannot request an
unbounded number of instances.
"""
import json

MAX_INSTANCE_NAMES = 100


def parse_instance_names(names):
    """Return a de-duplicated list of instance names (order preserved).

    ``names`` may be a list or a JSON string of a list. Raises ``ValueError`` with a
    Persian message when the input is not a list of non-empty names or exceeds
    ``MAX_INSTANCE_NAMES``.
    """
    if isinstance(names, str):
        try:
            names = json.loads(names)
        except (TypeError, ValueError):
            raise ValueError("شناسه‌های نمونه باید یک فهرست باشد.")
    if not isinstance(names, list):
        raise ValueError("شناسه‌های نمونه باید یک فهرست باشد.")
    cleaned = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("شناسه‌های نمونه معتبر نیست.")
        cleaned.append(name.strip())
    if len(cleaned) > MAX_INSTANCE_NAMES:
        raise ValueError("حداکثر ۱۰۰ شناسهٔ نمونه می‌تواند در یک درخواست ارسال شود.")
    return list(dict.fromkeys(cleaned))
