import json

ALLOWED_WORKFLOW_STATUSES = {"Active", "Inactive", "Archived"}
DISCONNECTED_PATHS = 'همهٔ مراحل باید از شروع قابل دسترس و به یک پایان متصل باشند.'


def is_system_workflow(row):
    return (row.get('is_system_template') in (True, 1, '1') or bool(row.get('template_key'))
            or str(row.get('workflow_code') or '').upper().startswith('SYS-')
            or str(row.get('name') or '').upper().startswith('SYS-'))


def _validate_saved_stage(row):
    from asoud_erp.services.workflow_stage_policy import normalize_stage_config

    config = json.loads(row.get('config_json') or '{}')
    if not isinstance(config, dict) or row.get('configuration_status') != 'Complete':
        raise ValueError
    if row['stage_type'] == 'Start':
        if config.get('trigger_type') not in {'Manual', 'Document Event', 'System', 'API'}:
            raise ValueError
        if config.get('trigger_type') == 'Manual' and not config.get('initiator_roles'):
            raise ValueError
        if config.get('start_settings_version') == 1:
            from asoud_erp.services.workflow_start_policy import normalize_settings

            normalize_settings({key: config[key] for key in ('trigger_type', 'initiator_roles',
                'submission_source', 'allow_manager_restart', 'require_manual_reason') if key in config})
    else:
        normalize_stage_config(row['stage_type'], {'title': row.get('stage_title') or 'مرحله',
            **({'outcome': 'Completed'} if row['stage_type'] == 'End' else {}), **config})


def _validate_saved_routes(kind, routes):
    conditions = [json.loads(edge.get('condition_json') or '{}') for edge in routes]
    if any(not isinstance(value, dict) for value in conditions):
        raise ValueError
    if kind == 'End':
        if routes:
            raise ValueError
    elif kind == 'Condition':
        if (len(conditions) != 2 or any(type(c.get('result')) is not bool for c in conditions)
                or {c['result'] for c in conditions} != {True, False}):
            raise ValueError
    elif kind == 'Start':
        if len(routes) != 1:
            raise ValueError
    elif kind == 'Wait':
        if len(routes) != 1 or conditions != [{}]:
            raise ValueError
    elif kind in {'User Task', 'Approval', 'System Action'}:
        main = {'User Task': 'Complete', 'Approval': 'Approve', 'System Action': 'Success'}[kind]
        actions = [str(c.get('action') or e.get('transition_label') or '').casefold()
                   for c, e in zip(conditions, routes)]
        if actions.count(main.casefold()) != 1 and not (len(routes) == 1 and actions == ['']):
            raise ValueError
        if len(actions) != len(set(actions)):
            raise ValueError
        allowed = {'User Task': {'complete', 'reject', 'return'},
            'Approval': {'approve', 'reject', 'return'}, 'System Action': {'success', 'error'}}[kind]
        if any(action not in allowed for action in actions) and not (len(routes) == 1 and actions == ['']):
            raise ValueError


def activation_requirements(stages, transitions):
    """Validate saved graph against the existing runtime, without changing it."""
    errors = []
    names = {row['name'] for row in stages}
    starts = [row['name'] for row in stages if row['stage_type'] == 'Start']
    ends = {row['name'] for row in stages if row['stage_type'] == 'End'}
    if len(starts) != 1 or not ends:
        errors.append('گردش‌کار باید یک شروع و دست‌کم یک پایان داشته باشد.')
    outgoing = {name: [] for name in names}
    for edge in transitions:
        if edge['from_stage'] not in names or edge['to_stage'] not in names:
            errors.append('یکی از مسیرها به مرحله‌ای خارج از این گردش‌کار متصل است.')
            continue
        outgoing[edge['from_stage']].append(edge)
    for row in stages:
        kind, name = row['stage_type'], row['name']
        try:
            _validate_saved_stage(row)
            _validate_saved_routes(kind, outgoing[name])
            if kind == 'Wait' and json.loads(row.get('config_json') or '{}').get('wait_version') != 1:
                # Legacy waits require explicit conversion to the executable v1 contract.
                errors.append('اجرای مرحلهٔ انتظار هنوز پشتیبانی نمی‌شود؛ آن را جایگزین کنید.')
        except (ValueError, TypeError, KeyError):
            errors.append('تنظیمات یا مسیر خروج یکی از مراحل کامل و معتبر نیست.')
    if len(starts) == 1:
        reached, pending = set(), [starts[0]]
        while pending:
            node = pending.pop()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(e['to_stage'] for e in outgoing[node])
        can_finish = set(ends)
        while True:
            expanded = can_finish | {e['from_stage'] for e in transitions if e['to_stage'] in can_finish}
            if expanded == can_finish:
                break
            can_finish = expanded
        if reached != names or can_finish != names:
            errors.append(DISCONNECTED_PATHS)
    return list(dict.fromkeys(errors))


def design_details_summary(stages, transitions):
    """Read-only presentation of the same checks; never trusts stale Pending text."""
    requirements = activation_requirements(stages, transitions)
    names = {row['name'] for row in stages}
    stages_complete = (sum(row['stage_type'] == 'Start' for row in stages) == 1
                       and any(row['stage_type'] == 'End' for row in stages))
    for row in stages:
        try:
            _validate_saved_stage(row)
            if row['stage_type'] == 'Wait' and json.loads(row.get('config_json') or '{}').get('wait_version') != 1:
                stages_complete = False
        except (ValueError, TypeError, KeyError):
            stages_complete = False
    routes_complete = bool(names) and sum(row['stage_type'] == 'Start' for row in stages) == 1
    for row in stages:
        try:
            _validate_saved_routes(row['stage_type'],
                [edge for edge in transitions if edge['from_stage'] == row['name']])
        except (ValueError, TypeError, KeyError):
            routes_complete = False
    if any(edge['from_stage'] not in names or edge['to_stage'] not in names for edge in transitions):
        routes_complete = False
    # The existing validator owns reachability; do not duplicate traversal policy.
    if DISCONNECTED_PATHS in requirements:
        routes_complete = False
    return {'steps_count': sum(row['stage_type'] != 'Start' for row in stages),
        'stages_complete': stages_complete, 'routes_complete': routes_complete,
        'requirements': requirements}


def serialize_workflow(row: dict) -> dict:
    result = dict(row)
    result["missing_requirements"] = json.loads(
        result.pop("missing_requirements_json") or "[]"
    )
    result["is_locked"] = result["readiness_status"] != "Ready"
    return result
