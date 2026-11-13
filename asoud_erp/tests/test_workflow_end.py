import pytest

from asoud_erp.services.workflow_stage_policy import normalize_stage_config


@pytest.mark.parametrize('outcome', ['Completed', 'Rejected', 'Cancelled', 'Stopped'])
def test_end_preserves_four_results_and_optional_message(outcome):
    assert normalize_stage_config('End', {'title': ' پایان ', 'outcome': outcome,
        'result_label': ' پیام نتیجه '}) == {'title': 'پایان', 'outcome': outcome, 'result_label': 'پیام نتیجه'}


@pytest.mark.parametrize('raw', [{'title': '', 'outcome': 'Completed'},
    {'title': {}, 'outcome': 'Completed'}, {'title': 'پایان', 'outcome': []},
    {'title': 'پایان', 'outcome': 'unknown'}, {'title': 'پایان', 'outcome': 'Completed', 'result_label': {}},
    {'title': 'پایان', 'outcome': 'Completed', 'result_label': False}])
def test_end_rejects_invalid_title_result_or_message(raw):
    with pytest.raises(ValueError):
        normalize_stage_config('End', raw)
