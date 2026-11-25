"""B1: a cycle made only of automatic stages is rejected at design time and stopped at run time."""

import importlib
import json
import sys
import types

import pytest

from asoud_erp.services import workflow_auto_chain as chain
from asoud_erp.services.workflow_contract import activation_requirements
from asoud_erp.tests import _fake_site as fake


def stage(name, kind):
    config = {"condition_version": 2} if kind == "Condition" else {}
    return dict(name=name, stage_type=kind, stage_title=name, workflow_definition="DEF",
                config_json=json.dumps(config), configuration_status="Complete")


def edge(source, target, result=None):
    condition = {} if result is None else {"result": result}
    return dict(name=f"{source}-{target}-{result}", from_stage=source, to_stage=target,
                condition_json=json.dumps(condition), transition_label="", sequence_no=1)


CYCLE_STAGES = [stage("S", "Start"), stage("C1", "Condition"), stage("C2", "Condition"), stage("E", "End")]
CYCLE_EDGES = [edge("S", "C1"), edge("C1", "C2", True), edge("C1", "E", False),
               edge("C2", "C1", True), edge("C2", "E", False)]


def test_cycle_of_automatic_stages_is_found():
    assert chain.auto_cycle_stages(CYCLE_STAGES, CYCLE_EDGES) == {"C1", "C2"}


def test_self_loop_of_an_automatic_stage_is_a_cycle():
    assert chain.auto_cycle_stages(CYCLE_STAGES, [edge("C1", "C1", True)]) == {"C1"}


def test_cycle_through_a_person_or_a_wait_is_allowed():
    for kind in ("User Task", "Approval", "Wait"):
        stages = [stage("S", "Start"), stage("C1", "Condition"), stage("H", kind), stage("E", "End")]
        edges = [edge("S", "C1"), edge("C1", "H", True), edge("C1", "E", False), edge("H", "C1")]
        assert chain.auto_cycle_stages(stages, edges) == set()


def test_acyclic_automatic_chain_is_allowed():
    stages = [stage("S", "Start"), stage("C1", "Condition"), stage("A", "System Action"), stage("E", "End")]
    edges = [edge("S", "C1"), edge("C1", "A", True), edge("C1", "E", False), edge("A", "E")]
    assert chain.auto_cycle_stages(stages, edges) == set()


def test_limit_is_the_number_of_automatic_stages_not_a_fixed_number():
    assert chain.chain_limit(2) == 2
    assert chain.chain_limit(0) == 1
    assert not chain.chain_too_long(1, 2)  # C1 done, entering C2 is fine
    assert chain.chain_too_long(2, 2)      # both done, a third entry revisits one
    assert not chain.chain_too_long(49, 120)


def test_design_validation_names_the_automatic_cycle():
    assert chain.AUTO_CYCLE_DESIGN in activation_requirements(CYCLE_STAGES, CYCLE_EDGES)


def test_valid_design_without_a_cycle_is_not_flagged():
    stages = [stage("S", "Start"), stage("C1", "Condition"), stage("E", "End")]
    edges = [edge("S", "C1"), edge("C1", "E", True), edge("C1", "E", False)]
    assert chain.AUTO_CYCLE_DESIGN not in activation_requirements(stages, edges)


RELOADED_RT = [
    "asoud_erp.api.v1.workflow_runtime", "asoud_erp.services.workflow_condition_binding",
    "asoud_erp.services.request_access", "asoud_erp.services.erp_documents",
    "asoud_erp.services.request_link_values", "asoud_erp.api.v1.document_templates",
]


@pytest.fixture
def runtime_env(monkeypatch):
    site = fake.Site()
    frappe, utils = fake.install(site)
    utils.add_to_date = lambda *args, **kwargs: "now"
    naming = types.ModuleType("frappe.model.naming")
    naming.make_autoname = lambda key: key
    model = types.ModuleType("frappe.model")
    model.naming = naming
    frappe.model = model
    for name, module in {"frappe": frappe, "frappe.utils": utils, "frappe.model": model,
                         "frappe.model.naming": naming}.items():
        monkeypatch.setitem(sys.modules, name, module)
    restore = fake.isolate(RELOADED_RT)
    site.user = "Administrator"
    runtime = importlib.import_module("asoud_erp.api.v1.workflow_runtime")
    binding = importlib.import_module("asoud_erp.services.workflow_condition_binding")
    group = importlib.import_module("asoud_erp.services.workflow_condition")
    monkeypatch.setattr(binding, "catalog", lambda definition, name: [])
    monkeypatch.setattr(binding, "validate_bindings", lambda config, available: None)
    monkeypatch.setattr(binding, "resolver", lambda *args: None)
    monkeypatch.setattr(group, "evaluate_group", lambda config, resolve: True)
    frappe.log_error = lambda **kwargs: None
    env = types.SimpleNamespace(site=site, frappe=frappe, runtime=runtime)
    yield env
    restore()


def instance_for(stages, edges):
    snapshot = json.dumps({"stages": stages, "transitions": edges})
    return types.SimpleNamespace(name="WFI-1", workflow_definition="DEF", status="Running", current_stage=None,
                                 reference_doctype=None, reference_name=None, graph_snapshot_json=snapshot,
                                 save=lambda **kwargs: None)


def activities(env):
    return [row.get("action") for row in env.site.table("ASOUD Workflow Activity").values()]


def test_runtime_stops_a_condition_cycle_with_a_persian_error(runtime_env):
    env = runtime_env
    instance = instance_for(CYCLE_STAGES, CYCLE_EDGES)
    start = types.SimpleNamespace(**CYCLE_STAGES[1])
    with pytest.raises(fake.ValidationError) as caught:
        env.runtime._activate_stage(instance, start)
    assert str(caught.value) == chain.AUTO_LOOP
    assert len(activities(env)) == 2  # exactly one pass over C1 and C2, then stopped


def test_runtime_lets_a_long_acyclic_condition_chain_finish(runtime_env, monkeypatch):
    env = runtime_env
    names = [f"C{i}" for i in range(1, 8)]
    stages = [stage("S", "Start")] + [stage(n, "Condition") for n in names] + [stage("E", "End")]
    edges = [edge("S", "C1")] + [edge(a, b, True) for a, b in zip(names, names[1:])] + [edge("C7", "E", True)]
    instance = instance_for(stages, edges)
    finished = []
    end = importlib.import_module("asoud_erp.services.workflow_end")
    monkeypatch.setattr(end, "finish", lambda inst, stg, **kwargs: finished.append(stg.name))
    env.runtime._activate_stage(instance, types.SimpleNamespace(**stages[1]))
    assert finished == ["E"]
    assert len(activities(env)) == 7


def test_history_rows_use_the_frozen_stage_and_skip_a_deleted_one(runtime_env):
    env = runtime_env
    frozen = dict(stage("KEPT", "User Task"), config_json=json.dumps({"form_fields": [{"key": "a"}]}))
    instance = instance_for([frozen], [])
    # The live row says something else; the instance must keep its frozen copy.
    env.site.add("ASOUD Workflow Stage", "KEPT", workflow_definition="DEF", stage_type="User Task",
                 config_json=json.dumps({"form_fields": []}))
    for name, stage_name in (("T1", "KEPT"), ("T2", "GONE")):
        env.site.add("ASOUD Workflow Task", name, workflow_instance="WFI-1", status="Completed",
                     workflow_stage=stage_name, task_title=name, response_json="{}", completed_on="2026-01-01")
    rows = env.runtime._completed_task_rows(instance)
    assert [row["name"] for row in rows] == ["T1"]
    assert rows[0]["form_fields"] == [{"key": "a"}]
