"""Pure rules for choosing who receives a workflow task."""
from collections.abc import Callable


def approval_assignees(users: list[str], initiator: str, escalation_users: Callable[[], list[str]]) -> list[str]:
    """Approvers for an Approval stage; nobody approves their own request.

    The initiator is dropped from the list. When nobody else is left the escalation
    users (without the initiator) take over. When there is still nobody, fail with a
    clear reason instead of creating a task the initiator can never complete.
    """
    if initiator not in users:
        return users
    others = [user for user in users if user != initiator]
    if not others:
        others = [user for user in escalation_users() if user != initiator]
    if not others:
        raise ValueError('برای این مرحلهٔ تأیید، تأییدکننده‌ای غیر از درخواست‌دهنده پیدا نشد؛ '
                         'تأییدکننده یا نقش تصاعد مستقل تعریف کنید.')
    return others


DEFAULT_MAX_ASSIGNEES = 1000


def check_assignee_cap(users: list[str], conf: dict) -> None:
    """Reject only an absurd final list; one Open task is created per assignee.

    Apply it after company/form/reference authorisation, never to raw candidates.
    `asoud_workflow_max_assignees` in site config raises or lowers the limit.
    """
    limit = conf.get('asoud_workflow_max_assignees')
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        limit = DEFAULT_MAX_ASSIGNEES
    if len(users) > limit:
        raise ValueError('تعداد مسئولان مجاز این اقدام بیش از حد مجاز است؛ نقش یا واحد را محدودتر کنید.')
