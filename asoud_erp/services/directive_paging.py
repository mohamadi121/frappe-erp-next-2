"""Pure paging and batch-lookup helpers for directive and workflow list endpoints.

Frappe applies access filters in Python, after SQL LIMIT, so a database page can
hold fewer visible rows than it read. Cursors therefore depend on the raw page size
only; see `next_cursor`.
"""

HISTORY_PAGE = 50

# Every value is a named parameter. The branch limit is applied inside each UNION
# member, so the outer sort reads at most `offset + page + 1` rows per branch and
# each branch can walk `(workflow_instance, created_on)` in index order.
HISTORY_SQL = """
    SELECT * FROM (
      (SELECT a.name AS sort_id, a.action, a.actor, a.created_on AS created_at,
              a.comment AS description, a.workflow_task AS reference
       FROM `tabASOUD Workflow Activity` a
       WHERE a.workflow_instance=%(instance)s AND
         (%(issuer)s=1 OR a.actor=%(user)s OR a.action IN ('ابلاغ دستور','مختومه کردن دستور') OR EXISTS (
           SELECT 1 FROM `tabASOUD Workflow Task` t
           WHERE t.name=a.workflow_task AND t.assigned_to=%(user)s))
       ORDER BY a.created_on DESC, a.name DESC
       LIMIT %(branch_limit)s)
      UNION ALL
      (SELECT c.name, 'پیش‌نویس', c.owner, c.creation, c.content, c.reference_name
       FROM `tabComment` c
       WHERE %(issuer)s=1 AND c.reference_doctype=%(doctype)s
         AND c.reference_name=%(name)s AND c.comment_type='Info'
       ORDER BY c.creation DESC, c.name DESC
       LIMIT %(branch_limit)s)
    ) events ORDER BY created_at DESC, sort_id DESC LIMIT %(page_limit)s OFFSET %(offset)s
"""


def next_cursor(start, raw_count: int, page_size: int) -> str | None:
    """Return the cursor for the page after `start`, from the raw database row count.

    A page may come back empty or short after access filtering while more rows exist,
    so the cursor is based on `raw_count` (rows read before filtering). Clients keep
    requesting while `next_cursor` is set and stop on the first short raw page.
    """
    if raw_count < page_size:
        return None
    return str(max(0, int(start)) + raw_count)


def review_index(rows) -> dict:
    """Map `directive_subject_task` to its review row, keeping the first row per report.

    `rows` is ordered by creation ascending, so the earliest review wins if several
    exist for one report. Rows without a subject are skipped.
    """
    index = {}
    for row in rows:
        subject = row["directive_subject_task"]
        if subject:
            index.setdefault(subject, row)
    return index


def history_limits(offset: int, page_size: int = HISTORY_PAGE) -> dict:
    """Bound parameters for `HISTORY_SQL` beyond the caller's own filters.

    Reads one row more than the page so the caller can tell whether a next page exists.
    """
    fetch = page_size + 1
    return dict(offset=offset, branch_limit=offset + fetch, page_limit=fetch)
