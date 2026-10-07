"""Durable automatic actions; database effects, links and receipt commit atomically.

No executor is whitelisted. Notification email is queued, never sent inline.
"""

import base64
import hashlib
import json
from html import escape
from pathlib import PurePosixPath

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime, nowdate

from asoud_erp.services.automatic_action_metadata import (
    RECORDS,
    identity,
    record_fields,
    service_user,
    validate_config,
)
from asoud_erp.services.automatic_action_policy import VARIABLE, calculate, resolve, retry_delay
from asoud_erp.services.document_templates import build_document

RECEIPT = "ASOUD Action Execution"


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _company(instance):
    return frappe.db.get_value("ASOUD Workflow Definition", instance.workflow_definition, "company")


def _record(doctype, name, company):
    if doctype not in RECORDS:
        raise frappe.PermissionError("Record type is not allowlisted")
    doc = frappe.get_doc(doctype, name)
    if doc.company != company:
        raise frappe.PermissionError("Record belongs to another company")
    doc.check_permission("read")
    return doc


def _values(doc):
    values = {field["key"]: doc.get(field["key"]) for field in record_fields(doc.doctype)}
    if doc.doctype == "ASOUD Workflow Request":
        values.update(json.loads(doc.values_json or "{}"))
    return values


def _context(instance, company):
    current = _record(instance.reference_doctype, instance.reference_name, company)
    stages = {}
    tasks = frappe.get_all(
        "ASOUD Workflow Task",
        filters={"workflow_instance": instance.name, "status": "Completed"},
        fields=["workflow_stage", "response_json"],
        order_by="completed_on asc",
    )
    for task in tasks:
        stages[task.workflow_stage] = json.loads(task.response_json or "{}")
    receipts = frappe.get_all(
        RECEIPT,
        filters={"workflow_instance": instance.name, "status": "Succeeded"},
        fields=["workflow_stage", "result_json"],
        order_by="completed_on asc",
    )
    records = {}
    for row in receipts:
        result = json.loads(row.result_json or "{}")
        if result.get("doctype") and result.get("name"):
            doc = _record(result["doctype"], result["name"], company)
            stages[row.workflow_stage] = result.get("values", _values(doc))
            records[row.workflow_stage] = doc
    return {
        "current": _values(current),
        "stages": stages,
        "records": records,
        "record": current,
        "system": {
            "today": nowdate(),
            "now": str(now_datetime()),
            "company": company,
            "initiator": instance.started_by,
        },
    }


def _target(op, context):
    target = op.get("target", {"source": "current"})
    if target["source"] == "current":
        return context["record"]
    doc = context["records"].get(target["stage"])
    if doc is None:
        raise ValueError("The target stage has no completed record output")
    return doc


def _mapping(mapping, context):
    return {key: value for key, entry in mapping.items() if (value := resolve(entry, context)) is not None}


def _update(doc, values, company):
    doc.check_permission("write")
    if doc.doctype == "ASOUD Workflow Request":
        from asoud_erp.api.v1.workflow_request import _fields
        from asoud_erp.services.request_link_values import validate_link_values
        from asoud_erp.services.workflow_response import normalize_form_response

        fields = _fields(frappe.get_doc("ASOUD Workflow Definition", doc.workflow_definition))
        values = dict(values)
        if "subject" in values:
            subject = values.pop("subject")
            if not isinstance(subject, str) or not 3 <= len(subject.strip()) <= 140:
                raise ValueError("Request subject must contain 3..140 characters")
            doc.subject = subject.strip()
        merged = {**json.loads(doc.values_json or "{}"), **values}
        normalized = normalize_form_response(fields, merged)
        validate_link_values(fields, normalized, company)
        doc.values_json = _json(normalized)
    else:
        doc.update(values)
    doc.save()


def _link(original, created, relation, execution):
    from frappe.utils import get_link_to_form

    original.check_permission("read")
    created.check_permission("read")
    content = (
        f"{escape(relation)}: {get_link_to_form(created.doctype, created.name)} "
        f"(automatic execution {escape(execution)})"
    )
    return original.add_comment("Info", content).name


def _request_attachments(values, definition, instance, execution):
    from asoud_erp.api.v1.workflow_request import _fields
    from asoud_erp.services.workflow_response import map_attachment_values

    attachments, copied = [], {}

    def copy(value):
        if value in copied:
            return copied[value]
        names = frappe.get_all(
            "File", filters={"file_url": value, "is_private": 1}, pluck="name", limit_page_length=2
        )
        if len(names) != 1:
            raise ValueError("Attachment must resolve to exactly one private file")
        file = frappe.get_doc("File", names[0])
        file.check_permission("read")
        same_record = (
            file.attached_to_doctype == instance.reference_doctype
            and file.attached_to_name == instance.reference_name
        )
        same_task = (
            file.attached_to_doctype == "ASOUD Workflow Task"
            and frappe.db.get_value("ASOUD Workflow Task", file.attached_to_name, "workflow_instance")
            == instance.name
        )
        if not (same_record or same_task):
            raise frappe.PermissionError("Attachment does not belong to this workflow's source or tasks")
        if (
            not str(file.file_url).startswith("/private/files/")
            or int(file.file_size or 0) > 10 * 1024 * 1024
        ):
            raise ValueError("Only local private attachments up to 10 MB may be copied")
        content = file.get_content()
        if isinstance(content, str):
            content = content.encode()
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Attachment exceeds 10 MB")
        filename = f"auto-{execution[:12]}-{len(attachments)}{PurePosixPath(file.file_name).suffix}"
        attachments.append({"filename": filename, "content_base64": base64.b64encode(content).decode()})
        copied[value] = f"attachment:{filename}"
        return copied[value]

    fields = _fields(frappe.get_doc("ASOUD Workflow Definition", definition))
    return map_attachment_values(fields, values, copy), attachments


def _notify(op, context, instance):
    from asoud_erp.services.request_access import company_access

    def replacement(match):
        value = context["current"].get(match.group(1))
        if value is None or isinstance(value, (list, dict)):
            raise ValueError(f"Missing message variable: {match.group(1)}")
        return str(value)

    message = VARIABLE.sub(replacement, op["message"])
    results = []
    recipients = set(instance.started_by if user == "initiator" else user for user in op["recipients"])
    for user in sorted(recipients):
        for channel in op["channels"]:
            frappe.db.savepoint("automatic_notification")
            try:
                if not frappe.db.get_value("User", user, "enabled") or not company_access(
                    user=user, company=_company(instance)
                ):
                    raise frappe.PermissionError("Recipient cannot access the workflow company")
                if not frappe.has_permission(context["record"].doctype, "read", context["record"], user=user):
                    raise frappe.PermissionError("Recipient cannot access the source record")
                if channel == "in_app":
                    doc = frappe.get_doc(
                        {
                            "doctype": "Notification Log",
                            "type": "Alert",
                            "for_user": user,
                            "from_user": frappe.session.user,
                            "subject": escape(message[:140]),
                            "document_type": instance.reference_doctype,
                            "document_name": instance.reference_name,
                            "email_content": escape(message),
                        }
                    )
                    doc.insert(
                        ignore_permissions=True
                    )  # Native delivery, not business-document permission bypass.
                    results.append(
                        {"recipient": user, "channel": channel, "status": "created", "reference": doc.name}
                    )
                else:
                    if not frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
                        raise ValueError("No default outgoing email account is configured")
                    email = frappe.db.get_value("User", user, "email")
                    queue = frappe.sendmail(
                        recipients=[email],
                        subject=message[:140],
                        message=escape(message),
                        reference_doctype=instance.reference_doctype,
                        reference_name=instance.reference_name,
                        delayed=True,
                        now=False,
                    )
                    if not getattr(queue, "name", None):
                        raise ValueError("Email was not queued; check recipients and outgoing email settings")
                    results.append(
                        {
                            "recipient": user,
                            "channel": channel,
                            "status": "queued",
                            "reference": getattr(queue, "name", None),
                        }
                    )
            except Exception as error:
                frappe.db.rollback(save_point="automatic_notification")
                results.append(
                    {
                        "recipient": user,
                        "channel": channel,
                        "status": "failed",
                        "error": type(error).__name__,
                        "message": str(error)[:300],
                    }
                )
    return {"notifications": results}


def perform(receipt, instance, config, company):
    context = _context(instance, company)
    op, kind = config["operation"], config["action_type"]
    if kind == "Send Notification":
        return _notify(op, context, instance)
    if kind == "Create Request":
        from asoud_erp.api.v1.workflow_request import create_request

        values = _mapping(op["mapping"], context)
        if not frappe.has_permission("ASOUD Workflow Request", "create"):
            raise frappe.PermissionError("Service user cannot create requests")
        subject = values.pop("subject")
        values, attachments = _request_attachments(values, op["request_type"], instance, receipt.name)
        response = create_request(
            company=company,
            workflow_definition=op["request_type"],
            subject=subject,
            request_id=f"auto-{receipt.name}",
            values=values,
            attachments=attachments,
        )
        doc = _record("ASOUD Workflow Request", response["data"]["name"], company)
    elif kind == "Create Document":
        from asoud_erp.api.v1.document_templates import _validate_links
        from asoud_erp.services.request_link_values import validate_link_values

        values = _mapping(op["mapping"], context)
        _validate_links(
            {k: {"source": "fixed", "value": v} for k, v in values.items()}, op["doctype"], company
        )
        from asoud_erp.services.document_templates import LINK_TARGETS, TARGET_FIELDS

        for field in TARGET_FIELDS[op["doctype"]]:
            linked = values.get(field["key"])
            if linked and field["type"] in LINK_TARGETS:
                if not frappe.has_permission(field["type"], "read", linked):
                    raise frappe.PermissionError("Service user cannot read a mapped linked record")
                if field["type"] == "Account":
                    currency = frappe.db.get_value("Account", linked, "account_currency")
                    company_currency = frappe.db.get_value("Company", company, "default_currency")
                    if currency and currency != company_currency:
                        raise ValueError("Automatic journal entries require accounts in the company currency")
        if op["doctype"] == "Material Request":
            validate_link_values([{"key": "items", "type": "Item Table"}], values, company)
        doc = frappe.get_doc(build_document(op["doctype"], values, company))
        doc.insert()
        if op["initial_state"] == "Submitted":
            doc.submit()
    else:
        doc = _target(op, context)
        if kind == "Update Fields":
            _update(doc, _mapping(op["mapping"], context), company)
        elif kind == "Calculate Value":
            _update(
                doc,
                {
                    op["field"]: calculate(
                        op["method"], _mapping(op["inputs"], context), op.get("formula", "")
                    )
                },
                company,
            )
        elif kind == "Change Status":
            from frappe.model.workflow import apply_workflow, get_transitions

            if op["transition"] not in {row.action for row in get_transitions(doc)}:
                raise frappe.PermissionError(
                    "Transition is not allowed from the current state for the service user"
                )
            doc = apply_workflow(doc.as_json(), op["transition"])
            if doc is None:
                raise ValueError("Background submission is unsupported for automatic status changes")
        else:
            value = resolve(op["lookup"], context)
            if value is None:
                raise ValueError("Record lookup cannot use an empty value")
            matches = frappe.get_all(
                op["doctype"],
                filters={"company": company, op["lookup_field"]: value},
                pluck="name",
                limit_page_length=2,
            )
            if len(matches) > 1:
                raise ValueError("Record lookup is ambiguous")
            if not matches:
                if op["missing"] == "skip":
                    return {"skipped": True, "reason": "No matching record"}
                raise ValueError("No matching record")
            linked = _record(op["doctype"], matches[0], company)
            comment = _link(doc, linked, op["relationship"], receipt.name)
            return {
                "doctype": doc.doctype,
                "name": doc.name,
                "linked_doctype": linked.doctype,
                "linked_name": linked.name,
                "relationship": op["relationship"],
                "comment": comment,
            }
    result = {"doctype": doc.doctype, "name": doc.name, "values": _values(doc)}
    if kind.startswith("Create") and op["link_original"]:
        result["comment"] = _link(context["record"], doc, "related", receipt.name)
    return result


def _audit(receipt, instance, message):
    frappe.get_doc(
        {
            "doctype": "ASOUD Workflow Activity",
            "workflow_instance": instance.name,
            "workflow_stage": receipt.workflow_stage,
            "actor": receipt.service_user or frappe.session.user,
            "action": f"Automatic {receipt.status}",
            "created_on": now_datetime(),
            "comment": f"{receipt.name} | {receipt.action_type} | attempt {receipt.attempts} | {message}"[
                :1000
            ],
            "reference_doctype": RECEIPT,
            "reference_name": receipt.name,
        }
    ).insert(ignore_permissions=True)


def _finish(receipt, instance, success):
    from asoud_erp.api.v1.workflow_runtime import _activate_stage

    routes = json.loads(receipt.routes_json)
    target = routes.get("Success" if success else "Error")
    if target:
        stage = frappe.get_doc("ASOUD Workflow Stage", target)
        if stage.workflow_definition != instance.workflow_definition or (
            not success and stage.stage_type != "User Task"
        ):
            raise ValueError("Invalid automatic action route")
        _activate_stage(instance, stage, automatic_trigger=receipt.trigger_id)
    else:
        if success:
            raise ValueError("Automatic action has no success destination")
        instance.status = "Failed"
        instance.completed_on = now_datetime()
        instance.save(ignore_permissions=True)


def _final_failure(receipt, instance):
    frappe.db.savepoint("automatic_error_route")
    try:
        _finish(receipt, instance, False)
    except Exception:
        frappe.db.rollback(save_point="automatic_error_route")
        instance.reload()
        instance.status, instance.completed_on = "Failed", now_datetime()
        instance.save(ignore_permissions=True)
    if instance.status == "Failed":
        from asoud_erp.api.v1.workflow_runtime import _notify_user, _users_for_roles

        for user in _users_for_roles(["System Manager"]):
            frappe.db.savepoint("automatic_failure_notice")
            try:
                _notify_user(user, "Automatic action failed", instance, message=f"Execution: {receipt.name}")
            except Exception:
                frappe.db.rollback(save_point="automatic_failure_notice")


def schedule(instance, stage, config, trigger="start"):
    from asoud_erp.api.v1.workflow_runtime import _system_route

    frappe.get_doc("ASOUD Workflow Instance", instance.name, for_update=True)
    execution_id = hashlib.sha256(f"{instance.name}|{stage.name}|{trigger}".encode()).hexdigest()
    existing = frappe.db.get_value(RECEIPT, execution_id, "status")
    if existing:
        if existing in {"Pending", "Running", "Retry Pending"}:
            return
        raise ValueError(
            "Repeated automatic-stage activation; insert a human task before repeating this action"
        )
    instance.save(ignore_permissions=True)
    routes = {
        key: getattr(_system_route(instance, stage.name, key), "name", None) for key in ("Success", "Error")
    }
    receipt = frappe.get_doc(
        {
            "doctype": RECEIPT,
            "workflow_instance": instance.name,
            "workflow_stage": stage.name,
            "trigger_id": trigger,
            "status": "Pending",
            "action_type": config["action_type"],
            "config_json": _json(config),
            "routes_json": _json(routes),
            "next_attempt": now_datetime(),
        }
    )
    receipt.insert(ignore_permissions=True, set_name=execution_id)
    try:
        receipt.service_user = service_user(_company(instance))
    except frappe.PermissionError as error:
        receipt.status, receipt.error_code, receipt.error_message = (
            "Failed",
            "ServiceIdentityMissing",
            str(error),
        )
        receipt.completed_on = now_datetime()
        receipt.save(ignore_permissions=True)
        _audit(receipt, instance, str(error))
        instance.status, instance.completed_on = "Failed", now_datetime()
        instance.save(ignore_permissions=True)
        return
    receipt.save(ignore_permissions=True)
    _audit(receipt, instance, "Waiting for background worker")


def run(execution):
    receipt = frappe.get_doc(RECEIPT, execution, for_update=True)
    if receipt.status not in {"Pending", "Retry Pending"}:
        return
    if receipt.next_attempt and get_datetime(receipt.next_attempt) > now_datetime():
        return
    receipt.attempts = int(receipt.attempts or 0) + 1
    receipt.started_on = now_datetime()
    receipt.status = "Running"
    receipt.save(ignore_permissions=True)
    # Worker-only entry point. Persist the attempt before effects, so an OS kill
    # cannot reset the retry budget. Effects and successful receipt still commit together.
    frappe.db.commit()
    receipt = frappe.get_doc(RECEIPT, execution, for_update=True)
    if receipt.status != "Running":
        return
    instance = frappe.get_doc("ASOUD Workflow Instance", receipt.workflow_instance, for_update=True)
    if instance.status != "Running" or instance.current_stage != receipt.workflow_stage:
        receipt.status = "Cancelled"
        receipt.save(ignore_permissions=True)
        _audit(receipt, instance, "Instance no longer waits at this stage")
        return
    config = json.loads(receipt.config_json)
    try:
        with identity(_company(instance)) as user:
            receipt.service_user = user
            validate_config(instance.workflow_definition, receipt.workflow_stage, config)
            result = perform(receipt, instance, config, _company(instance))
        receipt.result_json = _json(result)
        channel_errors = any(row["status"] == "failed" for row in result.get("notifications", []))
        receipt.status = "Completed With Errors" if channel_errors else "Succeeded"
        receipt.error_code = receipt.error_message = None
        receipt.completed_on = now_datetime()
        receipt.save(ignore_permissions=True)
        _finish(receipt, instance, True)
    except Exception as error:
        # This is a dedicated worker transaction: full rollback also runs native
        # File cleanup and discards email/realtime after-commit callbacks.
        frappe.db.rollback()
        receipt = frappe.get_doc(RECEIPT, execution, for_update=True)
        if receipt.status != "Running":
            return
        instance = frappe.get_doc("ASOUD Workflow Instance", receipt.workflow_instance, for_update=True)
        from rq.timeouts import JobTimeoutException

        delay = retry_delay(
            config["execution"],
            receipt.attempts,
            transient=isinstance(error, (ConnectionError, TimeoutError, JobTimeoutException)),
        )
        receipt.result_json = None
        receipt.error_code, receipt.error_message = type(error).__name__, str(error)[:1000]
        receipt.status = "Retry Pending" if delay is not None else "Failed"
        receipt.next_attempt = add_to_date(now_datetime(), seconds=delay) if delay is not None else None
        receipt.completed_on = None if delay is not None else now_datetime()
        receipt.save(ignore_permissions=True)
        if delay is None:
            _final_failure(receipt, instance)
    _audit(receipt, instance, receipt.error_code or "Completed")


def dispatch():
    from frappe.utils import time_diff_in_seconds

    running = frappe.get_all(
        RECEIPT,
        filters={"status": "Running"},
        fields=["name", "config_json", "started_on"],
        limit_page_length=100,
    )
    for row in running:
        policy = json.loads(row.config_json)["execution"]
        if time_diff_in_seconds(now_datetime(), row.started_on) <= policy["timeout_seconds"] + 60:
            continue
        receipt = frappe.get_doc(RECEIPT, row.name, for_update=True)
        policy = json.loads(receipt.config_json)["execution"]
        if (
            receipt.status != "Running"
            or time_diff_in_seconds(now_datetime(), receipt.started_on) <= policy["timeout_seconds"] + 60
        ):
            continue
        instance = frappe.get_doc("ASOUD Workflow Instance", receipt.workflow_instance, for_update=True)
        delay = retry_delay(policy, receipt.attempts, transient=True)
        receipt.status = "Retry Pending" if delay is not None else "Failed"
        receipt.error_code, receipt.error_message = (
            "WorkerInterrupted",
            "Worker stopped before committing its result",
        )
        receipt.next_attempt = add_to_date(now_datetime(), seconds=delay) if delay is not None else None
        receipt.completed_on = None if delay is not None else now_datetime()
        receipt.save(ignore_permissions=True)
        if (
            delay is None
            and instance.status == "Running"
            and instance.current_stage == receipt.workflow_stage
        ):
            _final_failure(receipt, instance)
        _audit(receipt, instance, receipt.error_message)
    rows = frappe.get_all(
        RECEIPT,
        filters={"status": ["in", ["Pending", "Retry Pending"]], "next_attempt": ["<=", now_datetime()]},
        fields=["name", "config_json"],
        limit_page_length=100,
    )
    for row in rows:
        timeout = json.loads(row.config_json)["execution"]["timeout_seconds"]
        frappe.enqueue(
            "asoud_erp.services.automatic_action_runtime.run",
            execution=row.name,
            timeout=timeout,
            job_id=f"asoud-action-{row.name}",
            deduplicate=True,
            enqueue_after_commit=True,
        )
