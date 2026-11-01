import pytest

from asoud_erp.services.workflow_contract import activation_requirements, is_system_workflow


def graph():
    return [
        {'name': 'start', 'stage_type': 'Start', 'configuration_status': 'Complete',
         'config_json': '{"trigger_type":"Manual","initiator_roles":["Employee"]}'},
        {'name': 'task', 'stage_type': 'User Task', 'configuration_status': 'Complete',
         'stage_title': 'بررسی', 'config_json': '{"activity_type":"Task","assignment_type":"Initiator"}'},
        {'name': 'end', 'stage_type': 'End', 'configuration_status': 'Complete', 'config_json': '{}'},
    ], [
        {'from_stage': 'start', 'to_stage': 'task', 'condition_json': '{}'},
        {'from_stage': 'task', 'to_stage': 'end', 'condition_json': '{}'},
    ]


def test_complete_graph_can_activate_without_native_workflow_link():
    stages, edges = graph()
    assert activation_requirements(stages, edges) == []


@pytest.mark.parametrize('kind', ['pending', 'missing_end', 'disconnected', 'bad_config', 'ambiguous'])
def test_incomplete_graph_is_rejected(kind):
    stages, edges = graph()
    if kind == 'pending':
        stages[1]['configuration_status'] = 'Pending'
    elif kind == 'missing_end':
        stages.pop()
    elif kind == 'disconnected':
        edges.pop()
    elif kind == 'bad_config':
        stages[1]['config_json'] = '[]'
    else:
        edges.append(dict(edges[-1]))
    assert activation_requirements(stages, edges)


@pytest.mark.parametrize('row', [
    {'is_system_template': 1}, {'is_system_template': '1'},
    {'template_key': 'leave'}, {'workflow_code': 'SYS-LEAVE-ASD'}, {'name': 'SYS-LEGACY'},
])
def test_system_identification_fails_closed(row):
    assert is_system_workflow(row)


def test_independent_template_copy_is_not_system_owned():
    assert not is_system_workflow({'creation_mode': 'Template', 'workflow_code': 'WF-1'})
