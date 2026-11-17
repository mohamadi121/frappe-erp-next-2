"""The approved confidential-data policy for workflow participants (PA-055).

One pure function decides how much of a request a user may see:

- ``FULL``   — the request owner, a privileged manager with company access, or the current
  assignee (a task still ``Open`` for them, including an unclaimed shared-claim task while it
  is Open). They read the request and its confidential values and files.
- ``MASKED`` — a previous assignee who acted (a task they acted on, or they appear as the
  actor of a decision activity on the instance). They read the request and their own action
  history, but confidential values are masked and confidential files are hidden.
- ``NONE``   — everyone else, including a user whose shared-claim task was ``Cancelled``
  without them acting, and a holder reassigned away who never acted.

Reassignment rewrites ``task.assigned_to`` in place, so a reassigned-away holder is simply a
previous assignee: ``MASKED`` only if they acted, else ``NONE``. Claiming a shared task alone
is not a decision; the caller treats a Claim-only history as "did not act" (see the report).
"""

FULL = "FULL"
MASKED = "MASKED"
NONE = "NONE"


def classify(is_owner, privileged_with_company, task_rows, acted_in_activity) -> str:
    """The access level of one user for one request.

    ``task_rows`` are the request's workflow tasks still assigned to the user, each a mapping
    with ``status`` (``Open``/``Completed``/``Cancelled``/...) and ``acted`` (whether the user
    made a decision on that task). ``acted_in_activity`` is whether the user is the actor of a
    decision activity on the instance (a mere Claim does not count).
    """
    rows = task_rows or []
    if is_owner or privileged_with_company or any(
            str(row.get("status") or "") == "Open" for row in rows):
        return FULL
    if any(row.get("acted") for row in rows) or acted_in_activity:
        return MASKED
    return NONE
