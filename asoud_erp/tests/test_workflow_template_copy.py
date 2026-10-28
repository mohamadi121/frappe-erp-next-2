import json

import pytest

from asoud_erp.services.workflow_template_copy import appearance, graph_plan


def graph():
    stages = [{"name": key, "stage_type": kind, "stage_title": key, "sequence_no": n,
        "config_json": json.dumps({"nested": {"target_stage": "end"}, "literal": "بدون تغییر"}),
        "position_x": 10, "position_y": n * 150}
        for n, (key, kind) in enumerate((("start", "Start"), ("end", "End")))]
    edges = [{"from_stage": "start", "to_stage": "end", "sequence_no": 1, "condition_json": "{}"}]
    return stages, edges


def test_copy_has_fresh_graph_references_and_does_not_mutate_source():
    stages, edges = graph()
    before = json.dumps([stages, edges], sort_keys=True)
    copies, routes = graph_plan(stages, edges, {"start": "new-start", "end": "new-end"})
    assert {row["name"] for row in copies} == {"new-start", "new-end"}
    assert all(row["configuration_status"] == "Pending" for row in copies)
    assert json.loads(copies[0]["config_json"])["nested"]["target_stage"] == "new-end"
    assert routes[0]["from_stage"] == "new-start" and routes[0]["to_stage"] == "new-end"
    assert json.dumps([stages, edges], sort_keys=True) == before


def test_dangling_routes_are_rejected():
    stages, edges = graph()
    edges[0]["to_stage"] = "foreign-stage"
    with pytest.raises(ValueError):
        graph_plan(stages, edges, {"start": "new-start", "end": "new-end"})


@pytest.mark.parametrize("bad", ["[]", "null", "not-json"])
def test_malformed_config_is_rejected(bad):
    stages, edges = graph()
    stages[0]["config_json"] = bad
    with pytest.raises(ValueError):
        graph_plan(stages, edges, {"start": "new-start", "end": "new-end"})


def test_identity_and_graph_size_limits():
    stages, edges = graph()
    for rows, ids in (([], {}), (stages * 101, {}), (stages, {"start": "new"})):
        with pytest.raises(ValueError):
            graph_plan(rows, edges, ids)


def test_appearance_validates_without_touching_design():
    assert appearance("  گردش نمونه  ", " شرح ", "hub", "#315CF5") == ("گردش نمونه", "شرح")
    for args in (("x", "", "hub", "#315CF5"), ("عنوان", None, "hub", "#315CF5"),
                 ("عنوان", "", "invalid", "#315CF5"), ("عنوان", "", "hub", "invalid")):
        with pytest.raises(ValueError):
            appearance(*args)
