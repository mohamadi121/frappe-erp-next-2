"""Pure input policy; importing the stage normalizer must not require a bench."""


def request_mode(schema):
    """Absent intent is legacy, never an inferred record-only policy."""
    if schema.get('kind') != 'Request':
        return None
    mode = schema.get('workflow_mode')
    if mode is None or mode == '':
        return None
    if not isinstance(mode, str) or mode not in {'Fixed', 'Conditional', 'RecordOnly'}:
        raise ValueError('روش اتصال فرم به گردش‌کار معتبر نیست.')
    if mode == 'Fixed':
        name = schema.get('workflow')
        if not isinstance(name, str) or not name.strip() or len(name) > 140:
            raise ValueError('برای روش گردش مشخص، یک گردش‌کار معتبر انتخاب کنید.')
    return mode


def require_record_only_policy(mode):
    # No existing, authoritative approval exemption exists. Do not introduce a
    # blanket policy (or infer one from a preset's name) just to bypass routing.
    if mode == 'RecordOnly':
        raise ValueError('فقط ثبت فرم هنوز مجاز نیست؛ سیاست معتبرِ بی‌نیازی این فرم از تأیید مشخص نشده است.')


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
