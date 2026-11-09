"""Read-only validity check for a stored workflow graph.

Reuses the existing readiness engine (``activation_requirements``) for the rules
it already owns and adds only the graph-shape checks that engine does not cover
(self-loops, no-exit loops, disabled-decision routes, deleted form references).
"""
import json

from asoud_erp.services.workflow_contract import DISCONNECTED_PATHS, activation_requirements
from asoud_erp.services.workflow_simulation import ACTION_LABELS

# Readiness-engine messages -> stable issue codes (the engine owns these rules).
_READINESS_CODES = {
    'گردش‌کار باید یک شروع و دست‌کم یک پایان داشته باشد.': 'start_end_missing',
    'یکی از مسیرها به مرحله‌ای خارج از این گردش‌کار متصل است.': 'route_external',
    'اجرای مرحلهٔ انتظار هنوز پشتیبانی نمی‌شود؛ آن را جایگزین کنید.': 'wait_unsupported',
    'تنظیمات یا مسیر خروج یکی از مراحل کامل و معتبر نیست.': 'stage_invalid',
    DISCONNECTED_PATHS: 'disconnected',
}
# Runtime defaults when a saved config omits the flag (mirrors normalize_stage_config).
_DECISION_DEFAULTS = {
    'User Task': {'allow_reject': False, 'allow_return': False},
    'Approval': {'allow_reject': True, 'allow_return': True},
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


def _config(row):
    return _as_dict(row.get('config', row.get('config_json')))


def _route_action(edge):
    condition = _as_dict(edge.get('condition', edge.get('condition_json')))
    return str(condition.get('action') or edge.get('transition_label') or '')


def _outgoing(stages, transitions):
    """(targets, edges) maps keyed by stage name; external references are skipped."""
    names = {row['name'] for row in stages}
    targets = {name: [] for name in names}
    edges = {name: [] for name in names}
    for edge in transitions:
        if edge['from_stage'] in names and edge['to_stage'] in names:
            targets[edge['from_stage']].append(edge['to_stage'])
            edges[edge['from_stage']].append(edge)
    return targets, edges


def _can_reach_end(targets, ends):
    reverse = {name: [] for name in targets}
    for name, to_stages in targets.items():
        for to_stage in to_stages:
            reverse[to_stage].append(name)
    seen = set(ends)
    stack = list(ends)
    while stack:
        node = stack.pop()
        for parent in reverse[node]:
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def _in_cycle(targets):
    """Stages that can reach themselves (members of some cycle)."""
    result = set()
    for name in targets:
        seen = set()
        stack = list(targets[name])
        while stack:
            node = stack.pop()
            if node == name:
                result.add(name)
                break
            if node in seen:
                continue
            seen.add(node)
            stack.extend(targets[node])
    return result


def referenced_forms(stages):
    """Form names a stage config points at (submission source, result or supplementary form)."""
    forms = set()
    for row in stages:
        config = _config(row)
        for key in ('submission_source', 'result_form', 'supplementary_form'):
            value = config.get(key)
            if isinstance(value, dict) and isinstance(value.get('form'), str) and value['form']:
                forms.add(value['form'])
    return forms


def validate_workflow(stages, transitions, existing_forms=None):
    issues = []
    for message in activation_requirements(stages, transitions):
        issues.append({'code': _READINESS_CODES.get(message, 'readiness'),
                       'severity': 'error', 'message': message,
                       'stage': None, 'route': None})
    targets, edges = _outgoing(stages, transitions)
    ends = {row['name'] for row in stages if row['stage_type'] == 'End'}
    can_finish = _can_reach_end(targets, ends)
    cyclic = _in_cycle(targets)
    for row in stages:
        name, kind = row['name'], row['stage_type']
        title = row.get('stage_title') or name
        if name in targets[name]:
            issues.append({'code': 'self_loop', 'severity': 'warning',
                           'message': f'مرحلهٔ «{title}» به خودش وصل شده است؛ این یک حلقهٔ بازگشتی است.',
                           'stage': name, 'route': None})
        if name in cyclic and name not in can_finish:
            issues.append({'code': 'loop_no_exit', 'severity': 'error',
                           'message': f'مرحلهٔ «{title}» در حلقه‌ای قرار دارد که راهی به پایان ندارد.',
                           'stage': name, 'route': None})
        defaults = _DECISION_DEFAULTS.get(kind)
        if defaults:
            config = _config(row)
            for flag, action in (('allow_reject', 'Reject'), ('allow_return', 'Return')):
                if config.get(flag, defaults[flag]) is False:
                    if any(_route_action(e).casefold() == action.casefold() for e in edges[name]):
                        issues.append({'code': 'disabled_decision_route', 'severity': 'warning',
                                       'message': f'مسیر «{ACTION_LABELS.get(action, action)}» در مرحلهٔ «{title}» غیرفعال است؛ این اقدام در آن مرحله ممکن نیست.',
                                       'stage': name, 'route': action})
        if existing_forms is not None:
            for form in sorted(referenced_forms([row])):
                if form not in existing_forms:
                    issues.append({'code': 'form_missing', 'severity': 'error',
                                   'message': f'فرم متصل به مرحلهٔ «{title}» دیگر در دسترس نیست.',
                                   'stage': name, 'route': None})
    return {'ok': not any(issue['severity'] == 'error' for issue in issues), 'issues': issues}
