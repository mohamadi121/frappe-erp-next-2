"""Shared in-memory world for the pure cartable-access regression tests.

Each test file gets a fresh fake site and a fresh import of the real
``asoud_erp.api.v1.workflow_runtime`` module against it, so the access guards,
idempotent completion, bounded history and attachment checks run their real code
paths without a database.
"""

import importlib
import sys
import types
from datetime import timedelta

from asoud_erp.tests import _fake_site as fake


def make_world(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    utils.add_to_date = lambda d, days=0, **kw: (d + timedelta(days=days)).isoformat() if d else d
    for name, module in {"frappe": frappe, "frappe.utils": utils}.items():
        monkeypatch.setitem(sys.modules, name, module)
    # Re-import the real runtime against this fake frappe so its `frappe` global is
    # this test's site (the module otherwise caches the first test's fake).
    loaded = [name for name in list(sys.modules) if name.startswith("asoud_erp")]
    restore = fake.isolate(loaded)
    runtime = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    # The list endpoints read through raw SQL; the fake has no SQL engine, so return
    # an empty page. The guest guard under test throws before the SQL is reached.
    monkeypatch.setattr(frappe.db, "sql", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(frappe.db, "sql_list", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(frappe.db, "escape", lambda value: f"'{value}'", raising=False)
    world = types.SimpleNamespace(site=site, frappe=frappe, runtime=runtime)
    return world, restore
