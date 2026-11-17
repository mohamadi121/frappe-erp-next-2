"""Backfill ``graph_snapshot_json`` for old Running instances (PA-015).

Instances started before the snapshot field existed have an empty
``graph_snapshot_json`` and run against the live rows. There is no stored design
history, so a historical snapshot cannot be recovered. For each Running instance
with an empty snapshot we check whether the *live* graph is still consistent with
what the instance already executed (its ``current_stage`` exists and is reachable
from Start, and every stage its tasks/activities touched still exists). When it
is, we freeze the live graph as the snapshot using the same builder
``start_workflow_instance`` uses, tagged with ``snapshot_source:
"backfill_live_graph"``. When it is not, we leave the instance untouched and log
one ``Error Log`` entry listing the names so an admin can review.

Idempotent: only instances with an empty snapshot are considered, so a re-run
changes nothing.
"""
import frappe

from asoud_erp.services.workflow_graph_snapshot import (
    STAGE,
    TRANSITION,
    backfill_consistent,
    backfill_snapshot,
)


def execute() -> None:
    if not frappe.db.has_column("ASOUD Workflow Instance", "graph_snapshot_json"):
        return  # Pre-migrate site: the column does not exist yet.
    # Fetch every Running instance and filter the empty snapshots in Python: a
    # SQL `in ('', NULL)` does not reliably match a NULL column, and the set of
    # running instances is small.
    instances = frappe.get_all(
        "ASOUD Workflow Instance",
        filters={"status": "Running"},
        fields=["name", "workflow_definition", "current_stage", "graph_snapshot_json"],
        limit_page_length=0,
    )
    inconsistent = []
    for instance in instances:
        if instance.graph_snapshot_json:
            continue  # Already frozen (by start or a previous backfill run).
        definition = instance.workflow_definition
        stages = frappe.get_all(
            STAGE, filters={"workflow_definition": definition},
            fields=["name", "stage_type"], limit_page_length=0)
        transitions = frappe.get_all(
            TRANSITION, filters={"workflow_definition": definition},
            fields=["from_stage", "to_stage"], limit_page_length=0)
        task_stages = _touched_stages(instance.name)
        if not backfill_consistent(instance.current_stage, stages, transitions, task_stages):
            inconsistent.append(instance.name)
            continue
        frappe.db.set_value("ASOUD Workflow Instance", instance.name,
                            "graph_snapshot_json", backfill_snapshot(definition))
    if inconsistent:
        frappe.log_error(
            title="PA-015 snapshot backfill needs review",
            message="These Running instances have no snapshot and their live graph is "
                    "inconsistent with what they already executed; they were left "
                    "unchanged: " + ", ".join(sorted(inconsistent)),
        )


def _touched_stages(instance_name: str) -> set:
    """Stage names the instance's tasks and activities reference."""
    stages = set()
    for doctype in ("ASOUD Workflow Task", "ASOUD Workflow Activity"):
        for row in frappe.get_all(doctype, filters={"workflow_instance": instance_name},
                                  fields=["workflow_stage"], limit_page_length=0):
            if row.workflow_stage:
                stages.add(row.workflow_stage)
    return stages
