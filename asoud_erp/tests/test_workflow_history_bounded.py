"""Pure regression: workflow history reads are bounded (PA-028).

Runs the real ``_workflow_history`` helper against the in-memory fake site. A long
process must not load every activity into memory; only the newest ``HISTORY_LIMIT``
rows are read, returned oldest-first for the timeline.
"""

import pytest

from asoud_erp.tests._workflow_access_world import make_world


@pytest.fixture
def world(monkeypatch):
    w, restore = make_world(monkeypatch)
    yield w
    restore()


def test_workflow_history_is_bounded_and_chronological(world):
    site = world.site
    for i in range(250):
        site.add("ASOUD Workflow Activity", f"ACT-{i:03d}", workflow_instance="WFI-1",
                 actor="u@example.com", action="Approve",
                 created_on=f"2026-01-01 00:{i // 60:02d}:{i % 60:02d}")
    rows = world.runtime._workflow_history("WFI-1", ["name", "created_on"])
    assert len(rows) == 200
    # The 200 newest rows (i=50..249), returned oldest-first for the timeline.
    assert rows[0]["created_on"] == "2026-01-01 00:00:50"
    assert rows[-1]["created_on"] == "2026-01-01 00:04:09"
