import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

EMPTY_OPERATORS = {'Is Empty', 'Is Set'}
TYPE_OPERATORS = {
    'Number': {'Equals', 'Not Equals', 'Greater Than', 'Greater Or Equal', 'Less Than', 'Less Or Equal', 'Between'},
    'Date': {'Equals', 'Greater Than', 'Less Than', 'Between'},
    'Text': {'Equals', 'Not Equals', 'Contains', 'Not Contains'},
    'Select': {'Equals', 'Not Equals'},
}
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫', '01234567890123456789.')
_TEXT_TRANSLATE = str.maketrans({'ي': 'ی', 'ى': 'ی', 'ك': 'ک', '‌': ' '})
_TEXT_SPACES = re.compile(r'\s+')


def normalize_text(value: str) -> str:
    """Persian-safe comparison form: unify ي/ى/ك, ZWNJ to space, collapse spaces, casefold Latin."""
    return _TEXT_SPACES.sub(' ', value.translate(_TEXT_TRANSLATE)).strip().casefold()


def condition_value(kind, value):
    if kind == 'Number':
        try:
            number = Decimal(str(value).translate(_DIGITS).strip())
            if isinstance(value, bool) or not number.is_finite() or len(str(value)) > 2000 or abs(number.as_tuple().exponent) > 1000:
                raise InvalidOperation
            return number
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('مقدار شرط باید عدد معتبر باشد.') from None
    if kind == 'Date':
        try:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return date.fromisoformat(str(value).translate(_DIGITS))
        except ValueError:
            raise ValueError('تاریخ شرط معتبر نیست.') from None
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('مقدار متنی شرط معتبر نیست.')
    return value


def normalize_group(raw):
    """Additive v2 JSON; legacy single-predicate semantics below stay unchanged."""
    if (not isinstance(raw, dict) or type(raw.get('condition_version')) is not int
            or raw.get('condition_version') != 2 or not isinstance(raw.get('combine'), str)
            or raw.get('combine') not in {'All', 'Any'}):
        raise ValueError('روش ترکیب شروط معتبر نیست.')
    rows = raw.get('conditions')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('تعداد شروط باید بین یک تا پنجاه باشد.')
    result, seen = [], set()
    for index, row in enumerate(rows, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError('ساختار شرط معتبر نیست.')
            identity = row.get('id')
            if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity) or identity in seen:
                raise ValueError('شناسه شرط باید مستقل و غیرتکراری باشد.')
            seen.add(identity)
            source, field = row.get('source_kind'), row.get('source_field')
            if not isinstance(source, str) or source not in {'Original', 'Stage', 'System'} or not isinstance(field, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,139}', field):
                raise ValueError('منبع یا فیلد شرط معتبر نیست.')
            prior = row.get('source_stage') or ''
            if source == 'Stage' and (not isinstance(prior, str) or not prior or len(prior) > 140):
                raise ValueError('اقدام قبلی را انتخاب کنید.')
            kind, operator = row.get('field_type'), row.get('operator')
            if not isinstance(kind, str) or not isinstance(operator, str) or kind not in TYPE_OPERATORS or operator not in TYPE_OPERATORS[kind] | EMPTY_OPERATORS:
                raise ValueError('معیار مقایسه با نوع فیلد سازگار نیست.')
            item = dict(id=identity, source_kind=source, source_stage=prior if source == 'Stage' else '',
                source_field=field, field_type=kind, operator=operator)
            if operator not in EMPTY_OPERATORS:
                if row.get('value') in (None, ''):
                    raise ValueError('مقدار مقایسه وارد نشده است.')
                first = condition_value(kind, row['value'])
                if kind == 'Text' and not normalize_text(str(first)):
                    raise ValueError('مقدار مقایسه وارد نشده است.')
                item['value'] = str(first)
                if operator == 'Between':
                    last = condition_value(kind, row.get('value_to'))
                    if first > last:
                        raise ValueError('ابتدای بازه از انتهای آن بزرگ‌تر است.')
                    item['value_to'] = str(last)
            result.append(item)
        except ValueError as error:
            raise ValueError(f'شرط {index}: {error}') from None
    return dict(condition_version=2, combine=raw['combine'], conditions=result,
        title=str(raw.get('title') or '').strip(), description=str(raw.get('description') or '')[:500])


def evaluate_group(config, resolve):
    config = normalize_group(config)
    results = []
    for row in config['conditions']:
        actual = resolve(row)  # A missing source/field must raise, not return None.
        empty = actual is None or actual == ''
        operator = row['operator']
        if operator in EMPTY_OPERATORS:
            results.append(empty if operator == 'Is Empty' else not empty)
            continue
        if empty:
            results.append(False)
            continue
        left = condition_value(row['field_type'], actual)
        right = condition_value(row['field_type'], row['value'])
        if row['field_type'] == 'Text':
            left, right = normalize_text(str(left)), normalize_text(str(right))
        if operator == 'Between':
            result = right <= left <= condition_value(row['field_type'], row['value_to'])
        elif operator == 'Contains':
            result = right in left
        elif operator == 'Not Contains':
            result = right not in left
        else:
            result = {'Equals': lambda: left == right, 'Not Equals': lambda: left != right,
                'Greater Than': lambda: left > right, 'Greater Or Equal': lambda: left >= right,
                'Less Than': lambda: left < right, 'Less Or Equal': lambda: left <= right}[operator]()
        results.append(result)
    return all(results) if config['combine'] == 'All' else any(results)


def guaranteed_predecessors(stages, edges, target):
    """Graph dominators, not sequence numbers: an optional branch is not a source."""
    kinds = {row['name']: row['stage_type'] for row in stages}
    starts = [name for name, kind in kinds.items() if kind == 'Start']
    if len(starts) != 1 or target not in kinds:
        return set()
    outgoing = {name: set() for name in kinds}
    for edge in edges:
        if edge['from_stage'] in kinds and edge['to_stage'] in kinds:
            outgoing[edge['from_stage']].add(edge['to_stage'])
    reached, pending = set(), [starts[0]]
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend(outgoing[name] - reached)
    if target not in reached:
        return set()
    previous = {name: {p for p in reached if name in outgoing[p]} for name in reached}
    dom = {name: {name} if name == starts[0] else set(reached) for name in reached}
    changed = True
    while changed:
        changed = False
        for name in reached - {starts[0]}:
            parents = previous[name]
            value = {name} | (set.intersection(*(dom[p] for p in parents)) if parents else set())
            if value != dom[name]:
                dom[name] = value
                changed = True
    return {name for name in dom[target] - {target} if kinds[name] == 'User Task'}


def evaluate_condition(operator: str, actual: Any, expected: Any = None) -> bool:
    if operator == "Is Set":
        return actual not in (None, "", [])
    if operator == "Equals":
        return str(actual) == str(expected)
    if operator == "Not Equals":
        return str(actual) != str(expected)
    if operator == "Contains":
        return str(expected) in str(actual or "")
    if operator in {"Greater Than", "Less Than"}:
        try:
            left, right = Decimal(str(actual)), Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("Condition values must be numeric") from error
        return left > right if operator == "Greater Than" else left < right
    raise ValueError("Invalid condition operator")


def select_boolean_transition(transitions: list[dict[str, Any]], result: bool) -> str:
    matches = [
        str(item.get("to_stage") or "")
        for item in transitions
        if isinstance(item.get("condition"), dict)
        and item["condition"].get("result") is result
    ]
    if len(matches) != 1 or not matches[0]:
        raise ValueError("Condition stage must have exactly one transition for each result")
    return matches[0]
