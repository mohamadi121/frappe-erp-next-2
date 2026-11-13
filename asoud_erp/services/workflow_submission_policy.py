"""Pure input policy; importing the stage normalizer must not require a bench."""


def normalize(value):
    if value is None:
        return None
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or
            not value[k].strip() or len(value[k]) > 140 for k in ('form', 'revision')):
        raise ValueError('درخواست یا سند انتخاب‌شده و نسخهٔ آن معتبر نیست.')
    return {k: value[k].strip() for k in ('form', 'revision')}


def choose_route(candidates, *, legacy_default=False):
    """Select one primary route, never a database-order winner."""
    matches = [row for row in candidates if row.get('matched')]
    if len(matches) > 1:
        raise ValueError('شرایط بیش از یک گردش‌کار با این ارسال منطبق است؛ مدیر باید شرط‌ها را بدون تداخل تنظیم کند.')
    if matches:
        return matches[0]['name']
    defaults = [row for row in candidates if row['mode'] == 'Default']
    if len(defaults) > 1 or (defaults and legacy_default):
        raise ValueError('برای این فرم بیش از یک گردش‌کار پیش‌فرض وجود دارد؛ مدیر باید تعارض را رفع کند.')
    if defaults:
        row = defaults[0]
        if row['status'] != 'Active' or row['readiness_status'] != 'Ready':
            raise ValueError('گردش‌کار پیش‌فرض هنوز فعال و آماده نیست؛ مدیر باید طراحی آن را تکمیل کند.')
        if row.get('stale'):
            raise ValueError('نسخهٔ فرم تغییر کرده است؛ اتصال گردش‌کار باید به‌روزرسانی شود.')
        return row['name']
    if legacy_default or not candidates:
        return None
    raise ValueError('هیچ مسیر مشروطی منطبق نیست و گردش‌کار پیش‌فرضی برای این فرم تعیین نشده است.')
