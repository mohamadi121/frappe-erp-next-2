"""Pure regression: a previous participant keeps view access after a reassign (PA-045).

Runs the real ``_assert_instance_access`` against the in-memory fake site. A user who
already acted on an instance (an Activity row with their actor) keeps read access even
after the task moved to someone else; an unrelated user is still denied.
"""

import pytest

from asoud_erp.tests import _fake_site as fake
from asoud_erp.tests._workflow_access_world import make_world


def _instance_with_history(site, instance="WFI-1"):
    site.add("ASOUD Workflow Instance", instance, status="Running", started_by="other@example.com",
             reference_doctype=None)
    site.add("ASOUD Workflow Task", "T1", workflow_instance=instance, assigned_to="user-b@example.com",
             status="Open")
    site.add("ASOUD Workflow Activity", "ACT-1", workflow_instance=instance, actor="user-a@example.com",
             action="Approve", created_on="2026-10-05 10:00:00")


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_previous_assignee_keeps_view_access_via_activity(world):
    site = world.site
    _instance_with_history(site)
    site.user = "user-a@example.com"  # acted on the instance, then the task moved to user-b
    instance = world.frappe.get_doc("ASOUD Workflow Instance", "WFI-1")
    world.runtime._assert_instance_access(instance)  # must not raise


def test_unrelated_user_cannot_view_instance(world):
    site = world.site
    _instance_with_history(site)
    site.user = "stranger@example.com"
    instance = world.frappe.get_doc("ASOUD Workflow Instance", "WFI-1")
    with pytest.raises(fake.PermissionError_):
        world.runtime._assert_instance_access(instance)
