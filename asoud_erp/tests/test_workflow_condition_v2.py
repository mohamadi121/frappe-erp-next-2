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
