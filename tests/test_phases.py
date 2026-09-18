"""PhaseTimer tests: recording, accumulation, events, and the timings JSON."""

import json
from pathlib import Path
from unittest import mock

from repolish.phases import PhaseTimer, write_phase_timings


def test_phase_records_positive_duration():
    timer = PhaseTimer()
    with timer.phase('render'):
        sum(i * i for i in range(1000))
    assert timer._durations['render'] > 0


def test_record_accumulates_repeat_names():
    timer = PhaseTimer()
    timer.record('config_load', 10.0)
    timer.record('config_load', 5.0)
    assert timer._durations['config_load'] == 15.0


def test_phase_accumulates_repeat_names():
    timer = PhaseTimer()
    with timer.phase('post_process'):
        pass
    with timer.phase('post_process'):
        pass
    assert len(timer._durations) == 1
    assert timer._durations['post_process'] >= 0


def test_durations_returns_recorded_phases():
    timer = PhaseTimer()
    timer.record('render', 183.0)
    timer.record('post_process', 1400.0)
    assert timer.durations == {'render': 183.0, 'post_process': 1400.0}


def test_durations_is_a_copy():
    timer = PhaseTimer()
    timer.record('render', 183.0)
    timer.durations['render'] = 0.0
    assert timer.durations['render'] == 183.0


def test_write_phase_timings_writes_json_payload(tmp_path: Path):
    timer = PhaseTimer()
    timer.record('render', 183.4)
    timer.record('post_process', 1400.6)
    path = tmp_path / '.repolish' / '_' / 'phase-timings.json'
    result = write_phase_timings(path, 4210.4, [('pkg-alpha', timer)])
    assert result == path
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload == {
        'total_ms': 4210,
        'sessions': [
            {
                'name': 'pkg-alpha',
                'phases': {'render': 183, 'post_process': 1401},
            },
        ],
    }


def test_write_phase_timings_accepts_empty_sessions(tmp_path: Path):
    path = write_phase_timings(tmp_path / 'timings.json', 12.0, [])
    assert json.loads(path.read_text(encoding='utf-8')) == {
        'total_ms': 12,
        'sessions': [],
    }


def test_emit_logs_one_debug_event_per_phase():
    timer = PhaseTimer()
    timer.record('render', 183.4)
    timer.record('staging', 45.2)
    with mock.patch('repolish.phases.logger.debug') as mock_debug:
        timer.emit()
    assert [c.args[0] for c in mock_debug.call_args_list] == [
        'phase_completed',
        'phase_completed',
    ]
    assert mock_debug.call_args_list[0].kwargs == {'phase': 'render', 'ms': 183}
    assert mock_debug.call_args_list[1].kwargs == {'phase': 'staging', 'ms': 45}


def test_emit_noop_without_records():
    with mock.patch('repolish.phases.logger.debug') as mock_debug:
        PhaseTimer().emit()
    mock_debug.assert_not_called()
