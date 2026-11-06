"""Pure policy for explicit v1 start configuration; no parallel workflow engine."""
import re

from asoud_erp.services.workflow_submission_policy import normalize


def validate_request_id(request_id: str | None) -> None:
    if request_id is not None and request_id != '':
        if not isinstance(request_id, str) or not re.match(r'^[A-Za-z0-9_-]{8,64}$', request_id):
            raise ValueError('شناسهٔ درخواست (request_id) معتبر نیست؛ باید بین ۸ تا ۶۴ نویسه و شامل حروف، ارقام، خط تیره یا زیرخط باشد.')


def normalize_settings(value):
    allowed = {'trigger_type', 'initiator_roles', 'submission_source', 'allow_manager_restart', 'require_manual_reason'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('تنظیمات شروع گردش‌کار معتبر نیست.')
    trigger = value.get('trigger_type')
    roles = value.get('initiator_roles', [])
    if not isinstance(trigger, str) or trigger not in {'Manual', 'Document Event'} or not isinstance(roles, list) or len(roles) > 100:
        raise ValueError('نحوهٔ شروع یا نقش‌های مجاز معتبر نیست.')
    if any(not isinstance(role, str) or not role.strip() or len(role) > 140 or role.strip() in {'Guest', 'All'} for role in roles):
        raise ValueError('نقش مجاز شروع را از فهرست نقش‌های فعال انتخاب کنید.')
    for key in ('allow_manager_restart', 'require_manual_reason'):
        if key in value and type(value[key]) is not bool:
            raise ValueError('گزینه‌های تنظیمات اضافی باید روشن یا خاموش باشند.')
    if value.get('require_manual_reason', True) is not True:
        raise ValueError('ثبت علت شروع دستی الزامی است و غیرفعال نمی‌شود.')
    source = normalize(value.get('submission_source'))
    if trigger == 'Manual' and (source or not roles):
        raise ValueError('برای شروع دستی نقش مجاز انتخاب کنید؛ اتصال فرم در این حالت مجاز نیست.')
    if trigger == 'Document Event' and not source:
        raise ValueError('برای شروع با ارسال فرم، درخواست یا سند منتشرشده را انتخاب کنید.')
    return {'start_settings_version': 1, 'trigger_type': trigger,
        'initiator_roles': list(dict.fromkeys(role.strip() for role in roles)),
        'submission_source': source, 'allow_manager_restart': value.get('allow_manager_restart', False),
        'require_manual_reason': value.get('require_manual_reason', True),
        'prevent_duplicate': True, 'prevent_restart': True, 'audit_start': True,
        'subject_source': 'General Subject' if trigger == 'Manual' else 'Referenced Document', 'pass_mode': 'Direct'}


def start_decision(config, existing_status, restart, manager, reason):
    if not isinstance(reason, str) or len(reason) > 1000:
        raise ValueError('علت شروع باید متن و حداکثر ۱۰۰۰ نویسه باشد.')
    if existing_status and not restart:
        return 'reuse'  # Idempotent submit/retry is not an explicit second execution.
    if restart:
        if not existing_status or existing_status == 'Running':
            raise ValueError('شروع مجدد فقط پس از خاتمهٔ اجرای قبلی مجاز است؛ اجرای هم‌زمان ساخته نمی‌شود.')
        if not config.get('allow_manager_restart') or not manager:
            raise ValueError('شروع مجدد برای این رکورد مجاز نیست؛ استثنای مدیر باید فعال و دسترسی او تأیید شود.')
        if not reason.strip():
            raise ValueError('برای استثنای شروع مجدد، ثبت علت الزامی است.')
    if config.get('trigger_type') == 'Manual' and not reason.strip():
        raise ValueError('علت شروع دستی گردش‌کار را وارد کنید.')
    return 'new'
