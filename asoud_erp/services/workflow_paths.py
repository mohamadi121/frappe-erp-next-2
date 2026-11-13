"""Safe editing plans for native workflow transitions, not an execution engine."""


def references_any(value, names):
    if isinstance(value, str):
        return value in names
    if isinstance(value, dict):
        return any(references_any(item, names) for item in value.values())
    return isinstance(value, list) and any(references_any(item, names) for item in value)


def removal_plan(stages, transitions, transition):
    nodes = {row['name']: row for row in stages}
    edge = next((row for row in transitions if row['name'] == transition), None)
    if not edge or edge['from_stage'] not in nodes or edge['to_stage'] not in nodes:
        raise ValueError('مسیر انتخاب‌شده دیگر موجود یا معتبر نیست؛ نمودار را تازه کنید.')

    def reachable(seeds, edges):
        following = {}
        for row in edges:
            following.setdefault(row['from_stage'], []).append(row['to_stage'])
        seen, pending = set(seeds), list(seeds)
        while pending:
            for target in following.get(pending.pop(), []):
                if target in nodes and target not in seen:
                    seen.add(target)
                    pending.append(target)
        return seen

    candidates = reachable([edge['to_stage']], transitions)
    remaining = [row for row in transitions if row['name'] != transition]
    # Even a disconnected, pre-existing other branch owns its shared targets.
    protected = (set(nodes) - candidates) | {edge['from_stage']}
    protected |= {name for name, row in nodes.items() if row['stage_type'] == 'Start'}
    removed = candidates - reachable(protected, remaining)
    links = {row['name'] for row in transitions if row['name'] == transition
        or row['from_stage'] in removed or row['to_stage'] in removed}
    return {'stages': sorted(removed), 'transitions': sorted(links)}
