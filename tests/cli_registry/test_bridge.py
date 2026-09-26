"""Tests for the ``cli:`` subprocess bridge (:mod:`repolish.cli_registry`).

These tests pin the quarantine's behavior so the v2 removal knows exactly
what goes away with it.
"""

import json
import subprocess
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.cli_registry import run_provider_link
from repolish.config.models import ProviderFileInfo


@pytest.mark.parametrize(
    ('exception', 'should_raise'),
    [
        (None, False),  # Success case
        (subprocess.CalledProcessError(1, 'mylib-link'), True),  # Command fails
    ],
)
def test_run_provider_link_error_handling(
    exception: subprocess.CalledProcessError | None,
    *,
    should_raise: bool,
    mocker: pytest_mock.MockerFixture,
):
    """Test run_provider_link handles success and failure cases."""
    provider_info_data = {
        'resources_dir': '.repolish/mylib',
        'site_package_dir': '/fake/source/mylib',
    }

    mock_run = mocker.patch('subprocess.run')

    if exception is None:
        # Success case
        mock_info = MagicMock()
        mock_info.stdout = json.dumps(provider_info_data)
        mock_link = MagicMock()
        mock_run.side_effect = [mock_info, mock_link]

        result = run_provider_link('mylib', 'mylib-link')

        assert isinstance(result, ProviderFileInfo)
        assert result.resources_dir == '.repolish/mylib'
        assert mock_run.call_count == 2

        # Verify --info call
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ['mylib-link', '--info']
        assert first_call[1]['capture_output'] is True
        assert first_call[1]['text'] is True
        assert first_call[1]['check'] is True

        # Verify link call
        second_call = mock_run.call_args_list[1]
        assert second_call[0][0] == ['mylib-link']
        assert second_call[1]['check'] is True
    else:
        # Error case
        mock_run.side_effect = exception

        if should_raise:
            with pytest.raises(type(exception)):
                run_provider_link('mylib', 'mylib-link')
        else:
            result = run_provider_link('mylib', 'mylib-link')
            assert isinstance(result, ProviderFileInfo)


def test_run_provider_link_passes_location_context(
    mocker: pytest_mock.MockerFixture,
):
    """run_provider_link passes REPOLISH_LINK_CONTEXT env var when location_context is set."""
    provider_info_data = {
        'resources_dir': '.repolish/mylib',
        'site_package_dir': '/fake/source/mylib',
    }

    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(provider_info_data)
    mock_link = MagicMock()
    mock_run.side_effect = [mock_info, mock_link]

    result = run_provider_link(
        'mylib',
        'mylib-link',
        location_context='packages/pkg_a',
    )

    assert isinstance(result, ProviderFileInfo)
    assert mock_run.call_count == 2

    # Verify both calls include the env var
    for call in mock_run.call_args_list:
        assert 'env' in call[1]
        assert call[1]['env']['REPOLISH_LINK_CONTEXT'] == 'packages/pkg_a'


def test_run_provider_link_without_location_context(
    mocker: pytest_mock.MockerFixture,
):
    """run_provider_link does not pass REPOLISH_LINK_CONTEXT when location_context is None."""
    provider_info_data = {
        'resources_dir': '.repolish/mylib',
        'site_package_dir': '/fake/source/mylib',
    }

    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(provider_info_data)
    mock_link = MagicMock()
    mock_run.side_effect = [mock_info, mock_link]

    result = run_provider_link('mylib', 'mylib-link', location_context=None)

    assert isinstance(result, ProviderFileInfo)
    # Verify REPOLISH_LINK_CONTEXT is not passed when location_context is None
    for call in mock_run.call_args_list:
        assert 'REPOLISH_LINK_CONTEXT' not in call[1].get('env', {})
