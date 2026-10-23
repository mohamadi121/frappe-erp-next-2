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
