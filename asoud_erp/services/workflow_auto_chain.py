"""Automatic stages (Condition, System Action) must not loop forever without a person or a wait.

A chain of automatic stages that never reaches a human task, a Wait or an End visits
each stage at most once, so it can never be longer than the number of automatic stages in
the graph. A longer chain is therefore a proven cycle and is stopped.
"""

AUTO_STAGE_TYPES = {'Condition', 'System Action'}
# Activities written when an automatic stage finishes; any other activity (task
# completed, wait resumed, start) breaks the chain.
AUTO_ACTIONS = ('Condition True', 'Condition False', 'System Action Succeeded',
                'System Action Failed', 'Automatic Succeeded', 'Automatic Completed With Errors')
AUTO_LOOP = 'مسیرهای خودکار این گردش‌کار به یک حلقهٔ بی‌پایان رسید و متوقف شد؛ مدیر گردش‌کار باید مسیر شرط و اقدام خودکار را بازبینی کند.'
AUTO_CYCLE_DESIGN = 'حلقه‌ای که فقط از مراحل شرط و اقدام خودکار ساخته شده است مجاز نیست؛ میان آن‌ها یک وظیفه یا انتظار قرار دهید.'


def chain_limit(auto_stage_count: int) -> int:
    """Longest possible acyclic automatic chain: every automatic stage once."""
    return max(int(auto_stage_count), 1)


def chain_too_long(finished_hops: int, auto_stage_count: int) -> bool:
    """True when entering one more automatic stage would revisit one: the hops already
    finished since the last human or wait step have used every automatic stage."""
    return finished_hops >= chain_limit(auto_stage_count)


def auto_cycle_stages(stages, transitions) -> set:
    """Stage names that lie on a cycle made only of automatic stages."""
    auto = {row['name'] for row in stages if row['stage_type'] in AUTO_STAGE_TYPES}
    graph = {name: set() for name in auto}
    for edge in transitions:
        if edge['from_stage'] in auto and edge['to_stage'] in auto:
            graph[edge['from_stage']].add(edge['to_stage'])
    reach = {}
    for start in auto:
        seen, pending = set(), list(graph[start])
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(graph[node])
        reach[start] = seen
    return {name for name in auto if name in reach[name]}
