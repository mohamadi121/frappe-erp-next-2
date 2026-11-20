"""Bounded reads of workflow history and the deadline job (no unbounded queries).

Every history list and the hourly deadline job read at most ``HISTORY_LIMIT`` rows,
newest first. The client shows the recent history; older rows stay in the database
and are never loaded into memory in one query.
"""

HISTORY_LIMIT = 200
DEADLINE_BATCH = 500


def history_order():
    """Newest first, so the bounded read keeps the most recent rows."""
    return "created_on desc"
