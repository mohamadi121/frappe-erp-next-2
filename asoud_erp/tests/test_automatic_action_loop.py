"""Regression test for the async (schema_version 2) automatic-action loop.

A loop made only of System Action stages (A -> B -> A, a self loop, or a loop
through a Condition) is stopped by the receipt idempotency in
``automatic_action_runtime.schedule``: re-entering an automatic stage with the
same trigger raises a Persian ``ValueError`` (``REPEATED_ACTIVATION``) instead
of the old English sentence. The worker then settles — it never loops forever —
and the instance ends on its Error route (or ``Failed`` when there is no Error
route). A legitimate re-entry through a human task uses a fresh trigger, so a
new receipt is allowed and nothing is blocked.

Limits of this test (read before trusting it):
- It runs on the in-memory fake site (``asoud_erp.tests._fake_site``). Rollback
  is modelled by deep-copying the tables, savepoints included; it is NOT run on
  MariaDB and NOT through a real RQ worker.
- ``perform()`` and the service identity are stubbed; only ``schedule`` /
  ``run`` / ``_finish`` / ``_activate_stage`` are the real code paths.
- Real-database behaviour of this path is covered only by the existing
  integration tests.
"""

import contextlib
import importlib
import json
import sys
import types

import pytest

from asoud_erp.tests import _fake_site as fake

# The exact Persian sentence the runtime must raise when an automatic stage is
# re-entered with the same trigger. Pinned here (not imported from the module)
# so the test fails if the message regresses to the old English text.
EXPECTED_PERSIAN = (
    "ورود دوباره به یک مرحلهٔ خودکار با همان محرک مجاز نیست؛ پیش از تکرار این اقدام یک وظیفهٔ انسانی در مسیر قرار دهید."
)

EXEC = {"extra_attempts": 2, "retry_seconds": 1, "timeout_seconds": 60}


def stg(name, kind, config=None):
    return dict(name=name, stage_type=kind, stage_title=name, workflow_definition="DEF",
                config_json=json.dumps(config or {}), configuration_status="Complete")


def edg(a, b, action=""):
    return dict(name=f"{a}-{b}-{action}", from_stage=a, to_stage=b,
                condition_json=json.dumps({"action": action} if action else {}), transition_label="", sequence_no=1)


SA = {"schema_version": 2, "action_type": "Send Notification", "operation": {}, "execution": EXEC}


@pytest.fixture
def env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    utils.add_to_date = lambda *a, **k: "now"
    utils.get_datetime = lambda v=None: 0
    utils.now_datetime = lambda: 1
    import copy
    snaps = {}

    def commit():
        snaps["__commit__"] = copy.deepcopy(site.tables)

    def savepoint(name):
        snaps[name] = copy.deepcopy(site.tables)

    def rollback(save_point=None):
        site.tables = copy.deepcopy(snaps[save_point or "__commit__"])
    frappe.db.commit, frappe.db.savepoint, frappe.db.rollback = commit, savepoint, rollback
    frappe.log_error = lambda **k: None
    site._commit = commit
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    rq = types.ModuleType("rq")
    rqt = types.ModuleType("rq.timeouts")
    rqt.JobTimeoutException = type("JobTimeoutException", (Exception,), {})
    rq.timeouts = rqt
    for n, m in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                 "frappe.model.naming": naming, "rq": rq, "rq.timeouts": rqt}.items():
        monkeypatch.setitem(sys.modules, n, m)
    # receipts are named by hash: honour set_name like Frappe does
    orig_insert = fake.FakeDoc.insert

    def insert(self, **kwargs):
        if kwargs.get("set_name"):
            self._data["name"] = kwargs["set_name"]
        return orig_insert(self, **kwargs)
    monkeypatch.setattr(fake.FakeDoc, "insert", insert)
    restore = fake.isolate(["asoud_erp.services.automatic_action_runtime", "asoud_erp.api.v1.workflow_runtime",
                            "asoud_erp.services.workflow_condition_binding", "asoud_erp.services.request_access",
                            "asoud_erp.services.erp_documents", "asoud_erp.services.request_link_values",
                            "asoud_erp.api.v1.document_templates", "asoud_erp.services.automatic_action_metadata"])
    site.user = "Administrator"
    rt = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    aar = importlib.import_module("asoud_erp.services.automatic_action_runtime")
    monkeypatch.setattr(aar, "service_user", lambda company: "svc@example.com")
    monkeypatch.setattr(aar, "_company", lambda instance: "WP")
    monkeypatch.setattr(aar, "validate_config", lambda *a: None)
    monkeypatch.setattr(aar, "perform", lambda receipt, instance, config, company: {})
    monkeypatch.setattr(aar, "identity", lambda company: contextlib.nullcontext("svc@example.com"))
    monkeypatch.setattr(rt, "_notify_user", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_users_for_roles", lambda roles: [])
    yield types.SimpleNamespace(site=site, rt=rt, aar=aar)
    restore()


def build(env, stages, edges):
    snap = json.dumps({"stages": stages, "transitions": edges})
    site = env.site
    site.add("ASOUD Workflow Definition", "DEF", company="WP", status="Active")
    for s in stages:
        site.add("ASOUD Workflow Stage", s["name"], **{k: v for k, v in s.items() if k != "name"})
    end = importlib.import_module("asoud_erp.services.workflow_end")
    end.finish = lambda inst, stg, **kw: (setattr(inst, "status", "Completed"), inst.save())
    row = site.add("ASOUD Workflow Instance", "WFI-1", workflow_definition="DEF", status="Running",
                   current_stage=None, started_by="user@example.com", graph_snapshot_json=snap,
                   reference_doctype=None, reference_name=None)
    site._commit()
    return fake.FakeDoc(site, row)


def drain(env, limit=30):
    """Run every Pending/Retry Pending receipt like the worker would; returns number of worker runs."""
    runs = 0
    while runs < limit:
        pending = [n for n, r in env.site.table("ASOUD Action Execution").items()
                   if r["status"] in ("Pending", "Retry Pending")]
        if not pending:
            break
        env.aar.run(pending[0])
        runs += 1
    return runs


def run_loop(env, stages, edges, first):
    instance = build(env, stages, edges)
    stage = types.SimpleNamespace(**next(s for s in stages if s["name"] == first))
    error = None
    try:
        env.rt._activate_stage(instance, stage)
    except Exception as e:  # sync part
        error = e
    runs = drain(env)
    inst = env.site.table("ASOUD Workflow Instance")["WFI-1"]
    receipts = {r["workflow_stage"]: r for r in env.site.table("ASOUD Action Execution").values()}
    return error, runs, inst["status"], receipts


def test_two_system_action_v2_stages_in_a_loop_end_bounded(env):
    stages = [stg("S", "Start"), stg("A", "System Action", SA), stg("B", "System Action", SA), stg("E", "End")]
    edges = [edg("S", "A"), edg("A", "B", "Success"), edg("B", "A", "Success"), edg("A", "E", "Error"),
             edg("B", "E", "Error")]
    error, runs, status, receipts = run_loop(env, stages, edges, "A")
    assert error is None
    assert runs <= 2, "worker never settled: unbounded loop"
    assert receipts["A"]["status"] == "Succeeded"
    assert receipts["B"]["status"] == "Failed"
    assert receipts["B"]["error_code"] == "ValueError"
    assert receipts["B"]["error_message"] == EXPECTED_PERSIAN


def test_single_system_action_v2_self_loop_ends_bounded(env):
    stages = [stg("S", "Start"), stg("A", "System Action", SA), stg("E", "End")]
    edges = [edg("S", "A"), edg("A", "A", "Success"), edg("A", "E", "Error")]
    error, runs, status, receipts = run_loop(env, stages, edges, "A")
    assert error is None
    assert runs <= 2, "worker never settled: unbounded loop"
    assert receipts["A"]["status"] == "Failed"
    assert receipts["A"]["error_code"] == "ValueError"
    assert receipts["A"]["error_message"] == EXPECTED_PERSIAN


def test_condition_in_the_middle_of_an_async_loop_ends_bounded(env, monkeypatch):
    cond = {"condition_version": 2}
    stages = [stg("S", "Start"), stg("A", "System Action", SA), stg("C", "Condition", cond), stg("E", "End")]
    edges = [edg("S", "A"), edg("A", "C", "Success"), edg("C", "A"), edg("C", "E"), edg("A", "E", "Error")]
    edges[2]["condition_json"] = json.dumps({"result": True})
    edges[3]["condition_json"] = json.dumps({"result": False})
    binding = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    group = importlib.import_module("asoud_erp.services.workflow_condition")
    monkeypatch.setattr(binding, "catalog", lambda d, n: [])
    monkeypatch.setattr(binding, "validate_bindings", lambda c, a: None)
    monkeypatch.setattr(binding, "resolver", lambda *a: None)
    monkeypatch.setattr(group, "evaluate_group", lambda c, r: True)
    error, runs, status, receipts = run_loop(env, stages, edges, "A")
    assert error is None
    assert runs <= 2, "worker never settled: unbounded loop"
    assert receipts["A"]["status"] == "Failed"
    assert receipts["A"]["error_message"] == EXPECTED_PERSIAN


def test_loop_without_an_error_route_fails_the_instance(env):
    stages = [stg("S", "Start"), stg("A", "System Action", SA), stg("B", "System Action", SA)]
    edges = [edg("S", "A"), edg("A", "B", "Success"), edg("B", "A", "Success")]
    error, runs, status, receipts = run_loop(env, stages, edges, "A")
    assert error is None
    assert runs <= 2, "worker never settled: unbounded loop"
    assert status == "Failed"


def test_legit_loop_through_a_human_task_is_not_blocked(env):
    # A -> Task -> A: the second entry has a fresh trigger (the task name), so a new receipt is allowed.
    stages = [stg("S", "Start"), stg("A", "System Action", SA)]
    instance = build(env, stages, [edg("S", "A")])
    env.rt._activate_stage(instance, types.SimpleNamespace(**stages[1]))
    first = list(env.site.table("ASOUD Action Execution"))
    assert len(first) == 1
    env.aar.schedule(instance, fake.FakeDoc(env.site, env.site.table("ASOUD Workflow Stage")["A"]), SA, trigger="TASK-0001")
    receipts = list(env.site.table("ASOUD Action Execution").values())
    assert len(receipts) == 2, "a fresh trigger must schedule a second receipt"
    assert {r["trigger_id"] for r in receipts} == {"start", "TASK-0001"}


def test_english_text_no_longer_appears_in_any_receipt(env):
    stages = [stg("S", "Start"), stg("A", "System Action", SA), stg("B", "System Action", SA), stg("E", "End")]
    edges = [edg("S", "A"), edg("A", "B", "Success"), edg("B", "A", "Success"), edg("A", "E", "Error"),
             edg("B", "E", "Error")]
    error, runs, status, receipts = run_loop(env, stages, edges, "A")
    for row in receipts.values():
        assert "Repeated automatic-stage" not in (row.get("error_message") or "")
