"""Pure tests for the workflow graph snapshot (PA-015).

The service is exercised on the in-memory fake site so the snapshot/fallback
logic is proven without a Frappe site. The integration test
(``integration_tests/test_workflow_graph_snapshot.py``) proves the same behaviour
on a real site with real rows.
"""
import importlib
import json
import sys

import pytest

from asoud_erp.tests import _fake_site as fake


@pytest.fixture
def snap(monkeypatch):
    site = fake.Site()
    frappe, _utils = fake.install(site)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    restore = fake.isolate(["asoud_erp.services.workflow_graph_snapshot"])
    module = importlib.import_module("asoud_erp.services.workflow_graph_snapshot")
    yield module, site, frappe
    restore()


def _graph(site):
    site.add("ASOUD Workflow Stage", "s-start", workflow_definition="def-1", stage_type="Start",
             stage_title="شروع", config_json="{}")
    site.add("ASOUD Workflow Stage", "s-task", workflow_definition="def-1", stage_type="User Task",
             stage_title="ثبت", config_json=json.dumps({"form_fields": []}))
    site.add("ASOUD Workflow Stage", "s-end", workflow_definition="def-1", stage_type="End",
             stage_title="پایان", config_json="{}")
    site.add("ASOUD Workflow Transition", "t1", workflow_definition="def-1", from_stage="s-start",
             to_stage="s-task", transition_label=None, condition_json="{}", sequence_no=1)
    site.add("ASOUD Workflow Transition", "t2", workflow_definition="def-1", from_stage="s-task",
             to_stage="s-end", transition_label=None, condition_json="{}", sequence_no=1)


def _instance(site, raw):
    # A real instance row carries the snapshot column; the fake DB's has_column
    # reports a column present in its rows, so the field must be on the row.
    site.add("ASOUD Workflow Instance", "wfi-1", workflow_definition="def-1", status="Running",
             graph_snapshot_json=raw)
    return fake.FakeDoc(site, site.table("ASOUD Workflow Instance")["wfi-1"])


def test_capture_freezes_stages_and_transitions(snap):
    module, site, _ = snap
    _graph(site)
    data = json.loads(module.capture("def-1"))
    assert [row["name"] for row in data["stages"]] == ["s-start", "s-task", "s-end"]
    assert [row["name"] for row in data["transitions"]] == ["t1", "t2"]
    assert data["stages"][1]["config_json"] == json.dumps({"form_fields": []})


def test_load_returns_none_when_absent(snap):
    module, site, _ = snap
    assert module.load(fake.FakeDoc(site, {"graph_snapshot_json": None})) is None
    assert module.load(fake.FakeDoc(site, {})) is None


def test_load_rejects_corrupt_snapshot(snap):
    module, site, _ = snap
    assert module.load(fake.FakeDoc(site, {"graph_snapshot_json": "{not json"})) is None
    assert module.load(fake.FakeDoc(site, {"graph_snapshot_json": json.dumps({"stages": "x"})})) is None


def test_stage_for_reads_snapshot_not_live(snap):
    module, site, _ = snap
    _graph(site)
    instance = _instance(site, module.capture("def-1"))
    # The live table is edited after the snapshot; the frozen config must win.
    site.table("ASOUD Workflow Stage")["s-task"]["config_json"] = json.dumps({"form_fields": [{"key": "changed"}]})
    stage = module.stage_for(instance, "s-task")
    assert json.loads(stage.config_json) == {"form_fields": []}


def test_stage_for_falls_back_to_live_for_old_instance(snap):
    module, site, _ = snap
    _graph(site)
    instance = _instance(site, None)
    stage = module.stage_for(instance, "s-task")
    assert stage.stage_type == "User Task"
    assert stage.name == "s-task"


def test_stage_for_missing_in_snapshot_is_none(snap):
    module, site, _ = snap
    _graph(site)
    instance = _instance(site, module.capture("def-1"))
    assert module.stage_for(instance, "ghost") is None


def test_transitions_for_reads_snapshot(snap):
    module, site, _ = snap
    _graph(site)
    instance = _instance(site, module.capture("def-1"))
    rows = module.transitions_for(instance, "s-start")
    assert [row["to_stage"] for row in rows] == ["s-task"]


def test_transitions_for_falls_back_to_live(snap):
    module, site, _ = snap
    _graph(site)
    instance = _instance(site, None)
    rows = module.transitions_for(instance, "s-task")
    assert [row["to_stage"] for row in rows] == ["s-end"]


def test_has_transition_snapshot_and_fallback(snap):
    module, site, _ = snap
    _graph(site)
    snap_instance = _instance(site, module.capture("def-1"))
    assert module.has_transition(snap_instance, "s-task", to_stage="s-end") is True
    assert module.has_transition(snap_instance, "s-task", to_stage="ghost") is False
    assert module.has_transition(snap_instance, "s-end") is False
    live_instance = _instance(site, None)
    assert module.has_transition(live_instance, "s-start", to_stage="s-task") is True
    assert module.has_transition(live_instance, "s-end") is False


def test_require_stage_throws_when_missing(snap):
    module, site, frappe = snap
    _graph(site)
    instance = _instance(site, module.capture("def-1"))
    with pytest.raises(frappe.ValidationError):
        module.require_stage(instance, "ghost")


def _stages():
    return [
        {"name": "s-start", "stage_type": "Start"},
        {"name": "s-task", "stage_type": "User Task"},
        {"name": "s-end", "stage_type": "End"},
    ]


def _transitions():
    return [
        {"from_stage": "s-start", "to_stage": "s-task"},
        {"from_stage": "s-task", "to_stage": "s-end"},
    ]


def test_backfill_consistent_when_graph_matches_execution(snap):
    module, _, _ = snap
    assert module.backfill_consistent("s-task", _stages(), _transitions(), {"s-task"}) is True
    # A stage the instance already passed is also consistent.
    assert module.backfill_consistent("s-end", _stages(), _transitions(), {"s-task", "s-end"}) is True


def test_backfill_inconsistent_when_current_stage_orphan(snap):
    module, _, _ = snap
    assert module.backfill_consistent("ghost", _stages(), _transitions(), set()) is False
    assert module.backfill_consistent(None, _stages(), _transitions(), set()) is False


def test_backfill_inconsistent_when_task_stage_missing(snap):
    module, _, _ = snap
    # The instance acted on a stage that no longer exists in the live graph.
    assert module.backfill_consistent("s-task", _stages(), _transitions(), {"ghost"}) is False


def test_backfill_inconsistent_when_current_stage_unreachable(snap):
    module, _, _ = snap
    # s-end exists but the route into it was deleted, so it is no longer reachable.
    transitions = [{"from_stage": "s-start", "to_stage": "s-task"}]
    assert module.backfill_consistent("s-end", _stages(), transitions, set()) is False


def test_backfill_inconsistent_without_single_start(snap):
    module, _, _ = snap
    stages = _stages() + [{"name": "s-start2", "stage_type": "Start"}]
    assert module.backfill_consistent("s-task", stages, _transitions(), set()) is False


def test_backfill_snapshot_uses_capture_and_marks_source(snap):
    module, site, _ = snap
    _graph(site)
    data = json.loads(module.backfill_snapshot("def-1"))
    assert data["snapshot_source"] == "backfill_live_graph"
    assert [row["name"] for row in data["stages"]] == ["s-start", "s-task", "s-end"]
    assert [row["name"] for row in data["transitions"]] == ["t1", "t2"]
    # A reader must still parse the backfilled snapshot (unknown key ignored).
    assert module.load(_instance(site, module.backfill_snapshot("def-1"))) is not None
