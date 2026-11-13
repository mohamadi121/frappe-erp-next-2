"""Pure timing policy for the existing Wait stage. All instants are UTC-aware."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from asoud_erp.services.digits import to_ascii_digits


def zone(name):
    try:
        return ZoneInfo(name)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError('منطقهٔ زمانی دفتر معتبر نیست؛ تنظیمات سامانه را بررسی کنید.') from exc


def integer(value, minimum=0):
    value = to_ascii_digits(value)
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit() or not minimum <= int(value) <= 3650:
        raise ValueError('مقدار باید عدد صحیح در محدودهٔ مجاز تا ۳۶۵۰ باشد.')
    return int(value)


def clock(value):
    value = to_ascii_digits(value)
    try:
        result = time.fromisoformat(value)
        if len(value) != 5 or result.tzinfo or result.second or result.microsecond:
            raise ValueError
        return result
    except (TypeError, ValueError) as exc:
        raise ValueError('ساعت را با قالب ۲۴ ساعته، مانند ۰۹:۰۰، وارد کنید.') from exc


def local_instant(value, tz):
    """Reject nonexistent/ambiguous wall clocks, never silently pick a DST fold."""
    if value.tzinfo:
        return value.astimezone(timezone.utc)
    first, second = value.replace(tzinfo=tz, fold=0), value.replace(tzinfo=tz, fold=1)
    valid = [item for item in (first, second)
        if item.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == value]
    if not valid or (len(valid) == 2 and first.utcoffset() != second.utcoffset()):
        raise ValueError('این ساعت در منطقهٔ زمانی دفتر مبهم یا ناموجود است؛ ساعت دیگری انتخاب کنید.')
    return valid[0].astimezone(timezone.utc)


def normalize(raw):
    if not isinstance(raw, dict) or raw.get('wait_version') != 1:
        raise ValueError('تنظیمات قدیمی انتظار باید با فرم جدید بررسی و ذخیره شوند.')
    title, description = raw.get('title'), raw.get('description', '')
    if not isinstance(title, str) or not 3 <= len(title.strip()) <= 140:
        raise ValueError('عنوان مرحله باید بین ۳ تا ۱۴۰ نویسه باشد.')
    if not isinstance(description, str) or len(description) > 500:
        raise ValueError('توضیحات باید حداکثر ۵۰۰ نویسه باشد.')
    kind, past = raw.get('wait_type'), raw.get('past_policy', 'Continue')
    if kind not in {'Duration', 'Date', 'FormDate'} or past not in {'Continue', 'Error'}:
        raise ValueError('نوع انتظار یا سیاست زمان گذشته معتبر نیست.')
    result = dict(wait_version=1, title=title.strip(), description=description.strip(), wait_type=kind, past_policy=past)
    if kind == 'Duration':
        unit = raw.get('wait_unit')
        if unit not in {'Minute', 'Hour', 'Day'}:
            raise ValueError('واحد زمان انتظار معتبر نیست.')
        result.update(wait_value=integer(raw.get('wait_value'), 1), wait_unit=unit)
    elif kind == 'Date':
        try:
            value = datetime.fromisoformat(raw['wait_value'])
            if value.tzinfo or len(raw['wait_value']) not in {16, 19}:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('تاریخ و ساعت ادامهٔ فرایند معتبر نیست.') from exc
        result['wait_value'] = value.isoformat(timespec='seconds')
    else:
        source = raw.get('date_source')
        if not isinstance(source, dict) or source.get('source_kind') not in {'Original', 'Stage'}:
            raise ValueError('منبع تاریخ فرم معتبر نیست.')
        if (not isinstance(source.get('source_field'), str) or not source['source_field']
                or len(source['source_field']) > 140 or source.get('field_type') not in {'Date', 'DateTime'}):
            raise ValueError('فیلد تاریخ معتبر انتخاب کنید.')
        stage = source.get('source_stage', '') if source['source_kind'] == 'Stage' else ''
        if not isinstance(stage, str) or (source['source_kind'] == 'Stage' and not stage) or len(stage) > 140:
            raise ValueError('مرحلهٔ منبع تاریخ معتبر نیست.')
        direction = raw.get('offset_direction', 'Same')
        change = raw.get('date_change_policy', 'Keep')
        if direction not in {'Same', 'Before', 'After'} or change not in {'Keep', 'Recalculate'}:
            raise ValueError('تنظیمات جابه‌جایی یا تغییر تاریخ معتبر نیست.')
        result.update(date_source={**{key: source[key] for key in ('source_kind', 'source_field', 'field_type')},
            'source_stage': stage}, offset_direction=direction,
            offset_days=0 if direction == 'Same' else integer(raw.get('offset_days')),
            date_change_policy=change)
        if source['field_type'] == 'Date':
            result['clock'] = clock(raw.get('clock')).strftime('%H:%M')
    return result


def due_time(config, entered, zone_name, source_value=None):
    tz = zone(zone_name)
    if entered.tzinfo is None:
        raise ValueError('زمان ورود به انتظار باید بدون ابهام باشد.')
    kind = config['wait_type']
    if kind == 'Duration':
        count, unit = config['wait_value'], config['wait_unit']
        if unit != 'Day':
            return entered.astimezone(timezone.utc) + timedelta(minutes=count if unit == 'Minute' else count * 60)
        local = entered.astimezone(tz).replace(tzinfo=None) + timedelta(days=count)
        return local_instant(local, tz)
    if kind == 'Date':
        return local_instant(datetime.fromisoformat(config['wait_value']), tz)
    if source_value in (None, ''):
        raise ValueError('فیلد تاریخ مبدأ خالی است؛ فرایند بدون تاریخ معتبر ادامه نمی‌یابد.')
    try:
        if config['date_source']['field_type'] == 'Date':
            day = source_value if type(source_value) is date else date.fromisoformat(str(source_value))
            value = datetime.combine(day, clock(config['clock']))
        else:
            if not isinstance(source_value, datetime) and ('T' not in str(source_value) and ' ' not in str(source_value)):
                raise ValueError
            value = source_value if isinstance(source_value, datetime) else datetime.fromisoformat(str(source_value).replace('Z', '+00:00'))
            if value.tzinfo:
                value = value.astimezone(tz).replace(tzinfo=None)
    except (TypeError, ValueError) as exc:
        raise ValueError('مقدار تاریخ مبدأ معتبر نیست؛ اطلاعات فرم را اصلاح کنید.') from exc
    offset = config['offset_days'] * {'Same': 0, 'Before': -1, 'After': 1}[config['offset_direction']]
    return local_instant(value + timedelta(days=offset), tz)
