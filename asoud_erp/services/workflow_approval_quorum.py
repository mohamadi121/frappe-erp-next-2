"""Decision counting for Approval stages with several approvers (PA-067).

`approval_mode` selects how many Approve decisions are needed before the stage
advances: `Any` (one, the legacy default), `All` (every assigned approver) or
`Majority` (more than half of the assigned approvers). A Reject or Return by
any approver still cancels the whole stage, as before.

A stage can be re-activated (a Return route back to it), which creates a fresh
set of tasks. Only the tasks of the most recent activation count toward the
decision; the tasks of an earlier round are already settled.
"""

MODES = {"Any", "All", "Majority"}

# Tasks of one round are created in a single loop, so their `assigned_on`
# values are milliseconds apart. A re-activation happens later (minutes or
# more), so a window this wide never mixes two rounds.
_ROUND_WINDOW_SECONDS = 60


def normalize_mode(config) -> str:
    """The decision mode of a saved stage config.

    Only an explicit `Any` or `Majority` changes the legacy behaviour; a
    missing or unknown value keeps the old `All` semantics so configs written
    before this feature behave exactly as they did.
    """
    mode = config.get("approval_mode") if isinstance(config, dict) else None
    if mode in MODES:
        return mode
    return "All"


def required_approvals(mode: str, total: int) -> int:
    """Approve decisions needed from `total` assigned approvers."""
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        raise ValueError("تعداد تأییدکنندگان مرحلهٔ تأیید نامعتبر است.")
    if mode == "Any":
        return 1
    if mode == "All":
        return total
    if mode == "Majority":
        return total // 2 + 1
    raise ValueError("حالت رأی‌گیری مرحلهٔ تأیید نامعتبر است؛ فقط هر یک، همه یا اکثریت مجاز است.")


def current_round(tasks: list[dict]) -> list[dict]:
    """The tasks created at the most recent activation of the stage.

    `tasks` are the stage's Open and Completed rows, each with an `assigned_on`
    datetime. The round is the newest cluster of `assigned_on` values.
    """
    if not tasks:
        return []
    stamps = [t["assigned_on"] for t in tasks if t.get("assigned_on") is not None]
    if not stamps:
        return list(tasks)
    newest = max(stamps)
    from datetime import timedelta

    floor = newest - timedelta(seconds=_ROUND_WINDOW_SECONDS)
    return [t for t in tasks if t.get("assigned_on") is not None and t["assigned_on"] >= floor]


def decision_counts(tasks: list[dict]) -> tuple[int, int]:
    """`(total, approved)` for the stage's current round."""
    round_tasks = current_round(tasks)
    total = len(round_tasks)
    approved = sum(1 for t in round_tasks if t.get("status") == "Completed" and t.get("action") == "Approve")
    return total, approved


def stage_reached_quorum(mode: str, total: int, approved: int) -> bool:
    """Whether `approved` Approve decisions satisfy the stage's decision mode."""
    return approved >= required_approvals(mode, total)
