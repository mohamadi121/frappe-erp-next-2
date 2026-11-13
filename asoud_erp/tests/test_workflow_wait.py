from datetime import datetime, timedelta, timezone

import pytest

from asoud_erp.services.workflow_wait_policy import due_time, normalize


def config(**values):
    return normalize({'wait_version': 1, 'title': 'انتظار معتبر', 'wait_type': 'Duration',
        'wait_value': 24, 'wait_unit': 'Hour', **values})


def test_duration_starts_at_entry_and_calendar_day_is_not_always_24_hours():
    entered = datetime(2026, 3, 7, 17, tzinfo=timezone.utc)  # New York noon, pre-DST.
    assert due_time(config(), entered, 'America/New_York') == entered + timedelta(hours=24)
    assert due_time(config(wait_value=1, wait_unit='Day'), entered, 'America/New_York') == entered + timedelta(hours=23)


@pytest.mark.parametrize('value', [0, -1, True, 1.5, 'abc', 3651, None])
def test_bad_durations_fail(value):
    with pytest.raises(ValueError):
        config(wait_value=value)


def test_date_uses_office_timezone_and_rejects_dst_gaps_and_folds():
    now = datetime.now(timezone.utc)
    assert due_time(config(wait_type='Date', wait_value='2026-11-11T09:00'), now, 'Asia/Tehran') == datetime(2026, 11, 11, 5, 30, tzinfo=timezone.utc)
    for value in ['2026-03-08T02:30', '2026-11-01T01:30']:
        with pytest.raises(ValueError, match='مبهم یا ناموجود'):
            due_time(config(wait_type='Date', wait_value=value), now, 'America/New_York')


def test_form_date_offsets_and_datetime_clock_do_not_conflict():
    raw = {'wait_type': 'FormDate', 'date_source': {'source_kind': 'Original', 'source_field': 'starts', 'field_type': 'Date'},
        'clock': '09:00', 'offset_direction': 'Before', 'offset_days': 1}
    now = datetime.now(timezone.utc)
    value = config(**raw)
    assert 'wait_unit' not in value and 'wait_value' not in value
    assert due_time(value, now, 'Asia/Tehran', '2026-12-01') == datetime(2026, 11, 30, 5, 30, tzinfo=timezone.utc)
    raw['date_source']['field_type'] = 'DateTime'
    value = config(**raw)
    assert 'clock' not in value
    assert due_time(value, now, 'Asia/Tehran', '2026-12-01T14:15') == datetime(2026, 11, 30, 10, 45, tzinfo=timezone.utc)
    for invalid in [None, '', 'not a date', False]:
        with pytest.raises(ValueError):
            due_time(value, now, 'Asia/Tehran', invalid)


def test_inactive_settings_are_not_saved_and_legacy_event_is_not_reinterpreted():
    assert 'date_source' not in config(date_source={'source_field': 'old'})
    with pytest.raises(ValueError):
        config(wait_type='Event')


def test_persian_digits_use_existing_digit_adapter_without_removing_minus_or_decimal():
    assert config(wait_value='۲۴')['wait_value'] == 24
    for invalid in ['-۲', '۲٫۵']:
        with pytest.raises(ValueError):
            config(wait_value=invalid)


def test_simulation_waits_without_producing_a_schedule_or_request():
    from asoud_erp.services.workflow_simulation import simulate_workflow

    stages = [{'name': 'start', 'stage_type': 'Start', 'config': {}},
        {'name': 'wait', 'stage_type': 'Wait', 'config': config()},
        {'name': 'end', 'stage_type': 'End', 'config': {'outcome': 'Completed'}}]
    edges = [{'from_stage': 'start', 'to_stage': 'wait', 'condition': {}},
        {'from_stage': 'wait', 'to_stage': 'end', 'condition': {}}]
    result = simulate_workflow(stages, edges, [])
    assert result['status'] == 'waiting'
    assert result['waiting_stage'] == 'wait'
    assert result['allowed_actions'] == []
