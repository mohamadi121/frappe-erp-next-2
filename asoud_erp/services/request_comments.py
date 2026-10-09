"""Free comments on a request: standard Frappe `Comment` records, `comment_type = "Comment"`.

Approval comments stay in the workflow activity timeline; this thread is separate.
The text helper is pure; the rest needs frappe (imported lazily).
"""

from __future__ import annotations

import html
import re

MAX_COMMENT_LENGTH = 2000
REQUEST_DOCTYPE = "ASOUD Workflow Request"
_TAGS = re.compile(r"<[^>]*>")
_BLOCK_BREAKS = re.compile(r"(?i)</(?:p|div|li|h[1-6])>|<br\s*/?>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_comment_text(text) -> str:
    """Plain text of a comment: tags stripped, entities decoded, whitespace trimmed.

    Returns "" for empty input; raises ValueError when longer than MAX_COMMENT_LENGTH.
    """
    if not isinstance(text, str):
        return ""
    plain = html.unescape(_TAGS.sub("", _BLOCK_BREAKS.sub("\n", text)))
    plain = _BLANK_LINES.sub("\n\n", "\n".join(_SPACES.sub(" ", line).strip() for line in plain.split("\n")))
    plain = plain.strip()
    if len(plain) > MAX_COMMENT_LENGTH:
        raise ValueError("Comment is too long")
    return plain


def _author_names(users: set[str], company: str) -> dict[str, str]:
    import frappe
    from frappe.utils import get_fullname

    names: dict[str, str] = {}
    if users:
        for row in frappe.get_all(
            "Employee", filters={"user_id": ["in", list(users)], "status": "Active"},
            fields=["user_id", "employee_name", "company"], limit_page_length=0):
            if row.user_id not in names or row.company == company:
                names[row.user_id] = row.employee_name
    return {user: names.get(user) or get_fullname(user) for user in users}


def _serialize(rows, company: str, user: str) -> list[dict]:
    authors = {row["comment_email"] or row["owner"] for row in rows}
    names = _author_names(authors, company)
    return [{
        "name": row["name"], "content": clean_comment_text(row["content"] or ""),
        "author": row["comment_email"] or row["owner"],
        "author_name": names[row["comment_email"] or row["owner"]],
        "creation": str(row["creation"] or ""),
        "is_mine": (row["comment_email"] or row["owner"]) == user,
    } for row in rows]


def _filters(request_name: str) -> dict:
    return {"comment_type": "Comment", "reference_doctype": REQUEST_DOCTYPE, "reference_name": request_name}


def list_comments(request, limit_start: int = 0, limit_page_length: int = 50) -> tuple[list[dict], int]:
    """`(comments oldest first, total)` of a request; the caller has checked permission."""
    import frappe

    rows = frappe.get_all(
        "Comment", filters=_filters(request.name),
        fields=["name", "content", "comment_email", "owner", "creation"],
        order_by="creation asc, name asc", limit_start=limit_start, limit_page_length=limit_page_length)
    total = frappe.db.count("Comment", _filters(request.name))
    return _serialize(rows, request.company, frappe.session.user), total


def count_comments(request_name: str) -> int:
    import frappe

    return frappe.db.count("Comment", _filters(request_name))


def add_comment(request, content) -> dict:
    """Adds a comment as the session user and notifies the owner and current assignees."""
    import frappe
    from frappe import _

    from asoud_erp.services.request_templates.base import throw_error

    try:
        text = clean_comment_text(content)
    except ValueError:
        throw_error("EMPTY_COMMENT", "متن نظر حداکثر ۲۰۰۰ نویسه می‌تواند باشد.")
    if not text:
        throw_error("EMPTY_COMMENT")
    comment = request.add_comment("Comment", text)
    _notify(request, _("New comment on request {0}").format(request.name), text)
    row = frappe.db.get_value("Comment", comment.name, ["name", "content", "comment_email", "owner", "creation"],
                              as_dict=True)
    return _serialize([row], request.company, frappe.session.user)[0]


def _notify(request, subject: str, message: str) -> None:
    """In-app Notification Log for the owner and the open task assignees, never the author."""
    import frappe

    recipients = [request.owner]
    document_type, document_name = REQUEST_DOCTYPE, request.name
    if request.workflow_instance:
        recipients += frappe.get_all(
            "ASOUD Workflow Task", filters={"workflow_instance": request.workflow_instance, "status": "Open"},
            pluck="assigned_to", limit_page_length=0)
        # The app's notification list shows workflow notifications by instance.
        document_type, document_name = "ASOUD Workflow Instance", request.workflow_instance
    for user in dict.fromkeys(recipients):
        if not user or user in {"Guest", frappe.session.user}:
            continue
        # Same in-app notification the workflow runtime creates; recipients are request participants.
        frappe.get_doc({
            "doctype": "Notification Log", "subject": subject, "for_user": user,
            "from_user": frappe.session.user, "type": "Alert", "document_type": document_type,
            "document_name": document_name, "email_content": message[:500], "read": 0,
        }).insert(ignore_permissions=True)
