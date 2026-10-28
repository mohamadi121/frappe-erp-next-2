"""Pure input policy; importing the stage normalizer must not require a bench."""


def normalize(value):
    if value is None:
        return None
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or
            not value[k].strip() or len(value[k]) > 140 for k in ('form', 'revision')):
        raise ValueError('درخواست یا سند انتخاب‌شده و نسخهٔ آن معتبر نیست.')
    return {k: value[k].strip() for k in ('form', 'revision')}
