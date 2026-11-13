import pytest

from asoud_erp.services.workflow_condition import (
    evaluate_group,
    guaranteed_predecessors,
    normalize_group,
    normalize_text,
)


def rule(**values):
    return dict(id='c1', source_kind='Original', source_field='amount',
        field_type='Number', operator='Greater Than', value='50', **values)


def config(*conditions, combine='All'):
    return dict(title='شرط و مسیر', condition_version=2, combine=combine, conditions=list(conditions))


def test_decimal_precision_and_inclusive_range():
    row = rule()
    row.update(operator='Between', value='0.100000000000000001', value_to='0.100000000000000003')
    normalized = normalize_group(config(row))
    assert evaluate_group(normalized, lambda _: '0.100000000000000001') is True
    assert evaluate_group(normalized, lambda _: '0.100000000000000004') is False


@pytest.mark.parametrize('combine,expected', [('All', False), ('Any', True)])
def test_combination(combine, expected):
    one, two = rule(), rule()
    two.update(id='c2', source_field='other')
    normalized = normalize_group(config(one, two, combine=combine))
    assert evaluate_group(normalized, lambda row: '100' if row['id'] == 'c1' else '20') is expected


def test_any_does_not_hide_invalid_source_data():
    one, two = rule(), rule()
    two['id'] = 'c2'
    normalized = normalize_group(config(one, two, combine='Any'))
    with pytest.raises(ValueError):
        evaluate_group(normalized, lambda row: '100' if row['id'] == 'c1' else 'NaN')


def test_date_range_and_invalid_range():
    row = rule()
    row.update(field_type='Date', operator='Between', value='2026-01-01', value_to='2026-01-31')
    assert evaluate_group(normalize_group(config(row)), lambda _: '2026-01-31') is True
    row['value_to'] = '2025-12-01'
    with pytest.raises(ValueError):
        normalize_group(config(row))


def test_empty_is_not_a_missing_field():
    row = rule()
    row.update(operator='Is Empty', value='discard me')
    normalized = normalize_group(config(row))
    assert 'value' not in normalized['conditions'][0]
    assert evaluate_group(normalized, lambda _: None) is True
    def missing(_):
        raise ValueError('فیلد حذف شده است.')
    with pytest.raises(ValueError):
        evaluate_group(normalized, missing)


def test_type_operator_and_duplicate_ids_rejected():
    row = rule()
    row.update(field_type='Select', operator='Contains')
    with pytest.raises(ValueError):
        normalize_group(config(row))
    with pytest.raises(ValueError):
        normalize_group(config(rule(), rule()))


def test_text_and_persian_numbers():
    row = rule()
    row.update(value='۵۰٫۵')
    assert evaluate_group(normalize_group(config(row)), lambda _: '۵۱') is True
    row.update(field_type='Text', operator='Not Contains', value='فوری')
    assert evaluate_group(normalize_group(config(row)), lambda _: 'عادی') is True


def test_row_identity_and_order_remain_stable():
    rows = [rule() for _ in range(6)]
    for i, row in enumerate(rows):
        row['id'] = f'c{i}'
    rows.pop(2)
    assert [row['id'] for row in normalize_group(config(*rows))['conditions']] == ['c0', 'c1', 'c3', 'c4', 'c5']


def test_optional_branch_is_not_a_guaranteed_previous_action():
    stages = [dict(name='START', stage_type='Start'), dict(name='A', stage_type='User Task'),
        dict(name='OPTIONAL', stage_type='User Task'), dict(name='GATE', stage_type='Condition')]
    edges = [dict(from_stage='START', to_stage='A'), dict(from_stage='A', to_stage='OPTIONAL'),
        dict(from_stage='OPTIONAL', to_stage='GATE'), dict(from_stage='A', to_stage='GATE')]
    assert guaranteed_predecessors(stages, edges, 'GATE') == {'A'}
    edges.append(dict(from_stage='GATE', to_stage='A'))
    assert guaranteed_predecessors(stages, edges, 'GATE') == {'A'}


def test_six_conditions_and_every_numeric_operator():
    for operator in ['Equals', 'Not Equals', 'Greater Than', 'Greater Or Equal', 'Less Than', 'Less Or Equal']:
        row = rule()
        row.update(operator=operator)
        assert isinstance(evaluate_group(normalize_group(config(row)), lambda _: '50'), bool)
    rows = [dict(rule(), id=f'item{i}') for i in range(6)]
    assert len(normalize_group(config(*rows))['conditions']) == 6


def text_rule(operator, value, actual):
    row = rule()
    row.update(field_type='Text', operator=operator, value=value)
    return evaluate_group(normalize_group(config(row)), lambda _: actual)


def test_normalize_text_unifies_persian_and_spaces():
    assert normalize_text('درخواست خريد') == normalize_text('درخواست خرید')
    assert normalize_text('می‌خواهم') == normalize_text('می خواهم')
    assert normalize_text('  ERP   ') == 'erp'
    assert normalize_text('خرید  تجهیزات') == 'خرید تجهیزات'
    # diacritics, digits and ه/ة/أ/ا are untouched
    assert normalize_text('مَبل ۵۰') == 'مَبل ۵۰'


def test_text_contains_matches_normalized_substrings():
    actual = 'درخواست خرید تجهیزات کامپیوتری'
    assert text_rule('Contains', 'تجهیزات', actual) is True
    assert text_rule('Contains', 'خرید تجهیزات', actual) is True
    assert text_rule('Contains', 'مبلمان', actual) is False
    assert text_rule('Not Contains', 'مبلمان', actual) is True
    assert text_rule('Not Contains', 'خرید تجهیزات', actual) is False


def test_text_equals_ignores_arabic_ya_ka_zwnj_spaces_and_case():
    assert text_rule('Equals', 'خرید', 'درخواست خريد') is False
    assert text_rule('Equals', 'خرید', 'خرید') is True
    assert text_rule('Equals', 'می‌خواهم', 'می خواهم') is True
    assert text_rule('Equals', 'خرید  تجهیزات', 'خرید تجهیزات') is True
    assert text_rule('Equals', 'ERP', 'erp') is True
    assert text_rule('Not Equals', 'خرید', 'خرید') is False


def test_text_equals_unifies_arabic_ya_and_kaf():
    # خريد uses Arabic ya U+064A, كالا uses Arabic kaf U+0643
    assert text_rule('Equals', 'خرید', 'خريد') is True
    assert text_rule('Equals', 'کالا', 'كالا') is True
    # ى U+0649 in the actual value matches a search for ی
    assert text_rule('Contains', 'ی', 'درخواست ىادداشت') is True
    assert text_rule('Not Equals', 'خرید', 'فروش') is True


def test_whitespace_only_text_value_rejected():
    row = rule()
    row.update(field_type='Text', operator='Contains', value='   ')
    with pytest.raises(ValueError, match='مقدار مقایسه وارد نشده است'):
        normalize_group(config(row))


def test_number_and_select_are_not_text_normalized():
    row = rule()
    row.update(field_type='Select', operator='Equals', value='ERP')
    assert evaluate_group(normalize_group(config(row)), lambda _: 'erp') is False
    assert evaluate_group(normalize_group(config(row)), lambda _: 'ERP') is True
    assert evaluate_group(normalize_group(config(rule())), lambda _: ' 51 ') is True
    assert evaluate_group(normalize_group(config(rule())), lambda _: ' 49 ') is False
@pytest.mark.parametrize('kind,actual,value,expected', [
    ('Boolean', False, 'false', True), ('Boolean', True, 'false', False),
    ('DateTime', '2026-11-19T12:10:00', '2026-11-19T12:10:00', True),
    ('Time', '12:10:00', '12:10', True),
])
def test_additional_real_form_scalar_types(kind, actual, value, expected):
    raw = {'condition_version': 2, 'combine': 'All', 'conditions': [{
        'id': 'typed', 'source_kind': 'Original', 'source_field': 'field',
        'field_type': kind, 'operator': 'Equals', 'value': value}]}
    assert evaluate_group(raw, lambda _: actual) is expected


@pytest.mark.parametrize('actual,expected', [(['a', 'b'], True), (['b'], False), ([], False)])
def test_multiselect_compares_option_ids_not_string_fragments(actual, expected):
    raw = config(dict(id='tags', source_kind='Original', source_field='tags',
        field_type='MultiSelect', operator='Contains', value='a'))
    assert evaluate_group(raw, lambda _: actual) is expected
    if actual:
        raw['conditions'][0]['operator'] = 'Not Contains'
        assert evaluate_group(raw, lambda _: actual) is not expected


@pytest.mark.parametrize('actual', [None, '', 0, False])
def test_null_zero_and_false_are_not_conflated(actual):
    row = dict(id='value', source_kind='Original', source_field='field', field_type='Text', operator='Is Empty')
    assert evaluate_group(config(row), lambda _: actual) is (actual is None or actual == '')


def test_long_action_reports_are_compared_without_truncating_the_source():
    row = dict(id='report', source_kind='Stage', source_stage='action', source_field='action_note',
        field_type='Text', operator='Contains', value='پایان گزارش')
    assert evaluate_group(config(row), lambda _: 'متن ' * 1000 + 'پایان گزارش') is True


def test_native_time_values_keep_clock_semantics():
    from datetime import timedelta

    row = dict(id='clock', source_kind='Original', source_field='clock',
        field_type='Time', operator='Equals', value='08:15:00')
    assert evaluate_group(config(row), lambda _: timedelta(hours=8, minutes=15)) is True
    for invalid in (timedelta(days=1), timedelta(seconds=-1)):
        with pytest.raises(ValueError):
            evaluate_group(config(row), lambda _: invalid)
