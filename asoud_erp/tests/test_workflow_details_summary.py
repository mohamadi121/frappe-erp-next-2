import json

from asoud_erp.services.workflow_contract import activation_requirements, design_details_summary


def saved_design():
    stages = [
        {'name': 's', 'stage_type': 'Start', 'configuration_status': 'Complete',
         'config_json': '{"trigger_type":"Manual","initiator_roles":["Employee"]}'},
        {'name': 'u', 'stage_type': 'User Task', 'stage_title': 'بررسی', 'configuration_status': 'Complete',
         'config_json': '{"activity_type":"Task","assignment_type":"Initiator"}'},
        {'name': 'e', 'stage_type': 'End', 'configuration_status': 'Complete', 'config_json': '{}'},
    ]
    edges = [{'from_stage': 's', 'to_stage': 'u', 'condition_json': '{}'},
             {'from_stage': 'u', 'to_stage': 'e', 'condition_json': '{}'}]
    return stages, edges


def test_complete_saved_design_has_no_fabricated_missing_requirements():
    stages, edges = saved_design()
    before = json.dumps([stages, edges])
    assert design_details_summary(stages, edges) == {
        'steps_count': 2, 'stages_complete': True, 'routes_complete': True, 'requirements': []}
    assert before == json.dumps([stages, edges])


def test_incomplete_stage_does_not_mark_real_routes_incomplete():
    stages, edges = saved_design()
    stages[1]['configuration_status'] = 'Pending'
    summary = design_details_summary(stages, edges)
    assert summary['stages_complete'] is False
    assert summary['routes_complete'] is True
    assert summary['requirements'] == activation_requirements(stages, edges)


def test_missing_route_does_not_mark_configured_stages_incomplete():
    stages, edges = saved_design()
    edges.pop()
    summary = design_details_summary(stages, edges)
    assert summary['stages_complete'] is True
    assert summary['routes_complete'] is False
    assert summary['requirements'] == activation_requirements(stages, edges)
