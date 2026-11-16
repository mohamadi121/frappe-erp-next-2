"""Pure regression: the cartable list endpoints reject a guest (PA-039).

Runs the real ``list_my_workflow_*`` endpoints against the in-memory fake site. A
guest (no signed-in account) must be refused at the controller entry, while a
signed-in user is not blocked by the guard.
"""

import pytest

from asoud_erp.tests import _fake_site as fake
from asoud_erp.tests._workflow_access_world import make_world


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_list_tasks_rejects_guest(world):
    world.site.user = "Guest"
    with pytest.raises(fake.PermissionError_):
        world.runtime.list_my_workflow_tasks()


def test_list_instances_rejects_guest(world):
    world.site.user = "Guest"
    with pytest.raises(fake.PermissionError_):
        world.runtime.list_my_workflow_instances()


def test_list_notifications_rejects_guest(world):
    world.site.user = "Guest"
    with pytest.raises(fake.PermissionError_):
        world.runtime.list_my_workflow_notifications()


def test_list_tasks_allows_a_signed_in_user(world):
    world.site.user = "sara@example.com"
    result = world.runtime.list_my_workflow_tasks()
    assert result["ok"] is True
