"""Pure regression: idempotent completion of a workflow task (PA-025).

Runs the real ``complete_workflow_task`` against the in-memory fake site. A network
retry that re-sends the same ``request_id`` after the decision was already applied
must return the stored result, not a validation error.
"""

import json

import pytest

from asoud_erp.tests import _fake_site as fake
from asoud_erp.tests._workflow_access_world import make_world


def _completed_task(site, task="T1", instance="WFI-1", stage="STAGE-1", user="sara@example.com"):
    site.add("ASOUD Workflow Instance", instance, status="Completed", started_by="other@example.com",
             reference_doctype=None)
    site.add("ASOUD Workflow Stage", stage, stage_type="Approval", config_json="{}")
    site.add("ASOUD Workflow Task", task, workflow_instance=instance, workflow_stage=stage,
             status="Completed", assigned_to=user, action="Approve")


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_complete_replays_previous_result_on_request_id_retry(world):
    site = world.site
    _completed_task(site)
    site.add("ASOUD Workflow Activity", "ACT-1", workflow_task="T1", workflow_instance="WFI-1",
             actor="sara@example.com", action="Approve",
             change_json=json.dumps({"request_id": "req-12345678"}),
             created_on="2026-10-05 10:00:00")
    result = world.runtime.complete_workflow_task("T1", "Approve", request_id="req-12345678")
    assert result["ok"] is True
    assert result["data"]["task"] == "T1"
    assert result["data"]["instance_status"] == "Completed"


def test_complete_replay_is_bound_to_the_same_task(world):
    site = world.site
    _completed_task(site, task="T1")
    _completed_task(site, task="T2", instance="WFI-2")
    # The request_id was used on T1 only; replaying it on T2 must not return T1's result.
    site.add("ASOUD Workflow Activity", "ACT-1", workflow_task="T1", workflow_instance="WFI-1",
             actor="sara@example.com", action="Approve",
             change_json=json.dumps({"request_id": "req-12345678"}),
             created_on="2026-10-05 10:00:00")
    with pytest.raises(fake.Error):
        world.runtime.complete_workflow_task("T2", "Approve", request_id="req-12345678")


def test_complete_without_request_id_still_rejects_completed_task(world):
    site = world.site
    _completed_task(site)
    with pytest.raises(fake.ValidationError):
        world.runtime.complete_workflow_task("T1", "Approve")
