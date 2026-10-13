"""Personal Event calendar; calendar-only holidays never alter HR Holiday Lists."""
import hashlib
import json
import re
from html import escape
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

import frappe
from frappe.utils import get_datetime, now_datetime, get_system_timezone

from asoud_erp.api.v1.responses import success
from asoud_erp.services.request_access import require_company, company_access

SCOPE = 'ASOUD Calendar Scope'
HOLIDAY = 'ASOUD Calendar Holiday'


def fail(message):
    frappe.throw(message, frappe.ValidationError)


def parse_payload(value):
    if isinstance(value, str):
        if len(value) > 100000: fail('حجم داده بیش از حد است.')
        value = json.loads(value)
    if not isinstance(value, dict): fail('ساختار داده معتبر نیست.')
    return value


def day(value):
    try:
        result = date.fromisoformat(str(value))
        if not 1900 <= result.year <= 2100: raise ValueError()
        return result
    except (TypeError, ValueError):
        fail('تاریخ معتبر نیست.')


def title(value):
    text = str(value or '').strip()
    if not text or len(text) > 140: fail('عنوان باید بین ۱ تا ۱۴۰ نویسه باشد.')
    return text


def manager():
    return frappe.session.user == 'Administrator' or bool({'System Manager', 'HR Manager'} & set(frappe.get_roles()))


def store(doc):
    doc.flags.calendar_service = True
    return doc.insert(ignore_permissions=True, set_name=doc.name) if doc.is_new() else doc.save(ignore_permissions=True)


def guard(doc):
    if not doc.flags.calendar_service:
        frappe.throw('از API تقویم استفاده کنید.', frappe.PermissionError)


def personal_row(scope, event):
    start = get_datetime(event.starts_on)
    end = get_datetime(event.ends_on or event.starts_on)
    return dict(id=scope.client_id, kind=scope.kind, title=event.subject,
                date=str(start.date()), end_date=str((end - timedelta(seconds=1)).date()) if event.all_day else str(start.date()),
                time=start.strftime('%H:%M'), done=event.status == 'Completed', version=str(event.modified))


@frappe.whitelist()
def get_calendar(company, start, end):
    require_company(company)
    start, end = day(start), day(end)
    if end < start or (end - start).days > 62: fail('بازه تقویم حداکثر ۶۳ روز است.')
    # Scope is a private binding to native Event, not a duplicate task ledger.
    records = frappe.db.sql('''select s.name from `tabASOUD Calendar Scope` s
        inner join `tabEvent` e on e.name=s.event
        where s.company=%s and s.user=%s and s.active=1
        and e.starts_on < %s and coalesce(e.ends_on,e.starts_on) >= %s
        order by e.starts_on limit 2001''',
        (company, frappe.session.user, str(end + timedelta(days=1)), str(start)), as_dict=True)
    if len(records) > 2000: fail('تعداد موارد زیاد است؛ بازه کوچک‌تری انتخاب کنید.')
    items = []
    for record in records:
        scope = frappe.get_doc(SCOPE, record.name)
        event = frappe.get_doc('Event', scope.event)
        if event.owner == frappe.session.user and event.status != 'Cancelled':
            items.append(personal_row(scope, event))
    for kind, filters in [('Organization', {'company': company}), ('Official', {'kind': 'Official'})]:
        filters.update(kind=kind, start_date=['<=', end], end_date=['>=', start], active=1)
        holidays = frappe.get_all(HOLIDAY, filters=filters, fields=['name', 'title', 'start_date', 'end_date', 'modified'], limit_page_length=2001)
        if len(holidays) > 2000: fail('تعداد تعطیلات بیش از حد مجاز است.')
        for h in holidays:
            items.append(dict(id=h.name, title=h.title, date=str(h.start_date), end_date=str(h.end_date),
                              kind=kind, version=str(h.modified)))
    alerts = frappe.db.sql('''select n.name as id, e.subject as title, e.starts_on as due
        from `tabNotification Log` n inner join `tabASOUD Calendar Scope` s on s.event=n.document_name
        inner join `tabEvent` e on e.name=s.event
        where n.document_type='Event' and n.for_user=%s and n.`read`=0
        and s.user=%s and s.company=%s and s.active=1 and e.owner=%s
        order by n.creation desc limit 20''',
        (frappe.session.user, frappe.session.user, company, frappe.session.user), as_dict=True)
    return success(dict(items=items, alerts=alerts, can_manage=manager(), timezone=get_system_timezone(),
        official_status='تعطیلات رسمی از آخرین داده تأییدشده نمایش داده می‌شوند.' if frappe.conf.get('asoud_calendar_provider') else
        'فقط تعطیلات رسمی واردشده و تأییدشده نمایش داده می‌شوند؛ اتصال خودکار منبع هنوز فعال نیست.'))


@frappe.whitelist(methods=['POST'])
def read_alert(company, name):
    require_company(company)
    doc = frappe.get_doc('Notification Log', name)
    if doc.for_user != frappe.session.user or doc.document_type != 'Event' or not frappe.db.exists(
            SCOPE, {'event': doc.document_name, 'user': frappe.session.user, 'company': company}):
        frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    doc.db_set('read', 1)
    return success(dict(saved=True))


@frappe.whitelist(methods=['POST'])
def save_personal(company, payload):
    require_company(company)
    data = parse_payload(payload)
    client_id = str(data.get('id', ''))
    mutation = str(data.get('mutation_id', ''))
    if not re.fullmatch(r'[a-f0-9]{24}', client_id) or not re.fullmatch(r'[a-f0-9]{24}', mutation):
        fail('شناسه درخواست معتبر نیست.')
    user = frappe.session.user
    name = hashlib.sha256(f'{company}\0{user}\0{client_id}'.encode()).hexdigest()
    # Serialize create/retry as well as update; the mutation receipt survives deletion.
    frappe.get_doc('User', user, for_update=True)
    exists = frappe.db.exists(SCOPE, name)
    scope = frappe.get_doc(SCOPE, name, for_update=True) if exists else frappe.get_doc(dict(
        doctype=SCOPE, name=name, user=user, company=company, client_id=client_id, active=1))
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if exists and scope.last_mutation == mutation:
        if scope.fingerprint != fingerprint: fail('شناسه ارسال تکراری با محتوای متفاوت است.')
        return success(dict(saved=True))
    event = frappe.get_doc('Event', scope.event, for_update=True) if exists and scope.event else None
    if event and (event.owner != user or scope.user != user or scope.company != company):
        frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    if exists and (not scope.active or str(event.modified) != str(data.get('version', ''))):
        frappe.throw('تقویم در دستگاه دیگری تغییر کرده؛ تغییر محلی محفوظ است.', frappe.TimestampMismatchError)
    if data.get('deleted') is True:
        if event:
            event.status = 'Cancelled'
            event.save(ignore_permissions=True)
        scope.active = 0
    else:
        kind = data.get('kind')
        if kind not in ('Reminder', 'PersonalDay'): fail('نوع تقویم معتبر نیست.')
        start, end = day(data.get('date')), day(data.get('end_date', data.get('date')))
        if end < start or (end - start).days > 366: fail('بازه تاریخ معتبر نیست.')
        clock = str(data.get('time', '09:00'))
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock): fail('ساعت معتبر نیست.')
        if not event:
            event = frappe.get_doc(dict(doctype='Event', event_type='Private', owner=user,
                event_category='Other', send_reminder=0, sync_with_google_calendar=0))
        event.subject = title(data.get('title'))
        event.status = 'Completed' if data.get('done') is True else 'Open'
        event.all_day = int(kind == 'PersonalDay')
        event.starts_on = datetime.combine(start, time.fromisoformat(clock) if kind == 'Reminder' else time())
        event.ends_on = datetime.combine(end + timedelta(days=1), time()) if kind == 'PersonalDay' else event.starts_on + timedelta(minutes=1)
        event.save(ignore_permissions=True)
        scope.event, scope.kind = event.name, kind
        scope.notified_version = None
    scope.last_mutation, scope.fingerprint = mutation, fingerprint
    store(scope)
    return success(dict(saved=True))


@frappe.whitelist(methods=['POST'])
def save_holiday(company, payload):
    require_company(company)
    if not manager(): frappe.throw('مجوز مدیریت تعطیلی لازم است.', frappe.PermissionError)
    data = parse_payload(payload)
    ident = str(data.get('id', ''))
    if not re.fullmatch(r'[a-f0-9]{24}', ident): fail('شناسه نامعتبر است.')
    frappe.get_doc('Company', company, for_update=True)
    exists = frappe.db.exists(HOLIDAY, ident)
    doc = frappe.get_doc(HOLIDAY, ident, for_update=True) if exists else frappe.get_doc(dict(
        doctype=HOLIDAY, name=ident, company=company, kind='Organization', active=1))
    if doc.company != company or doc.kind != 'Organization': frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    if exists and str(doc.modified) != str(data.get('version', '')):
        frappe.throw('تعطیلی تغییر کرده؛ تقویم را تازه کنید.', frappe.TimestampMismatchError)
    doc.title = title(data.get('title'))
    doc.start_date, doc.end_date = day(data.get('date')), day(data.get('end_date'))
    if doc.end_date < doc.start_date or (doc.end_date - doc.start_date).days > 366: fail('بازه تعطیلی معتبر نیست.')
    doc.active = 0 if data.get('deleted') is True else 1
    store(doc)
    return success(dict(saved=True))


@frappe.whitelist(methods=['POST'])
def import_official(payload):
    """Explicit reviewed batch import; never scrape or guess lunar holidays."""
    if 'System Manager' not in frappe.get_roles(): frappe.throw('مجوز مدیر سیستم لازم است.', frappe.PermissionError)
    data = parse_payload(payload)
    source = str(data.get('source_url', ''))
    if urlparse(source).hostname != 'calendar.ut.ac.ir' or urlparse(source).scheme != 'https':
        fail('مرجع تطبیق باید نشانی HTTPS مرکز تقویم دانشگاه تهران باشد.')
    if data.get('reviewed') is not True: fail('تأیید تطبیق انسانی با تقویم رسمی لازم است.')
    start, end = day(data.get('start')), day(data.get('end'))
    rows = data.get('days')
    if end < start or (end - start).days > 366 or not isinstance(rows, list) or len(rows) > 366:
        fail('بازه واردسازی معتبر نیست.')
    prepared = {}
    for row in rows:
        date_value = day(row.get('date'))
        if not start <= date_value <= end: fail('تاریخ خارج از بازه است.')
        prepared.setdefault(date_value, []).append(title(row.get('title')))
    frappe.get_doc('User', 'Administrator', for_update=True)
    for name in frappe.get_all(HOLIDAY, filters={'kind': 'Official', 'start_date': ['between', [start, end]]}, pluck='name'):
        doc = frappe.get_doc(HOLIDAY, name)
        doc.active = 0
        store(doc)
    for date_value, titles in prepared.items():
        name = hashlib.sha256(f'official:{date_value}'.encode()).hexdigest()[:24]
        doc = frappe.get_doc(HOLIDAY, name) if frappe.db.exists(HOLIDAY, name) else frappe.get_doc(dict(doctype=HOLIDAY, name=name))
        doc.update(dict(kind='Official', title='، '.join(titles)[:140], start_date=date_value, end_date=date_value,
                        active=1, source_url=source, reviewed_by=frappe.session.user, reviewed_on=now_datetime()))
        store(doc)
    return success(dict(count=len(prepared)))


def dispatch_reminders():
    """Native in-app Notification Log only; not a workflow task or mobile push."""
    records = frappe.db.sql('''select s.name from `tabASOUD Calendar Scope` s
        inner join `tabEvent` e on e.name=s.event
        where s.active=1 and s.kind='Reminder' and e.status='Open' and e.starts_on <= %s
        and (s.notified_version is null or s.notified_version != e.modified)
        order by e.starts_on limit 200''', (now_datetime(),), as_dict=True)
    for record in records:
        scope = frappe.get_doc(SCOPE, record.name, for_update=True)
        event = frappe.get_doc('Event', scope.event, for_update=True)
        if (not scope.active or event.status != 'Open' or get_datetime(event.starts_on) > now_datetime()
                or str(scope.notified_version) == str(event.modified)):
            continue
        if event.owner != scope.user or not company_access(scope.company, scope.user) or not frappe.db.get_value('User', scope.user, 'enabled'):
            continue
        frappe.get_doc(dict(doctype='Notification Log', for_user=scope.user, type='Alert',
            subject=escape(event.subject), document_type='Event', document_name=event.name,
            from_user=scope.user)).insert(ignore_permissions=True)
        scope.notified_version = event.modified
        store(scope)


def refresh_official_holidays():
    """Optional trusted server adapter. The app never calls a public holiday API.

    Admin must review a provider's license, reliability and official comparison
    process before configuring its installed Python dotted path in site_config.
    It returns the exact reviewed import_official payload; failure is atomic and
    preserves the previously imported calendar. No request can set this path.
    """
    path = frappe.conf.get('asoud_calendar_provider')
    if not path:
        return
    from asoud_erp.services.session_scope import as_administrator
    with as_administrator():
        import_official(frappe.get_attr(path)())
