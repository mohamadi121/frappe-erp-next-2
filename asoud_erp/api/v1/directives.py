"""Directive adapter over Internal Communication and the existing task/audit store.

No native ERP document is posted here. The protected inactive definition labels
adapter-owned tasks; it is deliberately not published as a generic workflow.
"""
import base64
import hashlib
import json
import re
from pathlib import Path

import frappe
from frappe.utils import get_fullname, getdate, now_datetime, nowdate

from asoud_erp.api.v1.responses import success
from asoud_erp.services.directive_access import (
    ADAPTER_PREFIX,
    COMMUNICATION,
    active_user,
    can_read,
    service_write,
)
from asoud_erp.services.request_access import require_company


def _data(value):
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        frappe.throw("اطلاعات ارسالی معتبر نیست.")
    return value


def _employee(company, user=None):
    require_company(company)
    user = user or frappe.session.user
    if not active_user(user):
        frappe.throw("حساب فعال لازم است.", frappe.PermissionError)
    row = frappe.db.get_value("Employee", {"company": company, "user_id": user,
        "status": "Active"}, ["name", "employee_name", "department", "designation", "reports_to"], as_dict=True)
    if not row:
        frappe.throw("پرسنل فعال این سازمان به حساب متصل نیست.", frappe.PermissionError)
    return row


def _people(company, manager=None):
    manager = manager or _employee(company).name
    rows = frappe.get_all("Employee", filters={"company": company, "reports_to": manager,
        "status": "Active", "user_id": ["is", "set"]},
        fields=["user_id", "employee_name", "department", "designation"], limit_page_length=0)
    return [dict(id=r.user_id, name=r.employee_name, department=r.department or "",
        position=r.designation or "") for r in rows if active_user(r.user_id) and r.user_id != frappe.session.user]


def _person(user):
    return dict(id=user, name=get_fullname(user))


def _policy():
    from asoud_erp.api.v1.workflow_runtime import ALLOWED_ATTACHMENT_EXTENSIONS, MAX_ATTACHMENT_BYTES
    return dict(max_bytes=MAX_ATTACHMENT_BYTES,
        max_count=frappe.get_meta(COMMUNICATION).max_attachments or None,
        extensions=sorted(ALLOWED_ATTACHMENT_EXTENSIONS))


def _get(name, company, lock=False):
    doc = frappe.get_doc(COMMUNICATION, name, for_update=lock)
    company = company or doc.company
    _employee(company)
    if doc.communication_type != "Directive" or doc.company != company or not can_read(doc):
        frappe.throw("اجازه مشاهده این دستور را ندارید.", frappe.PermissionError)
    return doc


def _active(doc):
    return [r for r in doc.recipients if r.recipient_type == "To" and r.directive_state != "Transferred"]


def _own(doc):
    return next((r for r in _active(doc) if r.user == frappe.session.user), None)


def _tasks(doc):
    if not doc.workflow_instance:
        return []
    return frappe.get_all("ASOUD Workflow Task", filters={"workflow_instance": doc.workflow_instance},
        fields=["name", "assigned_to", "status", "directive_kind", "directive_subject_task",
                "response_json", "action", "comment", "completed_on", "creation"],
        order_by="creation asc, name asc", limit_page_length=0)


def _actions(doc):
    issuer = doc.sender == frappe.session.user
    if doc.status == "Draft":
        return ["save_draft", "issue"] if issuer else []
    if doc.status != "Sent":
        return []
    result = []
    own = _own(doc)
    if own and own.directive_state in ("Pending", "Returned"):
        result.append("report")
        if doc.allow_transfer:
            result.append("transfer")
    if issuer and _active(doc) and all(r.directive_state == "Approved" for r in _active(doc)):
        if not frappe.db.exists("ASOUD Workflow Task", {"workflow_instance": doc.workflow_instance,
            "status": "Open", "directive_kind": ["!=", "Close"]}):
            result.append("close")
    if issuer and any(r.directive_state in ("Pending", "Returned") for r in _active(doc)):
        result.append("transfer")
    return result


def _file_row(doc):
    return dict(id=doc.name, filename=doc.file_name, size=doc.file_size or 0,
                content_type=Path(doc.file_name or "").suffix)


def _files(doctype, name, field=None):
    filters = {"attached_to_doctype": doctype, "attached_to_name": name, "is_private": 1}
    if field:
        filters["attached_to_field"] = field
    return [_file_row(frappe.get_doc("File", n)) for n in frappe.get_all("File", filters=filters,
        pluck="name", limit_page_length=0)]


def _state(doc):
    states = [r.directive_state for r in _active(doc)]
    if doc.status != "Sent":
        return doc.status
    if states and all(s == "Approved" for s in states):
        return "Approved"
    if "Awaiting Review" in states:
        return "Awaiting Review"
    if "Returned" in states:
        return "Returned"
    return "In Progress"


def _view(doc):
    issuer = doc.sender == frappe.session.user
    used = {r.user for r in doc.recipients} | {doc.sender}
    actions = _actions(doc)
    manager = frappe.db.get_value("Employee", {"company": doc.company,
        "user_id": doc.sender, "status": "Active"}, "name")
    people = _people(doc.company, manager) if manager and "transfer" in actions and active_user(doc.sender) else []
    if not people and "transfer" in actions:
        actions.remove("transfer")
    return dict(id=doc.name, number=doc.name, company=doc.company, subject=doc.subject or "",
        body=doc.content or "", priority=doc.priority, status=_state(doc), version=doc.directive_version,
        is_draft=doc.status == "Draft", issuer=_person(doc.sender), current_user_id=frappe.session.user,
        today=nowdate(), issue_date=str(doc.issued_on or "")[:10] or None,
        due_date=str(doc.due_date or "") or None, allow_transfer=bool(doc.allow_transfer),
        allowed_actions=actions, all_reports_approved=bool(_active(doc)) and all(r.directive_state == "Approved" for r in _active(doc)),
        transfer_choices=[r for r in people if r['id'] not in used] if "transfer" in actions else [],
        executors=[dict(person=_person(r.user), status=r.directive_state or "Pending",
            is_primary=r.user == doc.primary_executor,
            overdue=bool(doc.status == "Sent" and doc.due_date and getdate(doc.due_date) < getdate(nowdate())
                and r.directive_state not in ("Approved", "Transferred")))
            for r in doc.recipients if issuer or r.user == frappe.session.user],
        attachments=_files(COMMUNICATION, doc.name, "directive"), file_policy=_policy(),
        workflow_instance=doc.workflow_instance or "", incoming=doc.status!='Draft' and any(r.user==frappe.session.user for r in doc.recipients),
        sent=issuer, archived=doc.status == "Archived", open=doc.status == "Sent",
        overdue=bool(doc.status=='Sent' and doc.due_date and getdate(doc.due_date)<getdate(nowdate()) and any(r.directive_state!='Approved' for r in _active(doc))),
        needs_action=any(t.assigned_to == frappe.session.user and t.status == "Open" for t in _tasks(doc)),
        creation=str(doc.creation), sender=get_fullname(doc.sender))


def _mutation(action, payload, request_key, fn):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", str(request_key or "")):
        frappe.throw("شناسه درخواست معتبر نیست.")
    actor = frappe.session.user
    if actor == "Guest":
        frappe.throw("ورود به حساب لازم است.", frappe.PermissionError)
    # Serialize retries and actions by this actor; document locks serialize peers.
    frappe.db.sql("select name from `tabUser` where name=%s for update", actor)
    key = hashlib.sha256(f"{actor}:{request_key}".encode()).hexdigest()
    digest = hashlib.sha256(json.dumps([action, payload], sort_keys=True, default=str).encode()).hexdigest()
    if frappe.db.exists("ASOUD Directive Receipt", key):
        receipt = frappe.get_doc("ASOUD Directive Receipt", key)
        if receipt.actor != actor or receipt.payload_hash != digest:
            frappe.throw("شناسه تکراری با اطلاعات متفاوت ارسال شده است.")
        _get(receipt.directive, payload["company"])
        return success(json.loads(receipt.result_json))
    with service_write():
        result, doc = fn()
        frappe.get_doc(dict(doctype="ASOUD Directive Receipt", request_key=key, actor=actor,
            directive=doc.name, payload_hash=digest, result_json=json.dumps(result, default=str))).insert(ignore_permissions=True)
    return success(result)


def _audit(doc, action, comment="", task=None):
    if doc.workflow_instance:
        frappe.get_doc(dict(doctype="ASOUD Workflow Activity", workflow_instance=doc.workflow_instance,
            workflow_task=task, actor=frappe.session.user, action=action, comment=comment,
            created_on=now_datetime())).insert(ignore_permissions=True)
    else:
        doc.add_comment("Info", text=action)


def _notify(doc, user, title):
    frappe.get_doc(dict(doctype="Notification Log", for_user=user, from_user=frappe.session.user,
        subject=title[:140], document_type="ASOUD Workflow Instance", document_name=doc.workflow_instance,
        type="Alert")).insert(ignore_permissions=True)


def _stage(doc, kind):
    return frappe.db.get_value("ASOUD Workflow Stage", {"workflow_definition":
        frappe.db.get_value("ASOUD Workflow Instance", doc.workflow_instance, "workflow_definition"),
        "stage_subtype": kind}, "name")


def _new_task(doc, user, kind, subject_task=None):
    task = frappe.get_doc(dict(doctype="ASOUD Workflow Task", workflow_instance=doc.workflow_instance,
        workflow_stage=_stage(doc, kind), task_title=f"{ {'Report':'گزارش دستور','Review':'بررسی گزارش','Close':'تأیید نهایی دستور'}[kind]}: {doc.subject}"[:140],
        assigned_to=user, status="Open", assigned_on=now_datetime(),
        due_on=f"{doc.due_date} 23:59:59" if doc.due_date else None,
        directive_kind=kind, directive_subject_task=subject_task)).insert(ignore_permissions=True)
    _notify(doc, user, task.task_title)
    _audit(doc, 'تخصیص وظیفه', task=task.name)
    return task


def _finish(task, action, response=None, comment=""):
    task.status = "Completed"
    task.action, task.comment = action, comment
    task.completed_on = now_datetime()
    if response is not None:
        task.response_json = json.dumps(response, ensure_ascii=False)
    task.save(ignore_permissions=True)


def _open_task(doc, user, kind):
    name = frappe.db.get_value("ASOUD Workflow Task", {"workflow_instance": doc.workflow_instance,
        "assigned_to": user, "directive_kind": kind, "status": "Open"}, "name")
    if not name:
        frappe.throw("اقدام باز برای این کاربر وجود ندارد.")
    return frappe.get_doc("ASOUD Workflow Task", name, for_update=True)


def _bind(doc, ids, task=None):
    ids = list(dict.fromkeys(ids or []))
    policy = _policy()
    if policy['max_count'] and len(ids) > policy['max_count']:
        frappe.throw("تعداد پیوست‌ها بیش از حد مجاز است.")
    for name in ids:
        f = frappe.get_doc("File", name, for_update=True)
        if not f.is_private or f.attached_to_doctype != COMMUNICATION or f.attached_to_name != doc.name:
            frappe.throw("پیوست متعلق به این دستور نیست.", frappe.PermissionError)
        if f.attached_to_field != "directive" and f.owner != frappe.session.user:
            frappe.throw("پیوست متعلق به شما نیست.", frappe.PermissionError)
        if task and f.attached_to_field == "directive":
            frappe.throw("پیوست اصلی دستور قابل انتقال به گزارش نیست.")
        f.attached_to_doctype = "ASOUD Workflow Task" if task else COMMUNICATION
        f.attached_to_name = task.name if task else doc.name
        f.attached_to_field = "directive_report" if task else "directive"
        f.save(ignore_permissions=True)
    if not task:
        # Remove from the form, not from storage: pending files remain owner-only.
        for old in _files(COMMUNICATION, doc.name, "directive"):
            if old['id'] not in ids:
                f = frappe.get_doc("File", old['id'])
                f.attached_to_field = "directive_pending"
                f.save(ignore_permissions=True)


@frappe.whitelist()
def options(company):
    _employee(company)
    people = _people(company)
    return success(dict(people=people, priorities=[dict(value=value, label=label) for value,label in
        [("Medium","عادی"),("High","مهم"),("Urgent","فوری")]],
        allowed_actions=["save_draft","issue"] if people else [], today=nowdate(), file_policy=_policy()))


@frappe.whitelist()
def get_directive(company, directive):
    return success(_view(_get(directive, company)))


@frappe.whitelist()
def list_directives(company, start=0, page_length=100):
    _employee(company)
    # get_list applies both DocType and row-level permissions.
    names = frappe.get_list(COMMUNICATION, filters={"company":company, "communication_type":"Directive"},
        pluck="name", order_by="creation desc, name desc", limit_start=max(0,int(start)), limit_page_length=min(100,max(1,int(page_length))))
    return success(dict(items=[_view(_get(n, company)) for n in names],
        next_cursor=str(int(start)+len(names)) if len(names)==min(100,max(1,int(page_length))) else None))


@frappe.whitelist(methods=["POST"])
def save_draft(company, payload, request_key):
    data = _data(payload)
    def run():
        _employee(company)
        doc = _get(data['id'], company, True) if data.get('id') else frappe.new_doc(COMMUNICATION)
        if not doc.is_new() and (doc.sender != frappe.session.user or doc.status != "Draft"):
            frappe.throw("ویرایش دستور صادرشده مجاز نیست.", frappe.PermissionError)
        if not doc.is_new() and int(data.get('version', -1)) != doc.directive_version:
            frappe.throw("پیش‌نویس تغییر کرده است؛ دوباره دریافت کنید.")
        available = {p['id'] for p in _people(company)}
        users = list(dict.fromkeys(data.get('executor_ids') or []))
        if not available or set(users)-available:
            frappe.throw("مجریان باید از زیرمجموعه فعال و مجاز باشند.", frappe.PermissionError)
        subject = str(data.get('subject') or '').strip()
        if len(subject)>200:
            frappe.throw("موضوع حداکثر ۲۰۰ نویسه است.")
        if data.get('priority','Medium') not in ('Medium','High','Urgent'):
            frappe.throw("اولویت معتبر نیست.")
        primary = data.get('primary_id') or None
        if primary and primary not in users:
            frappe.throw("مسئول اصلی باید از مجریان باشد.")
        doc.company, doc.sender, doc.communication_type = company, frappe.session.user, "Directive"
        doc.subject, doc.content = subject, str(data.get('body') or '').strip()
        doc.priority, doc.status = data.get('priority','Medium'), 'Draft'
        doc.due_date = getdate(data['due_date']) if data.get('due_date') else None
        doc.primary_executor, doc.allow_transfer = primary, bool(data.get('allow_transfer'))
        doc.directive_version = (doc.directive_version or 0)+1
        doc.set('recipients', [dict(user=u,recipient_type='To',directive_state='Pending') for u in users])
        doc.flags.ignore_mandatory = True  # Only drafts may be incomplete.
        doc.save(ignore_permissions=True)
        _bind(doc, data.get('attachment_ids',[]))
        _audit(doc,'ذخیره پیش‌نویس')
        return dict(id=doc.name,version=doc.directive_version), doc
    return _mutation('save_draft',dict(company=company,payload=data),request_key,run)


@frappe.whitelist(methods=["POST"])
def issue(company, directive, request_key):
    def run():
        doc = _get(directive,company,True)
        if doc.sender != frappe.session.user or doc.status != 'Draft':
            frappe.throw("فقط صادرکننده می‌تواند پیش‌نویس را ابلاغ کند.",frappe.PermissionError)
        users = [r.user for r in doc.recipients]
        if not (doc.subject or '').strip() or not (doc.content or '').strip() or not users or doc.primary_executor not in users:
            frappe.throw("موضوع، شرح، مجریان و مسئول اصلی الزامی‌اند.")
        if set(users)-{p['id'] for p in _people(doc.company)} or doc.sender in users:
            frappe.throw("مجریان دیگر در دامنه مجاز نیستند.",frappe.PermissionError)
        if not doc.due_date or getdate(doc.due_date)<getdate(nowdate()):
            frappe.throw("مهلت معتبر و غیرگذشته لازم است.")
        # One immutable adapter definition per directive; no published-definition mutation.
        definition = frappe.get_doc(dict(doctype='ASOUD Workflow Definition',
            workflow_code=ADAPTER_PREFIX+doc.name, workflow_title='دستور سازمانی',
            company=doc.company,module_key='HR',creation_mode='Custom',target_doctype=COMMUNICATION,
            status='Inactive',readiness_status='Pending',pending_reason='Protected directive adapter',
            show_in_request_list=0,allow_user_submission=0)).insert(ignore_permissions=True)
        for i,kind in enumerate(['Report','Review','Close']):
            frappe.get_doc(dict(doctype='ASOUD Workflow Stage',workflow_definition=definition.name,
                stage_key=definition.name+'-'+kind,stage_type='Approval' if kind!='Report' else 'User Task',
                stage_subtype=kind,stage_title=kind,sequence_no=i+1,config_json='{}')).insert(ignore_permissions=True)
        instance = frappe.get_doc(dict(doctype='ASOUD Workflow Instance',workflow_definition=definition.name,
            subject=doc.subject[:140],reference_doctype=COMMUNICATION,reference_name=doc.name,
            status='Running',started_by=doc.sender,started_on=now_datetime())).insert(ignore_permissions=True)
        doc.workflow_instance,doc.issued_on,doc.status=instance.name,now_datetime(),'Sent'
        for row in doc.recipients:
            row.directive_state,row.assigned_on='Pending',now_datetime()
        doc.directive_version+=1
        doc.save(ignore_permissions=True)
        for user in users:
            _new_task(doc,user,'Report')
        _audit(doc,'ابلاغ دستور')
        return dict(id=doc.name),doc
    return _mutation('issue',dict(company=company,directive=directive),request_key,run)


@frappe.whitelist(methods=["POST"])
def report(company,directive,payload,request_key):
    data=_data(payload)
    def run():
        doc=_get(directive,company,True)
        if 'report' not in _actions(doc):
            frappe.throw('ثبت گزارش در این وضعیت مجاز نیست.',frappe.PermissionError)
        done=getdate(data.get('done_date')) if data.get('done_date') else None
        body=str(data.get('body') or '').strip()
        if not body or not done or done<getdate(doc.issued_on) or done>getdate(nowdate()):
            frappe.throw('شرح و تاریخ انجام بین تاریخ صدور و امروز لازم است.')
        task=_open_task(doc,frappe.session.user,'Report')
        version=1+sum(t.directive_kind=='Report' and t.assigned_to==frappe.session.user and t.action=='Report' for t in _tasks(doc))
        _bind(doc,data.get('attachment_ids',[]),task)
        _finish(task,'Report',dict(body=body,done_date=str(done),version=version))
        _own(doc).directive_state='Awaiting Review'
        doc.save(ignore_permissions=True)
        _new_task(doc,doc.sender,'Review',task.name)
        _audit(doc,'ارسال گزارش',task=task.name)
        return dict(id=doc.name),doc
    return _mutation('report',dict(company=company,directive=directive,payload=data),request_key,run)


@frappe.whitelist(methods=["POST"])
def review(company,directive,report_id,approve,reason,request_key):
    approved=str(approve).lower() in ('1','true')
    def run():
        doc=_get(directive,company,True)
        report_doc=frappe.get_doc('ASOUD Workflow Task',report_id)
        if doc.sender!=frappe.session.user or doc.status!='Sent' or report_doc.workflow_instance!=doc.workflow_instance or report_doc.action!='Report' or report_doc.assigned_to==doc.sender:
            frappe.throw('اجازه بررسی این گزارش را ندارید.',frappe.PermissionError)
        name=frappe.db.get_value('ASOUD Workflow Task',dict(workflow_instance=doc.workflow_instance,
            directive_kind='Review',directive_subject_task=report_id,status='Open',assigned_to=doc.sender),'name')
        if not name or (not approved and not str(reason or '').strip()):
            frappe.throw('گزارش بررسی شده یا دلیل اصلاح وارد نشده است.')
        task=frappe.get_doc('ASOUD Workflow Task',name,for_update=True)
        _finish(task,'Approve' if approved else 'Return',comment=str(reason or '').strip())
        row=next((r for r in _active(doc) if r.user==report_doc.assigned_to),None)
        if not row or row.directive_state!='Awaiting Review':
            frappe.throw('مسئول گزارش یا وضعیت تغییر کرده است.')
        row.directive_state='Approved' if approved else 'Returned'
        doc.save(ignore_permissions=True)
        if not approved:
            _new_task(doc,row.user,'Report')
        elif all(r.directive_state=='Approved' for r in _active(doc)):
            _new_task(doc,doc.sender,'Close')
        _notify(doc,row.user,'تأیید گزارش' if approved else 'درخواست اصلاح گزارش')
        _audit(doc,'تأیید گزارش' if approved else 'درخواست اصلاح',str(reason or ''),report_id)
        return dict(id=doc.name),doc
    return _mutation('review',dict(company=company,directive=directive,report_id=report_id,approve=approved,reason=reason),request_key,run)


@frappe.whitelist(methods=["POST"])
def transfer(company,directive,recipient_id,reason,request_key,executor_id=None):
    def run():
        doc=_get(directive,company,True)
        source=executor_id if doc.sender==frappe.session.user else frappe.session.user
        row=next((r for r in _active(doc) if r.user==source),None)
        available={p['id'] for p in _people(doc.company,_employee(doc.company,doc.sender).name)}
        if 'transfer' not in _actions(doc) or not row or row.directive_state not in ('Pending','Returned') or not str(reason or '').strip():
            frappe.throw('ارجاع در این وضعیت مجاز نیست یا دلیل وارد نشده است.',frappe.PermissionError)
        if recipient_id not in available or recipient_id in {r.user for r in doc.recipients}|{doc.sender,frappe.session.user}:
            frappe.throw('گیرنده غیرمجاز یا تکراری است؛ چرخه ارجاع مجاز نیست.')
        task=_open_task(doc,source,'Report')
        _finish(task,'Transferred',comment=str(reason).strip())
        row.directive_state,row.transferred_to='Transferred',recipient_id
        doc.append('recipients',dict(user=recipient_id,recipient_type='To',directive_state='Pending',assigned_on=now_datetime()))
        if doc.primary_executor==source:
            doc.primary_executor=recipient_id
        doc.save(ignore_permissions=True)
        _new_task(doc,recipient_id,'Report')
        _audit(doc,'انتقال مسئولیت',f'{source} → {recipient_id}: {reason}',task.name)
        return dict(id=doc.name),doc
    return _mutation('transfer',dict(company=company,directive=directive,recipient_id=recipient_id,reason=reason,executor_id=executor_id),request_key,run)


@frappe.whitelist(methods=["POST"])
def close(company,directive,request_key):
    def run():
        doc=_get(directive,company,True)
        if 'close' not in _actions(doc):
            frappe.throw('همه گزارش‌ها باید تأیید شوند و اختتام فقط با صادرکننده است.',frappe.PermissionError)
        task=_open_task(doc,doc.sender,'Close')
        _finish(task,'Close')
        doc.status,doc.closed_on='Closed',now_datetime()
        doc.save(ignore_permissions=True)
        instance=frappe.get_doc('ASOUD Workflow Instance',doc.workflow_instance,for_update=True)
        instance.status,instance.completed_on='Completed',now_datetime()
        instance.save(ignore_permissions=True)
        _audit(doc,'مختومه کردن دستور',task=task.name)
        for row in _active(doc):
            _notify(doc,row.user,'دستور مختومه شد')
        return dict(id=doc.name),doc
    return _mutation('close',dict(company=company,directive=directive),request_key,run)


@frappe.whitelist()
def reports(company,directive,start=0):
    doc=_get(directive,company)
    tasks=_tasks(doc)
    rows=[]
    for task in tasks:
        if task.directive_kind!='Report' or task.action!='Report' or (doc.sender!=frappe.session.user and task.assigned_to!=frappe.session.user):
            continue
        review_task=next((t for t in tasks if t.directive_kind=='Review' and t.directive_subject_task==task.name),None)
        data=json.loads(task.response_json or '{}')
        rows.append(dict(id=task.name,author=_person(task.assigned_to),body=data.get('body',''),
            done_date=data.get('done_date'),created_at=str(task.completed_on),version=data.get('version',1),
            status='Awaiting Review' if not review_task or review_task.status=='Open' else ('Approved' if review_task.action=='Approve' else 'Returned'),
            review_note=review_task.comment if review_task else '',
            allowed_actions=['approve','request_changes'] if review_task and review_task.status=='Open' and doc.status=='Sent' and doc.sender==frappe.session.user and task.assigned_to!=doc.sender else [],
            attachments=_files('ASOUD Workflow Task',task.name)))
    offset=max(0,int(start))
    return success(dict(items=rows[offset:offset+50],next_cursor=str(offset+50) if len(rows)>offset+50 else None))


@frappe.whitelist()
def history(company,directive,start=0):
    doc=_get(directive,company)
    filters={'workflow_instance':doc.workflow_instance or ''}
    related=[]
    if doc.sender!=frappe.session.user:
        own_tasks=[t.name for t in _tasks(doc) if t.assigned_to==frappe.session.user]
        related=[['actor','=',frappe.session.user],['workflow_task','in',own_tasks or ['']]]
    offset=max(0,int(start))
    rows=frappe.get_all('ASOUD Workflow Activity',filters=filters,or_filters=related or None,
        fields=['name','action','actor','created_on','comment','workflow_task'],order_by='created_on desc, name desc',limit_page_length=0)
    entries=[dict(action=r.action,actor=get_fullname(r.actor),created_at=str(r.created_on),description=r.comment or '',reference=r.workflow_task or '',sort_id=r.name) for r in rows]
    if doc.sender==frappe.session.user:
        comments=frappe.get_all('Comment',filters={'reference_doctype':COMMUNICATION,'reference_name':doc.name,'comment_type':'Info'},
            fields=['name','owner','creation','content'],limit_page_length=0)
        entries += [dict(action='ذخیره پیش‌نویس',actor=get_fullname(r.owner),created_at=str(r.creation),description='',reference=doc.name,sort_id=r.name) for r in comments]
    entries.sort(key=lambda r:(r['created_at'],r['sort_id']),reverse=True)
    return success(dict(items=entries[offset:offset+50],next_cursor=str(offset+50) if len(entries)>offset+50 else None))


@frappe.whitelist(methods=["POST"])
def upload_attachment(company,directive,filename,content_base64,request_key):
    def run():
        doc=_get(directive,company,True)
        if not set(_actions(doc)).intersection({'save_draft','report'}):
            frappe.throw('بارگذاری در این وضعیت مجاز نیست.',frappe.PermissionError)
        safe=Path(str(filename).replace('\\','/')).name
        policy=_policy()
        if Path(safe).suffix.lower() not in policy['extensions']:
            frappe.throw('نوع فایل مجاز نیست.')
        if len(content_base64)>policy['max_bytes']*4//3+4:
            frappe.throw('حجم فایل بیش از حد مجاز است.')
        try:
            content=base64.b64decode(content_base64,validate=True)
        except (ValueError,TypeError):
            frappe.throw('محتوای فایل معتبر نیست.')
        if not content or len(content)>policy['max_bytes']:
            frappe.throw('حجم فایل معتبر نیست.')
        f=frappe.get_doc(dict(doctype='File',file_name=safe,content=content,is_private=1,
            attached_to_doctype=COMMUNICATION,attached_to_name=doc.name,attached_to_field='directive_pending')).insert(ignore_permissions=True)
        return _file_row(f),doc
    return _mutation('upload',dict(company=company,directive=directive,filename=filename,
        content_hash=hashlib.sha256(content_base64.encode()).hexdigest()),request_key,run)


@frappe.whitelist()
def download_attachment(company,attachment):
    f=frappe.get_doc('File',attachment)
    from asoud_erp.services.directive_access import directive_for, file_permission
    doc=directive_for(f)
    if not doc or (company and doc.company!=company) or not file_permission(f,permission_type='read'):
        frappe.throw('اجازه دریافت فایل را ندارید.',frappe.PermissionError)
    _get(doc.name,company)
    content=f.get_content()
    if isinstance(content,str):
        content=content.encode('utf-8')
    return success(dict(filename=f.file_name,content_base64=base64.b64encode(content).decode()))


def notify_overdue(task):
    """Scheduler-only; the document lock also serializes report/transfer/close."""
    instance=frappe.get_doc('ASOUD Workflow Instance',task.workflow_instance)
    doc=frappe.get_doc(COMMUNICATION,instance.reference_name,for_update=True)
    task=frappe.get_doc('ASOUD Workflow Task',task.name,for_update=True)
    if doc.status!='Sent' or task.status!='Open' or task.escalated_on:
        return
    with service_write():
        _notify(doc,task.assigned_to,'مهلت اقدام دستور گذشته است')
        task.escalated_on=now_datetime()
        task.save(ignore_permissions=True)
