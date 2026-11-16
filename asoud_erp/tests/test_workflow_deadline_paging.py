"""Pure regression: the hourly deadline job pages due tasks by keyset (PA-028).

``process_workflow_deadlines`` must not load every open task into memory in one
query. It walks due tasks in bounded keyset pages ordered by name. This test
drives the real ``next_keyset_cursor`` and ``_deadline_task_names`` against a
fake ``frappe.get_all`` that simulates a table larger than one page, and proves
each query reads at most one page while the job still visits every due task in
order, exactly once.
"""

import pytest

from asoud_erp.tests._workflow_access_world import make_world


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_next_keyset_cursor_advances_and_stops(world):
    from asoud_erp.api.v1.workflow_runtime import next_keyset_cursor

    # A full page means more rows may exist: the cursor is the last name read.
    assert next_keyset_cursor(["a", "b", "c"], 3) == "c"
    # A short page ends the run.
    assert next_keyset_cursor(["a", "b"], 3) is None
    # An empty page ends the run.
    assert next_keyset_cursor([], 3) is None


def test_deadline_task_names_pages_bounded_and_visits_all(world):
    from asoud_erp.api.v1.workflow_runtime import _deadline_task_names
    from asoud_erp.services.workflow_history_limits import DEADLINE_BATCH

    # A table of due tasks larger than one page, ordered by name.
    total = DEADLINE_BATCH + 7
    all_names = [f"WFT-2026-{i:05d}" for i in range(total)]
    pages_read = []

    def fake_get_all(doctype, filters=None, pluck=None, order_by=None, limit_page_length=20, **kwargs):
        assert doctype == "ASOUD Workflow Task"
        # Every query must be bounded to a single page, never unbounded.
        assert limit_page_length == DEADLINE_BATCH
        assert order_by == "name asc"
        cursor = (filters or {}).get("name")
        start = 0
        if cursor:
            operator, value = cursor
            assert operator == ">"
            start = all_names.index(value) + 1
        page = all_names[start:start + limit_page_length]
        pages_read.append(page)
        return page

    world.frappe.get_all = fake_get_all
    names = list(_deadline_task_names({"status": "Open"}))
    # Every due task is visited, in name order, exactly once.
    assert names == all_names
    # Two queries: one full page, then the short tail.
    assert len(pages_read) == 2
    assert len(pages_read[0]) == DEADLINE_BATCH
    assert len(pages_read[1]) == 7


def test_deadline_task_names_stops_on_empty_table(world):
    from asoud_erp.api.v1.workflow_runtime import _deadline_task_names

    queries = []

    def fake_get_all(doctype, filters=None, pluck=None, order_by=None, limit_page_length=20, **kwargs):
        queries.append(filters)
        return []

    world.frappe.get_all = fake_get_all
    assert list(_deadline_task_names({"status": "Open"})) == []
    # A single empty query, no cursor, no second page.
    assert len(queries) == 1
    assert "name" not in queries[0]
