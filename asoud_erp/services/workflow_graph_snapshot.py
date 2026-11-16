"""Freeze a workflow's stage/transition graph at instance start.

A running instance must keep the stage graph it started with when the designer
later edits stages or routes. The snapshot is a JSON document of every stage and
transition of the definition, captured once when the instance is created. The
runtime reads routes and stage config from it when present, and falls back to
the live rows for old instances that predate the field.
"""
import json

import frappe

STAGE = "ASOUD Workflow Stage"
TRANSITION = "ASOUD Workflow Transition"

STAGE_FIELDS = ["name", "stage_type", "stage_title", "config_json", "workflow_definition"]
TRANSITION_FIELDS = ["name", "from_stage", "to_stage", "transition_label", "condition_json", "sequence_no"]


def ready() -> bool:
    """True once the ``graph_snapshot_json`` column exists (after ``bench migrate``)."""
    return frappe.db.has_column("ASOUD Workflow Instance", "graph_snapshot_json")


def capture(definition: str) -> str:
    """Serialize the definition's full graph to a JSON string.

    Transitions are ordered by ``sequence_no`` so a snapshot read keeps the same
    order the live query (``order_by="sequence_no asc"``) would return.
    """
    stages = frappe.get_all(STAGE, filters={"workflow_definition": definition},
        fields=STAGE_FIELDS, limit_page_length=0)
    transitions = frappe.get_all(TRANSITION, filters={"workflow_definition": definition},
        fields=TRANSITION_FIELDS, order_by="sequence_no asc", limit_page_length=0)
    return json.dumps({"stages": [dict(row) for row in stages],
                       "transitions": [dict(row) for row in transitions]}, ensure_ascii=False)


def load(instance) -> dict | None:
    """Parse the instance's snapshot, or ``None`` when it has none (old instance).

    A corrupt or partial snapshot is treated as absent so the engine falls back
    to the live rows rather than crashing mid-execution.
    """
    raw = getattr(instance, "graph_snapshot_json", None)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("stages"), list) \
            or not isinstance(data.get("transitions"), list):
        return None
    return data


def stage_for(instance, name):
    """A stage as a ``frappe._dict`` from the snapshot when present, else the live row.

    Returns ``None`` when the stage is not found (in the snapshot, or in the live
    table for old instances) instead of raising, so callers keep their own
    Persian error for a missing destination.
    """
    snap = load(instance)
    if snap:
        for row in snap["stages"]:
            if row["name"] == name:
                return frappe._dict(row)
        return None
    if not frappe.db.exists(STAGE, name):
        return None
    return frappe.get_doc(STAGE, name)


def require_stage(instance, name):
    """Like :func:`stage_for`, but a missing stage is a Persian error, not ``None``.

    Used where the stage is expected to exist (the task's own stage); a missing
    one is a data problem the user must be told about, not an ``AttributeError``.
    """
    stage = stage_for(instance, name)
    if not stage:
        frappe.throw("مرحلهٔ این وظیفه در دسترس نیست؛ مدیر گردش کار باید نمودار را بررسی کند.")
    return stage


def transitions_for(instance, from_stage) -> list:
    """Outgoing transitions from ``from_stage``: the snapshot first, then live rows."""
    snap = load(instance)
    if snap:
        return [frappe._dict(row) for row in snap["transitions"] if row["from_stage"] == from_stage]
    return frappe.get_all(TRANSITION,
        filters={"workflow_definition": instance.workflow_definition, "from_stage": from_stage},
        fields=TRANSITION_FIELDS, order_by="sequence_no asc", limit_page_length=0)


def has_transition(instance, from_stage, to_stage=None) -> bool:
    """Whether a transition out of ``from_stage`` (optionally into ``to_stage``) exists.

    Snapshot-aware: a frozen instance's routes live in its snapshot, so a route the
    designer later deleted still counts for that instance.
    """
    snap = load(instance)
    if snap:
        rows = [row for row in snap["transitions"] if row["from_stage"] == from_stage]
        if to_stage is not None:
            rows = [row for row in rows if row["to_stage"] == to_stage]
        return bool(rows)
    filters = {"workflow_definition": instance.workflow_definition, "from_stage": from_stage}
    if to_stage is not None:
        filters["to_stage"] = to_stage
    return bool(frappe.db.exists(TRANSITION, filters))


