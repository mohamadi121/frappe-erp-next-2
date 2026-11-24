"""Personal Event calendar; calendar-only holidays never alter HR Holiday Lists."""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, now_datetime

from asoud_erp.api.v1.responses import success
from asoud_erp.services.erp_documents import require_roles
from asoud_erp.services.request_access import company_access, require_company

SCOPE = 'ASOUD Calendar Scope'
HOLIDAY = 'ASOUD Calendar Holiday'


def fail(message):
    frappe.throw(message, frappe.ValidationError)


def parse_payload(value):
    if isinstance(value, str):
        if len(value) > 100000:
            fail('حجم داده بیش از حد است.')
        value = json.loads(value)
    if not isinstance(value, dict):
        fail('ساختار داده معتبر نیست.')
    return value


def day(value):
    try:
        result = date.fromisoformat(str(value))
        if not 1900 <= result.year <= 2100:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        fail('تاریخ معتبر نیست.')


def title(value):
    text = str(value or '').strip()
    if not text or len(text) > 140:
        fail('عنوان باید بین ۱ تا ۱۴۰ نویسه باشد.')
    return text


def manager():
    return frappe.session.user == 'Administrator' or bool({'System Manager', 'HR Manager'} & set(frappe.get_roles()))


def store(doc):
    doc.flags.calendar_service = True
    is_new = doc.is_new() or not doc.name or not frappe.db.exists(doc.doctype, doc.name)
    return doc.insert(ignore_permissions=True, set_name=doc.name) if is_new else doc.save(ignore_permissions=True)


def guard(doc):
    if not doc.flags.calendar_service:
        frappe.throw('از API تقویم استفاده کنید.', frappe.PermissionError)


def personal_row(scope, event):
    start = get_datetime(event.starts_on)
    end = get_datetime(event.ends_on or event.starts_on)
    return dict(id=scope.client_id, kind=scope.kind, title=event.subject,
                date=str(start.date()), end_date=str((end - timedelta(seconds=1)).date()) if event.all_day else str(start.date()),
                time=start.strftime('%H:%M'), end_time=end.strftime('%H:%M'),
                all_day=bool(event.all_day),
                starts_at=None if event.all_day else _instant(start),
                ends_at=None if event.all_day else _instant(end),
                done=event.status == 'Completed', version=str(event.modified))


def _instant(value):
    clock = get_datetime(value)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ZoneInfo(get_system_timezone()))
    return clock.astimezone(timezone.utc).isoformat()


def _native_items(company, start, end):
    """Native calendar expansion + existing HR sources, strictly office/personal scoped."""
    from frappe.desk.doctype.event.event import get_events

    items = []
    # No office may be guessed for a global Event. Native reference binds it to Company.
    if frappe.has_permission("Event", "read") and frappe.get_meta("Event").has_field("reference_doctype"):
        events = get_events(str(start), str(end), filters={
            "reference_doctype": "Company", "reference_docname": company})
        completed = frappe.get_list("Event", filters={
            "reference_doctype": "Company", "reference_docname": company,
            "status": "Completed", "starts_on": ["<", str(end + timedelta(days=1))],
            "ends_on": [">=", str(start)]}, pluck="name", limit_page_length=2001)
        events.extend(frappe.get_doc("Event", name) for name in completed)
        if len(events) > 2000:
            fail("تعداد برنامه‌ها زیاد است؛ بازه کوچک‌تری انتخاب کنید.")
        for event in events:
            if frappe.db.exists(SCOPE, {'company': company, 'user': frappe.session.user,
                    'event': event.name, 'active': 1}):
                continue
            original = frappe.get_cached_doc("Event", event.name)
            if original.owner != frappe.session.user and not any(
                    p.email == frappe.session.user and p.attending != "No"
                    for p in original.event_participants):
                continue
            if not frappe.has_permission("Event", "read", original):
                continue
            began = get_datetime(event.starts_on)
            ended = get_datetime(event.ends_on or event.starts_on)
            items.append(dict(id="event:" + event.name + ":" + began.isoformat(),
                source_type="Event", source_id=event.name,
                kind="Meeting" if original.event_category == "Meeting" else "Event",
                title=event.subject, date=str(began.date()), end_date=str(ended.date()),
                time="" if event.all_day else began.strftime("%H:%M"),
                end_time="" if event.all_day else ended.strftime("%H:%M"),
                all_day=bool(event.all_day), starts_at=None if event.all_day else _instant(began),
                ends_at=None if event.all_day else _instant(ended), done=original.status == "Completed",
                detail=original.location or ""))
    employees = frappe.get_all("Employee", filters={
        "company": company, "user_id": frappe.session.user, "status": "Active"}, pluck="name")
    if not employees:
        return items
    # Same self-service boundary as hr_self_service._mine, additionally office-filtered.
    if frappe.db.exists("DocType", "Attendance Request"):
        missions = frappe.get_all("Attendance Request", filters={
            "company": company, "employee": ["in", employees], "reason": "On Duty",
            "docstatus": ["!=", 2], "from_date": ["<=", end], "to_date": [">=", start]},
            fields=["name", "from_date", "to_date", "docstatus", "explanation"],
            limit_page_length=2001)
        if len(missions) > 2000:
            fail("تعداد مأموریت‌ها زیاد است؛ بازه کوچک‌تری انتخاب کنید.")
        for mission in missions:
            items.append(dict(id="mission:" + mission.name, source_type="Attendance Request",
                source_id=mission.name, kind="Mission", title="مأموریت",
                date=str(mission.from_date), end_date=str(mission.to_date),
                all_day=True, done=False, detail=mission.explanation or "",
                record_status="ثبت‌شده" if mission.docstatus == 1 else "پیش‌نویس"))
    if frappe.db.exists("DocType", "Travel Request"):
        # Filter the native itinerary in SQL before reading documents, never fetch years of records.
        names = frappe.db.sql_list("""select distinct t.name from `tabTravel Request` t
            inner join `tabTravel Itinerary` i on i.parent=t.name and i.parenttype='Travel Request'
            where t.company=%(company)s and t.employee in %(employees)s and t.docstatus!=2
            and i.departure_date<=%(end)s
            and coalesce(i.arrival_date,i.departure_date)>=%(start)s limit 2001""",
            dict(company=company, employees=employees, start=start, end=end))
        if len(names) > 2000:
            fail("تعداد مأموریت‌ها زیاد است؛ بازه کوچک‌تری انتخاب کنید.")
        for name in names:
            mission = frappe.get_doc("Travel Request", name)
            for leg in mission.itinerary:
                if not leg.departure_date:
                    continue
                began, ended = day(str(leg.departure_date)), day(str(leg.arrival_date or leg.departure_date))
                if began > end or ended < start:
                    continue
                items.append(dict(id="travel:" + name + ":" + leg.name,
                    source_type="Travel Request", source_id=name, kind="Mission",
                    title="مأموریت", date=str(began), end_date=str(ended), all_day=True,
                    done=False, detail=(leg.travel_from or "") + " ← " + (leg.travel_to or ""),
                    record_status="ثبت‌شده" if mission.docstatus == 1 else "پیش‌نویس"))
    return items


def _action_items(company, start, end, *, only_range=False):
    """Read the existing personal inbox; never create calendar copies of tasks."""
    from asoud_erp.api.v1.workflow_runtime import _assert_generic_access, list_my_workflow_tasks
    from asoud_erp.services.request_link_values import workflow_company

    counts = dict(waiting=0, overdue=0, high_priority=0)
    items, scopes, references = [], {}, {}
    cursor = 0
    clock = now_datetime()
    while True:
        page = list_my_workflow_tasks(status="Open", start=cursor, paged=1)["data"]
        for task in page["items"]:
            due = get_datetime(task["due_on"]) if task.get("due_on") else None
            if only_range and (not due or not start <= due.date() <= end):
                continue
            instance_id = task.get("workflow_instance")
            if not instance_id:
                continue  # No provable office: never infer from a user's other offices.
            try:
                _assert_generic_access(frappe.get_doc('ASOUD Workflow Task', task['name']))
            except frappe.PermissionError:
                continue
            if instance_id not in scopes:
                scopes[instance_id] = workflow_company(instance_id)
            if scopes[instance_id] != company:
                continue
            if instance_id not in references:
                instance = frappe.db.get_value("ASOUD Workflow Instance", instance_id,
                    ["reference_doctype", "reference_name", "status"], as_dict=True)
                priority = ""
                if instance and instance.reference_doctype and instance.reference_name:
                    meta = frappe.get_meta(instance.reference_doctype)
                    if meta.has_field("priority"):
                        priority = frappe.db.get_value(instance.reference_doctype,
                            instance.reference_name, "priority") or ""
                references[instance_id] = (instance, priority)
            instance, priority = references[instance_id]
            if not instance or instance.status != "Running":
                continue
            overdue = bool(due and due < clock)
            counts["waiting"] += 1
            counts["overdue"] += int(overdue)
            counts["high_priority"] += int(priority in ("High", "Urgent"))
            if due and start <= due.date() <= end:
                items.append(dict(id="task:" + task["name"], source_type="Task",
                    source_id=task["name"], kind="Deadline", title=task["task_title"],
                    date=str(due.date()), end_date=str(due.date()), time=due.strftime("%H:%M"),
                    deadline=True, overdue=overdue, done=False))
        next_cursor = page.get("next_cursor")
        if next_cursor is None:
            break
        if int(next_cursor) <= cursor:
            fail("دریافت کامل کارتابل انجام نشد؛ دوباره تلاش کنید.")
        cursor = int(next_cursor)
    return counts, items


@frappe.whitelist()
def get_calendar(company, start, end, summary_only=0):
    require_company(company)
    start, end = day(start), day(end)
    if end < start or (end - start).days > 62:
        fail('بازه تقویم حداکثر ۶۳ روز است.')
    source_warnings = []
    if str(summary_only) == "1":
        counts, _ = _action_items(company, start, end)
        return success(dict(action_counts=counts, timezone=get_system_timezone()))
    counts, action_items = None, []
    try:
        _, action_items = _action_items(company, start, end, only_range=True)
    except frappe.PermissionError:
        source_warnings.append("دسترسی به برنامه‌های کارتابل تأیید نشد.")
    except Exception:
        frappe.log_error(title="Calendar inbox adapter")
        source_warnings.append("برنامه‌های کارتابل دریافت نشد؛ دوباره تلاش کنید.")
    native_items = []
    try:
        native_items = _native_items(company, start, end)
    except Exception:
        frappe.log_error(title="Calendar native sources")
        source_warnings.append("جلسه‌ها و مأموریت‌ها کامل دریافت نشدند؛ دوباره تلاش کنید.")
    # Scope is a private binding to native Event, not a duplicate task ledger.
    records = frappe.db.sql('''select s.client_id, s.kind, e.subject, e.starts_on, e.ends_on,
        e.all_day, e.status, e.modified from `tabASOUD Calendar Scope` s
        inner join `tabEvent` e on e.name=s.event
        where s.company=%s and s.user=%s and s.active=1 and e.owner=%s and e.status!='Cancelled'
        and e.starts_on < %s and coalesce(e.ends_on,e.starts_on) >= %s
        order by e.starts_on limit 2001''',
        (company, frappe.session.user, frappe.session.user, str(end + timedelta(days=1)), str(start)), as_dict=True)
    if len(records) > 2000:
        fail('تعداد موارد زیاد است؛ بازه کوچک‌تری انتخاب کنید.')
    items = [*action_items, *native_items]
    for record in records:
        items.append(personal_row(record, record))
    for kind, filters in [('Organization', {'company': company}), ('Official', {'kind': 'Official'})]:
        filters.update(kind=kind, start_date=['<=', end], end_date=['>=', start], active=1)
        holidays = frappe.get_all(HOLIDAY, filters=filters, fields=['name', 'title', 'start_date', 'end_date', 'modified'], limit_page_length=2001)
        if len(holidays) > 2000:
            fail('تعداد تعطیلات بیش از حد مجاز است.')
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
    return success(dict(items=items, alerts=alerts, action_counts=counts, source_warnings=source_warnings, can_manage=manager(), timezone=get_system_timezone(),
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
        if scope.fingerprint != fingerprint:
            fail('شناسه ارسال تکراری با محتوای متفاوت است.')
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
        if kind not in ('Reminder', 'PersonalDay'):
            fail('نوع تقویم معتبر نیست.')
        start, end = day(data.get('date')), day(data.get('end_date', data.get('date')))
        if end < start or (end - start).days > 366:
            fail('بازه تاریخ معتبر نیست.')
        clock = str(data.get('time', '09:00'))
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
            fail('ساعت معتبر نیست.')
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
    if not manager():
        frappe.throw('مجوز مدیریت تعطیلی لازم است.', frappe.PermissionError)
    data = parse_payload(payload)
    ident = str(data.get('id', ''))
    if not re.fullmatch(r'[a-f0-9]{24}', ident):
        fail('شناسه نامعتبر است.')
    frappe.get_doc('Company', company, for_update=True)
    exists = frappe.db.exists(HOLIDAY, ident)
    doc = frappe.get_doc(HOLIDAY, ident, for_update=True) if exists else frappe.get_doc(dict(
        doctype=HOLIDAY, name=ident, company=company, kind='Organization', active=1))
    if doc.company != company or doc.kind != 'Organization':
        frappe.throw('دسترسی مجاز نیست.', frappe.PermissionError)
    if exists and str(doc.modified) != str(data.get('version', '')):
        frappe.throw('تعطیلی تغییر کرده؛ تقویم را تازه کنید.', frappe.TimestampMismatchError)
    doc.title = title(data.get('title'))
    doc.start_date, doc.end_date = day(data.get('date')), day(data.get('end_date'))
    if doc.end_date < doc.start_date or (doc.end_date - doc.start_date).days > 366:
        fail('بازه تعطیلی معتبر نیست.')
    doc.active = 0 if data.get('deleted') is True else 1
    store(doc)
    return success(dict(saved=True))


@frappe.whitelist(methods=['POST'])
def import_official(payload):
    """Explicit reviewed batch import; never scrape or guess lunar holidays."""
    require_roles(('System Manager',))
    if 'System Manager' not in frappe.get_roles():
        frappe.throw('مجوز مدیر سیستم لازم است.', frappe.PermissionError)
    data = parse_payload(payload)
    source = str(data.get('source_url', ''))
    if urlparse(source).hostname != 'calendar.ut.ac.ir' or urlparse(source).scheme != 'https':
        fail('مرجع تطبیق باید نشانی HTTPS مرکز تقویم دانشگاه تهران باشد.')
    if data.get('reviewed') is not True:
        fail('تأیید تطبیق انسانی با تقویم رسمی لازم است.')
    start, end = day(data.get('start')), day(data.get('end'))
    rows = data.get('days')
    if end < start or (end - start).days > 366 or not isinstance(rows, list) or len(rows) > 366:
        fail('بازه واردسازی معتبر نیست.')
    prepared = {}
    for row in rows:
        date_value = day(row.get('date'))
        if not start <= date_value <= end:
            fail('تاریخ خارج از بازه است.')
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
