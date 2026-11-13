from asoud_erp.services.workflow_paths import removal_plan


def nodes(*names):
    return [{'name': name, 'stage_type': 'Start' if name == 'root' else 'User Task'} for name in names]


def edge(name, source, target):
    return dict(name=name, from_stage=source, to_stage=target)


def test_exclusive_branch_does_not_delete_shared_target_or_other_branch():
    graph = [edge('a', 'root', 'left'), edge('b', 'root', 'right'),
        edge('c', 'left', 'shared'), edge('d', 'right', 'shared'), edge('e', 'shared', 'end')]
    assert removal_plan(nodes('root', 'left', 'right', 'shared', 'end'), graph, 'a') == {
        'stages': ['left'], 'transitions': ['a', 'c']}


def test_last_exclusive_branch_is_removed_without_leaving_lines():
    graph = [edge('a', 'root', 'left'), edge('b', 'left', 'end')]
    assert removal_plan(nodes('root', 'left', 'end'), graph, 'a') == {
        'stages': ['end', 'left'], 'transitions': ['a', 'b']}


def test_exclusive_cycle_is_removed_without_erasing_the_root():
    graph = [edge('a', 'root', 'left'), edge('b', 'other', 'left'), edge('c', 'left', 'other')]
    assert removal_plan(nodes('root', 'left', 'other'), graph, 'a')['stages'] == ['left', 'other']
