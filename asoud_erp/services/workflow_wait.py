"""Durable Wait adapter on the existing workflow instance and Frappe scheduler."""
import json
from datetime import datetime, timezone

import frappe

from asoud_erp.services.workflow_wait_policy import due_time, normalize, zone

INSTANCE = 'ASOUD Workflow Instance'


def utc_now():
    return datetime.now(timezone.utc)


def ready():
    return frappe.db.has_column(INSTANCE, 'wait_due_utc') and frappe.db.has_column(INSTANCE, 'wait_snapshot_json')


def blocked_message():
    from frappe.utils.scheduler import is_scheduler_inactive

    if not ready():
        return 'اجرای انتظار به به‌روزرسانی پایگاه دادهٔ سامانه نیاز دارد.'
    if is_scheduler_inactive(verbose=False):
        return 'زمان‌بند سامانه غیرفعال است یا سامانه در حالت نگهداری است؛ مدیر باید آن را بررسی کند.'
    return None


def office_zone(definition):
    from frappe.utils import get_system_timezone

    company = frappe.db.get_value('ASOUD Workflow Definition', definition, 'company')
    value = frappe.db.get_value('Company', company, 'time_zone') if frappe.get_meta('Company').has_field('time_zone') else None
    result = value or get_system_timezone()
    zone(result)
    return result, 'Company' if value else 'System'


def fields(definition, stage):
    from asoud_erp.services.workflow_condition_binding import catalog

    return [row for row in catalog(definition, stage, stage_types=('Wait',))
        if row['source_kind'] in {'Original', 'Stage'} and row['field_type'] in {'Date', 'DateTime'}]


def binding(config, available):
    source = config.get('date_source')
    if config['wait_type'] != 'FormDate':
        return
    if not any(all(row.get(key) == source.get(key) for key in
            ('source_kind', 'source_stage', 'source_field', 'field_type')) for row in available):
        raise ValueError('فیلد تاریخ مبدأ حذف، مخفی یا تغییرنوع داده است؛ دوباره فیلد معتبر انتخاب کنید.')


def destination(definition, stage):
    rows = frappe.get_all('ASOUD Workflow Transition', filters={'workflow_definition': definition,
        'from_stage': stage}, fields=['to_stage', 'condition_json'], limit_page_length=3)
    if len(rows) != 1 or json.loads(rows[0].condition_json or '{}'):
        raise ValueError('مرحلهٔ انتظار باید دقیقاً یک اتصال خروجی عادی در نمودار داشته باشد.')
    if not frappe.db.exists('ASOUD Workflow Stage', rows[0].to_stage):
        raise ValueError('مقصد خروجی انتظار حذف شده است؛ اتصال نمودار را اصلاح کنید.')
    target = frappe.get_doc('ASOUD Workflow Stage', rows[0].to_stage)
    if target.workflow_definition != definition or target.stage_type == 'Start' or target.name == stage:
        raise ValueError('مقصد خروجی انتظار معتبر نیست؛ اتصال نمودار را اصلاح کنید.')
    return target


def validate_design(definition, stage, config):
    config = normalize(config)
    blocked = blocked_message()
    if blocked:
        raise ValueError(blocked)
    tz, _ = office_zone(definition)
    if config['wait_type'] == 'FormDate':
        binding(config, fields(definition, stage))
    elif config['wait_type'] == 'Date':
        due_time(config, utc_now(), tz)
    destination(definition, stage)
    return config


def audit(instance, snapshot, action, message):
    from frappe.utils import now_datetime

    frappe.get_doc({'doctype': 'ASOUD Workflow Activity', 'workflow_instance': instance.name,
        'workflow_stage': snapshot['stage'], 'actor': frappe.session.user, 'action': action,
        'comment': message, 'created_on': now_datetime(),
        'change_json': json.dumps(snapshot, default=str, ensure_ascii=False)}).insert(ignore_permissions=True)


def source_value(instance, config):
    from asoud_erp.api.v1.workflow_runtime import _assert_instance_access
    from asoud_erp.services.request_access import require_company
    from asoud_erp.services.workflow_condition_binding import resolver

    available = fields(instance.workflow_definition, instance.current_stage)
    binding(config, available)
    previous = frappe.session.user
    try:
        # Background work must not turn an unreadable source into Administrator access.
        if not frappe.db.get_value('User', instance.started_by, 'enabled'):
            raise ValueError('حساب ثبت‌کننده برای خواندن تاریخ مبدأ فعال نیست.')
        frappe.set_user(instance.started_by)
        company = frappe.db.get_value('ASOUD Workflow Definition', instance.workflow_definition, 'company')
        require_company(company)
        _assert_instance_access(instance)
        return resolver(instance, {'conditions': [config['date_source']]}, available)(config['date_source'])
    except frappe.PermissionError as error:
        raise ValueError('ثبت‌کننده دیگر دسترسی معتبر برای خواندن تاریخ مبدأ این فرایند ندارد.') from error
    finally:
        frappe.set_user(previous)


def persist(instance, snapshot):
    instance.wait_snapshot_json = json.dumps(snapshot, default=str, ensure_ascii=False)
    instance.wait_due_utc = (datetime.fromisoformat(snapshot['due_utc']).replace(tzinfo=None)
        if snapshot['state'] == 'Waiting' else None)
    instance.save(ignore_permissions=True)


def lock_for_cancellation(request_name):
    """Wait workers and requester cancellation serialize on the same instance first."""
    from asoud_erp.services.request_access import require_company

    if not ready():
        return None
    request = frappe.db.get_value('ASOUD Workflow Request', request_name,
        ['owner', 'company', 'workflow_instance'], as_dict=True)
    if not request or not request.workflow_instance:
        return None
    if request.owner != frappe.session.user:
        frappe.throw('فقط ثبت‌کننده می‌تواند این درخواست را لغو کند.', frappe.PermissionError)
    require_company(request.company)
    if not frappe.db.get_value(INSTANCE, request.workflow_instance, 'wait_due_utc'):
        return None
    instance = frappe.get_doc(INSTANCE, request.workflow_instance, for_update=True)
    if instance.status != 'Running':
        frappe.throw('این فرایند دیگر در حال انتظار نیست؛ وضعیت درخواست را تازه کنید.')
    return instance


def failed(instance, snapshot, error):
    from frappe.utils import now_datetime

    snapshot.update(state='Failed', error=str(error), actual_utc=utc_now().isoformat())
    instance.status, instance.completed_on = 'Failed', now_datetime()
    persist(instance, snapshot)
    audit(instance, snapshot, 'Wait Failed', str(error))


def schedule(instance, stage, config):
    existing = json.loads(instance.get('wait_snapshot_json') or '{}')
    if existing.get('state') == 'Waiting' and existing.get('stage') == stage.name:
        return
    snapshot = {'state': 'Waiting', 'stage': stage.name, 'entered_utc': utc_now().isoformat(),
        'definition_version': frappe.db.get_value('ASOUD Workflow Definition', instance.workflow_definition, 'version_no')}
    try:
        config = validate_design(instance.workflow_definition, stage.name, {'title': stage.stage_title, **config})
        tz, _ = office_zone(instance.workflow_definition)
        value = source_value(instance, config) if config['wait_type'] == 'FormDate' else None
        due = due_time(config, datetime.fromisoformat(snapshot['entered_utc']), tz, value)
        snapshot.update(config=config, time_zone=tz, source_value=str(value) if value is not None else None,
            due_utc=due.isoformat(), scheduled_utc=due.isoformat(),
            target=destination(instance.workflow_definition, stage.name).name)
        if due < utc_now() and config['past_policy'] == 'Error':
            raise ValueError('زمان تعیین‌شدهٔ انتظار گذشته است؛ طبق سیاست این مرحله، فرایند متوقف شد.')
        persist(instance, snapshot)
        audit(instance, snapshot, 'Wait Scheduled', 'انتظار ثبت شد؛ ادامهٔ فرایند به‌صورت خودکار در سرور انجام می‌شود.')
    except (ValueError, frappe.ValidationError, frappe.PermissionError) as error:
        if not ready():
            frappe.throw('زیرساخت انتظار نصب نشده است؛ مدیر باید به‌روزرسانی پایگاه داده را اجرا کند.')
        failed(instance, snapshot, error)


def run(name):
    """One native transaction: lock, source refresh, idempotent continuation, audit."""
    from asoud_erp.api.v1.workflow_runtime import _activate_stage

    instance = frappe.get_doc(INSTANCE, name, for_update=True)
    snapshot = json.loads(instance.wait_snapshot_json or '{}')
    if snapshot.get('state') != 'Waiting':
        return
    if instance.status != 'Running' or instance.current_stage != snapshot['stage']:
        snapshot.update(state='Cancelled', actual_utc=utc_now().isoformat())
        persist(instance, snapshot)
        audit(instance, snapshot, 'Wait Cancelled', 'انتظار قبلی به دلیل خاتمه یا تغییر مرحلهٔ جاری بی‌اثر شد.')
        return
    frappe.db.savepoint('wait_resume')
    try:
        config = snapshot['config']  # Pin the entry-time config, not a newer designer edit.
        if config['wait_type'] == 'FormDate' and config['date_change_policy'] == 'Recalculate':
            value = source_value(instance, config)
            if str(value) != snapshot.get('source_value'):
                due = due_time(config, datetime.fromisoformat(snapshot['entered_utc']), snapshot['time_zone'], value)
                snapshot.update(source_value=str(value), previous_due_utc=snapshot['due_utc'], due_utc=due.isoformat())
                if due < utc_now() and config['past_policy'] == 'Error':
                    raise ValueError('تاریخ جدید مبدأ گذشته است؛ فرایند طبق تنظیمات متوقف شد.')
                persist(instance, snapshot)
                audit(instance, snapshot, 'Wait Rescheduled', 'زمان انتظار بر اساس تغییر معتبر تاریخ مبدأ محاسبه شد.')
        if datetime.fromisoformat(snapshot['due_utc']) > utc_now():
            return
        if not frappe.db.exists('ASOUD Workflow Stage', snapshot['target']):
            raise ValueError('مقصد ثبت‌شدهٔ انتظار حذف شده است؛ فرایند ادامه نیافت.')
        target = frappe.get_doc('ASOUD Workflow Stage', snapshot['target'])
        if target.workflow_definition != instance.workflow_definition or target.stage_type == 'Start' or target.name == snapshot['stage']:
            raise ValueError('مقصد ثبت‌شدهٔ انتظار دیگر معتبر نیست؛ فرایند ادامه نیافت.')
        snapshot.update(state='Completed', actual_utc=utc_now().isoformat())
        persist(instance, snapshot)
        audit(instance, snapshot, 'Wait Completed', 'زمان انتظار پایان یافت؛ فرایند از اتصال ثبت‌شده ادامه یافت.')
        _activate_stage(instance, target, automatic_trigger=f"wait:{snapshot['stage']}:{snapshot['entered_utc']}")
    except Exception as error:
        frappe.db.rollback(save_point='wait_resume')
        instance.reload()
        # Do not expose infrastructure errors or pretend a failed action is a false result.
        message = str(error) if isinstance(error, (ValueError, frappe.ValidationError)) else 'ادامهٔ انتظار در سرور انجام نشد؛ مدیر سامانه باید سوابق خطا را بررسی کند.'
        failed(instance, snapshot, message)
        frappe.log_error(title='خطا در ادامهٔ انتظار', message=frappe.get_traceback())


def dispatch():
    if not ready():
        return
    after = ''
    while True:
        # Scan waiting rows in keyset pages; future Recalculate waits also need polling.
        rows = frappe.get_all(INSTANCE, filters={'name': ['>', after], 'wait_due_utc': ['is', 'set']},
            pluck='name', order_by='name asc', limit_page_length=200)
        if not rows:
            break
        for name in rows:
            frappe.db.savepoint('wait_dispatch_row')
            try:
                frappe.enqueue('asoud_erp.services.workflow_wait.run', name=name, job_id=f'asoud-wait-{name}',
                    deduplicate=True, enqueue_after_commit=True)
            except Exception:
                frappe.db.rollback(save_point='wait_dispatch_row')
                frappe.log_error(title='خطا در صف انتظار', message=frappe.get_traceback())
        after = rows[-1]
