"""PhaseTimer tests: recording, accumulation, events, and the report section."""

from unittest import mock

from repolish.phases import PhaseTimer


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


def test_section_formats_ms_and_seconds_in_record_order():
    timer = PhaseTimer()
    timer.record('render', 183.0)
    timer.record('post_process', 1400.0)
    assert timer.section() == 'render 183ms · post-process 1.4s'


def test_section_empty_when_nothing_recorded():
    assert PhaseTimer().section() == ''


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
