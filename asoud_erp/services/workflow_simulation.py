"""Side-effect-free walk of a stored workflow graph.

Reuses the runtime's route selection: ``select_boolean_transition`` for Condition
stages and the same ``condition.action``/``transition_label`` match the runtime's
``_next_stage`` uses for decision stages. Condition stages are not evaluated
against data; the caller supplies True/False. Nothing is written.
"""
import json

from asoud_erp.services.workflow_condition import select_boolean_transition

MAX_STEPS = 200
# Actions the runtime accepts per stage type (mirrors complete_workflow_task / _system_route).
_ALLOWED_ACTIONS = {
    'User Task': ['Complete', 'Reject', 'Return'],
    'Approval': ['Approve', 'Reject', 'Return'],
    'System Action': ['Success', 'Error'],
    'Condition': ['True', 'False'],
}


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _stage_config(stage):
    return _as_dict(stage.get('config', stage.get('config_json')))


def _route_action(edge):
    condition = _as_dict(edge.get('condition', edge.get('condition_json')))
    return str(condition.get('action') or edge.get('transition_label') or '')


def _select_route(edges, action):
    """Mirror of the runtime ``_next_stage`` selection, returning the target name."""
    if not edges:
        return None
    selected = None
    if action:
        for edge in edges:
            if _route_action(edge).casefold() == action.casefold():
                selected = edge
                break
    if not selected and len(edges) == 1 and (action or 'Complete') in {'Complete', 'Approve'}:
        selected = edges[0]
    return selected['to_stage'] if selected else None


def _allowed_actions(stage_type):
    return list(_ALLOWED_ACTIONS.get(stage_type, []))


def _error(steps, message):
    return {'steps': steps, 'status': 'error', 'waiting_stage': None,
            'allowed_actions': [], 'outcome': None, 'errors': [message]}


def simulate_workflow(stages, transitions, decisions):
    stages_by_name = {row['name']: row for row in stages}
    edges_by_from = {}
    for edge in transitions:
        edges_by_from.setdefault(edge['from_stage'], []).append(edge)
    for name in edges_by_from:
        edges_by_from[name].sort(key=lambda e: e.get('sequence_no') or 0)
    decisions = [d for d in (decisions or []) if isinstance(d, dict)]

    starts = [row for row in stages if row.get('stage_type') == 'Start']
    if len(starts) != 1:
        return _error([], 'گردش‌کار باید دقیقاً یک مرحلهٔ شروع داشته باشد.')

    steps = []
    current = starts[0]['name']
    pointer = 0
    outcome = None
    status = 'needs_decision'
    waiting_stage = None

    for _ in range(MAX_STEPS):
        stage = stages_by_name.get(current)
        if stage is None:
            return _error(steps, 'مرحله‌ای در این گردش‌کار یافت نشد.')
        kind = stage.get('stage_type')
        title = stage.get('stage_title') or current
        if kind == 'End':
            steps.append({'stage': current, 'title': title, 'stage_type': kind,
                          'action': None, 'next': None})
            outcome = _stage_config(stage).get('outcome')
            status = 'finished'
            break
        if kind == 'Start':
            next_stage = _select_route(edges_by_from.get(current, []), None)
            if not next_stage:
                return _error(steps, 'مسیر خروجی مرحلهٔ شروع تعریف نشده است.')
            steps.append({'stage': current, 'title': title, 'stage_type': kind,
                          'action': None, 'next': next_stage})
            current = next_stage
            continue
        if kind == 'Wait':
            return _error(steps, 'اجرای مرحلهٔ انتظار هنوز پشتیبانی نمی‌شود؛ آن را جایگزین کنید.')

        if pointer < len(decisions) and decisions[pointer].get('stage') == current:
            action = decisions[pointer].get('action')
            pointer += 1
        else:
            steps.append({'stage': current, 'title': title, 'stage_type': kind,
                          'action': None, 'next': None})
            waiting_stage = current
            status = 'needs_decision'
            break

        allowed = _allowed_actions(kind)
        if allowed and action not in allowed:
            return _error(steps, f'اقدام «{action}» برای مرحلهٔ «{title}» معتبر نیست.')
        if kind == 'Condition':
            result = action == 'True'
            try:
                next_stage = select_boolean_transition(
                    [{'to_stage': e['to_stage'], 'condition': _as_dict(e.get('condition', e.get('condition_json')))}
                     for e in edges_by_from.get(current, [])], result)
            except ValueError:
                return _error(steps, 'مسیر خروجی مرحلهٔ شرط کامل نیست.')
        else:
            next_stage = _select_route(edges_by_from.get(current, []), action)
            if not next_stage:
                if action == 'Reject':
                    # The runtime ends the instance as Rejected when Reject has no route.
                    steps.append({'stage': current, 'title': title, 'stage_type': kind,
                                  'action': action, 'next': None})
                    outcome = 'Rejected'
                    status = 'finished'
                    break
                if action == 'Return':
                    return _error(steps, 'مسیر بازگشت تعریف نشده و مرحلهٔ قبلی برای بازگشت در دسترس نیست.')
                return _error(steps, 'مسیر خروجی این مرحله تعریف نشده است.')
        steps.append({'stage': current, 'title': title, 'stage_type': kind,
                      'action': action, 'next': next_stage})
        current = next_stage
    else:
        return _error(steps, 'مسیر بیش از ۲۰۰ مرحله طول کشید؛ احتمالاً حلقه‌ای وجود دارد.')

    return {'steps': steps, 'status': status, 'waiting_stage': waiting_stage,
            'allowed_actions': _allowed_actions(stages_by_name[waiting_stage].get('stage_type'))
            if waiting_stage else [], 'outcome': outcome, 'errors': []}
