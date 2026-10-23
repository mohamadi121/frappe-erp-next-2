"""Approval execution registry and parameter overlay contract."""

from copy import deepcopy

import pytest

from asoud_erp.services.form_execution import EXECUTORS, Executor, Result
from asoud_erp.services.form_execution.parameters import collect_parameters


class SampleExecutor:
    KIND = 'test_only'
    LABEL = 'آزمون'
    PARAMETERS = {'amount': {'label': 'مبلغ', 'types': ['Currency'], 'required': True}}

    def build(self, params: dict, ctx: dict) -> dict:
        return {'doctype': 'ToDo', 'description': str(params['amount'])}

    def apply(self, request, params: dict) -> Result:
        return Result(status='Created', doctype='ToDo', name='test-document')


def test_registry_accepts_executor_modules_and_reuses_native_result(monkeypatch):
    executor = SampleExecutor()
    assert isinstance(executor, Executor)
    monkeypatch.setitem(EXECUTORS, executor.KIND, executor)
    assert EXECUTORS['test_only'].build({'amount': 12}, {}) == {
        'doctype': 'ToDo', 'description': '12'}
    from asoud_erp.services.request_templates.base import NativeResult

    assert EXECUTORS['test_only'].apply(None, {'amount': 12}) == NativeResult(
        status='Created', doctype='ToDo', name='test-document')


def test_completed_steps_overlay_request_in_completion_order_without_mutation():
    fields = [{'key': 'asked', 'execution_key': 'amount'}, {'key': 'private'}]
    request_values = {'asked': 100, 'private': 'confidential'}
    tasks = [
        {'name': 'later', 'status': 'Completed', 'completed_on': '2026-01-02 12:00:00',
         'fields': [{'key': 'final', 'execution_key': 'amount'}], 'values': {'final': 70}},
        {'name': 'earlier', 'status': 'Completed', 'completed_on': '2026-01-02 11:00:00',
         'fields': [{'key': 'initial', 'execution_key': 'amount'}], 'values': {'initial': 80}},
        {'name': 'pending', 'status': 'Open', 'completed_on': None,
         'fields': [{'key': 'draft', 'execution_key': 'amount'}], 'values': {'draft': 999}},
    ]
    before = deepcopy((fields, request_values, tasks))
    assert collect_parameters(fields, request_values, tasks) == {'amount': 70}
    assert (fields, request_values, tasks) == before


def test_absent_step_values_do_not_erase_request_but_explicit_empty_values_do():
    fields = [{'key': 'request_amount', 'execution_key': 'amount'},
              {'key': 'reason', 'execution_key': 'purpose'}]
    tasks = [{'name': 'step', 'status': 'Completed', 'completed_on': '2026-01-01 12:00:00',
              'fields': [{'key': 'approved', 'execution_key': 'amount'},
                         {'key': 'note', 'execution_key': 'purpose'}], 'values': {'note': None}}]
    assert collect_parameters(fields, {'request_amount': 0, 'reason': 'متن'}, tasks) == {
        'amount': 0, 'purpose': None}


def test_all_completed_tasks_contribute_even_when_they_repeat_a_stage():
    tasks = [
        {'name': 'first', 'status': 'Completed', 'completed_on': '2026-01-01 12:00:00',
         'fields': [{'key': 'answer', 'execution_key': 'purpose'}], 'values': {'answer': 'اول'}},
        {'name': 'second', 'status': 'Completed', 'completed_on': '2026-01-02 12:00:00',
         'fields': [{'key': 'answer', 'execution_key': 'purpose'}], 'values': {'answer': 'دوم'}},
        {'name': 'cancelled', 'status': 'Cancelled', 'completed_on': '2026-01-03 12:00:00',
         'fields': [{'key': 'answer', 'execution_key': 'purpose'}], 'values': {'answer': 'لغو'}},
    ]
    assert collect_parameters([], {}, tasks) == {'purpose': 'دوم'}


def test_false_and_empty_string_values_are_preserved():
    fields = [{'key': 'check', 'execution_key': 'flag'}, {'key': 'note', 'execution_key': 'purpose'}]
    assert collect_parameters(fields, {'check': False, 'note': ''}, []) == {'flag': False, 'purpose': ''}


def test_completed_task_without_completion_time_is_rejected():
    with pytest.raises(ValueError, match='زمان تکمیل'):
        collect_parameters([], {}, [{'name': 'broken', 'status': 'Completed', 'completed_on': None,
                                      'fields': [], 'values': {}}])


@pytest.fixture
def executor_schema(monkeypatch):
    monkeypatch.setitem(EXECUTORS, 'test_only', SampleExecutor())
    return {'kind': 'Request', 'execution': {'kind': 'test_only'},
            'sections': [{'fields': [{'key': 'asked', 'type': 'Currency',
                                      'execution_key': 'amount'}]}]}


def test_execution_schema_accepts_known_kind_and_mapping(executor_schema):
    from asoud_erp.services.form_execution.schema import validate_execution

    assert validate_execution(executor_schema) is None


@pytest.mark.parametrize(('change', 'message'), [
    ('unknown_kind', 'نوع اجرا'), ('document', 'درخواست'),
    ('unknown_parameter', 'پارامتر'), ('duplicate', 'تکراری'),
    ('missing_required', 'الزامی'), ('wrong_type', 'نوع فیلد'),
    ('no_execution', 'نوع اجرا'), ('invalid_execution', 'نوع اجرا'),
])
def test_execution_schema_rejects_invalid_mapping(executor_schema, change, message):
    from asoud_erp.services.form_execution.schema import validate_execution

    field = executor_schema['sections'][0]['fields'][0]
    if change == 'unknown_kind':
        executor_schema['execution']['kind'] = 'unknown'
    elif change == 'document':
        executor_schema['kind'] = 'Document'
    elif change == 'unknown_parameter':
        field['execution_key'] = 'unknown'
    elif change == 'duplicate':
        executor_schema['sections'][0]['fields'].append({**field, 'key': 'second'})
    elif change == 'missing_required':
        field.pop('execution_key')
    elif change == 'wrong_type':
        field['type'] = 'Date'
    elif change == 'no_execution':
        executor_schema.pop('execution')
    elif change == 'invalid_execution':
        executor_schema['execution'] = []
    with pytest.raises(ValueError, match=message):
        validate_execution(executor_schema)


def test_execution_schema_preserves_legacy_forms():
    from asoud_erp.services.form_execution.schema import validate_execution

    assert validate_execution({'kind': 'Request', 'sections': [{'fields': []}]}) is None


def test_stage_fields_retain_execution_mapping_and_validate_keys(monkeypatch):
    from asoud_erp.services.workflow_stage_policy import _normalize_form_fields

    monkeypatch.setitem(EXECUTORS, 'test_only', SampleExecutor())
    fields = [{'key': 'approved', 'label': 'مبلغ مصوب', 'type': 'Currency', 'execution_key': 'amount'}]
    assert _normalize_form_fields(fields)[0]['execution_key'] == 'amount'
    fields[0]['execution_key'] = 'unknown'
    with pytest.raises(ValueError, match='پارامتر'):
        _normalize_form_fields(fields)


def test_form_entry_reference_lookup_is_indexed():
    import json
    from pathlib import Path

    path = Path(__file__).parents[1] / 'asoud_erp/doctype/asoud_form_entry/asoud_form_entry.json'
    fields = {field['fieldname']: field for field in json.loads(path.read_text())['fields']}
    assert fields['reference_name'].get('search_index') == 1
    assert fields['reference_doctype'].get('search_index') == 1


def test_registered_executor_parameter_types_are_form_schema_types():
    import ast
    from pathlib import Path

    # Read the constant without loading the site-dependent schema module.
    module = ast.parse((Path(__file__).parents[1] / 'services/form_schema.py').read_text())
    TYPES = next(ast.literal_eval(node.value) for node in module.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'TYPES' for target in node.targets))

    assert {'employee_advance', 'attendance_correction', 'asset_movement'} <= set(EXECUTORS)
    for kind, executor in EXECUTORS.items():
        for key, parameter in executor.PARAMETERS.items():
            assert parameter['types'], (kind, key)
            assert set(parameter['types']) <= TYPES, (kind, key, parameter['types'])
