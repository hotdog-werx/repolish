import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.linker.decorator import resource_linker, resource_linker_cli

from .conftest import (
    BasicLinkCliFixture,
    MockedPackageDict,
    PackageDictFixture,
)


def _call_with_argv(
    link_cli: Callable[[], None],
    argv: list[str],
    mocker: pytest_mock.MockerFixture,
) -> None:
    """Helper to call decorated function with mocked sys.argv."""
    mocker.patch.object(sys, 'argv', argv)
    link_cli()


def _test_info_mode(
    link_cli: Callable[[], None],
    pkg_root: Path,
    mocker: pytest_mock.MockerFixture,
    capsys: pytest.CaptureFixture[str],
    expected_info: dict[str, Any],
) -> dict[str, Any]:
    """Helper to test --info mode output."""
    mocker.patch.object(sys, 'argv', ['link-cli', '--info'])
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )
    link_cli()

    captured = capsys.readouterr()
    info = json.loads(captured.out)

    for key, value in expected_info.items():
        assert info[key] == value

    return info


def _assert_link_resources_called(
    mock_link_resources: MagicMock,
    expected_source_dir: Path,
    expected_target_dir: Path,
    *,
    expected_force: bool = False,
) -> None:
    """Helper to assert link_resources was called with expected arguments."""
    mock_link_resources.assert_called_once()
    call_args = mock_link_resources.call_args
    assert call_args.kwargs['source_dir'] == expected_source_dir
    assert call_args.kwargs['target_dir'] == expected_target_dir
    assert call_args.kwargs['force'] is expected_force


def test_resource_linker_basic_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
    basic_link_cli: BasicLinkCliFixture,
    mocker: pytest_mock.MockerFixture,
):
    """Test basic usage of resource_linker decorator."""
    monkeypatch.chdir(tmp_path)

    _call_with_argv(basic_link_cli, ['link-cli'], mocker)

    # Verify link_resources was called with correct args
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        Path('.repolish') / 'mylib',
        expected_force=False,
    )


def test_resource_linker_info_mode(
    test_package: PackageDictFixture,
    capsys: pytest.CaptureFixture[str],
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker --info outputs JSON."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        pass

    info = _test_info_mode(
        link_cli,
        test_package['pkg_root'],
        mocker,
        capsys,
        {'library_name': 'mylib', 'templates_dir': 'templates'},
    )

    assert 'source_dir' in info
    assert 'target_dir' in info


def test_resource_linker_custom_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
    basic_link_cli: BasicLinkCliFixture,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker with custom target directory."""
    monkeypatch.chdir(tmp_path)

    custom_target = tmp_path / 'custom' / 'target'

    _call_with_argv(
        basic_link_cli,
        ['link-cli', '--target-dir', str(custom_target)],
        mocker,
    )

    # Verify link_resources was called with custom target
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        custom_target,
        expected_force=False,
    )


def test_resource_linker_force_flag(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
    basic_link_cli: BasicLinkCliFixture,
):
    """Test resource_linker with --force flag."""
    monkeypatch.chdir(tmp_path)

    _call_with_argv(basic_link_cli, ['link-cli', '--force'], mocker)

    # Verify link_resources was called with force=True
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        Path('.repolish') / 'mylib',
        expected_force=True,
    )


def test_resource_linker_custom_templates_subdir(
    test_package: PackageDictFixture,
    capsys: pytest.CaptureFixture[str],
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker with custom templates subdirectory."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
        templates_subdir='custom_templates',
    )
    def link_cli() -> None:
        pass

    _test_info_mode(
        link_cli,
        test_package['pkg_root'],
        mocker,
        capsys,
        {'templates_dir': 'custom_templates'},
    )


def test_resource_linker_calls_wrapped_function(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
):
    """Test resource_linker calls the wrapped function after linking."""
    monkeypatch.chdir(tmp_path)

    called = []

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        called.append(True)

    _call_with_argv(link_cli, ['link-cli'], mocker)

    assert called == [True]


def test_resource_linker_handles_link_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker handles linking errors gracefully."""
    pkg_root = tmp_path / 'mylib'
    pkg_root.mkdir()
    # Don't create resources directory to trigger an error

    monkeypatch.chdir(tmp_path)

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        pass

    mocker.patch.object(sys, 'argv', ['link-cli'])
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )
    with pytest.raises(SystemExit) as exc_info:
        link_cli()

    assert exc_info.value.code == 1


def test_resource_linker_custom_target_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker with custom default_target_base."""
    pkg_root = tmp_path / 'mylib'
    pkg_root.mkdir()
    resources = pkg_root / 'resources'
    resources.mkdir()

    monkeypatch.chdir(tmp_path)

    # Mock link_resources to avoid actual I/O
    mock_link_resources = mocker.patch(
        'repolish.linker.decorator.link_resources',
        return_value=True,
    )

    # Mock _get_package_root BEFORE applying decorator
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
        default_target_base='.libs',
    )
    def link_cli() -> None:
        pass

    mocker.patch.object(sys, 'argv', ['link-cli'])
    link_cli()

    # Verify link_resources was called with custom target base
    _assert_link_resources_called(
        mock_link_resources,
        resources,
        Path('.libs') / 'mylib',
        expected_force=False,
    )


def test_resource_linker_does_not_call_wrapped_in_info_mode(
    test_package: PackageDictFixture,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker doesn't call wrapped function in --info mode."""
    called = []

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        called.append(True)

    mocker.patch.object(sys, 'argv', ['link-cli', '--info'])
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=test_package['pkg_root'],
    )
    link_cli()

    # Wrapped function should NOT be called in --info mode
    assert called == []


@dataclass
class ResourceLinkerCliCase:
    name: str
    package_name: str
    library_name_arg: str | None
    source_dir: str
    expected_lib_name: str
    expected_msg: str


@pytest.mark.parametrize(
    'case',
    [
        ResourceLinkerCliCase(
            name='auto_detection_with_underscore_to_dash',
            package_name='my_library',
            library_name_arg=None,
            source_dir='resources',
            expected_lib_name='my-library',
            expected_msg='`resources` from my-library are now available',
        ),
        ResourceLinkerCliCase(
            name='custom_library_name',
            package_name='mylib',
            library_name_arg='custom-name',
            source_dir='resources',
            expected_lib_name='custom-name',
            expected_msg='`resources` from custom-name are now available',
        ),
        ResourceLinkerCliCase(
            name='custom_source_directory',
            package_name='mylib',
            library_name_arg=None,
            source_dir='templates',
            expected_lib_name='mylib',
            expected_msg='`templates` from mylib are now available',
        ),
    ],
    ids=lambda case: case.name,
)
def test_resource_linker_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
    capsys: pytest.CaptureFixture[str],
    case: ResourceLinkerCliCase,
):
    """Test resource_linker_cli with various configurations."""
    monkeypatch.chdir(tmp_path)

    # Set up package structure
    pkg_root = tmp_path / case.package_name
    pkg_root.mkdir()
    source_path = pkg_root / case.source_dir
    source_path.mkdir()

    # Mock package detection
    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )
    mock_frame = mocker.MagicMock()
    mock_module = mocker.MagicMock()
    mock_module.__package__ = case.package_name
    mocker.patch('inspect.getmodule', return_value=mock_module)
    mocker.patch('inspect.stack', return_value=[None, mock_frame])

    # Mock link_resources
    mock_link = mocker.patch(
        'repolish.linker.decorator.link_resources',
        return_value=True,
    )

    # Create the CLI
    main = resource_linker_cli(
        library_name=case.library_name_arg,
        default_source_dir=case.source_dir,
    )

    # Call it
    mocker.patch.object(sys, 'argv', ['link-cli'])
    main()

    # Verify link_resources was called
    _assert_link_resources_called(
        mock_link,
        source_path,
        Path('.repolish') / case.expected_lib_name,
        expected_force=False,
    )

    # Verify success message
    captured = capsys.readouterr()
    assert case.expected_msg in captured.out


def test_resource_linker_cli_info_mode(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
    capsys: pytest.CaptureFixture[str],
):
    """Test resource_linker_cli --info mode outputs JSON."""
    pkg_root = tmp_path / 'mylib'
    pkg_root.mkdir()
    resources = pkg_root / 'resources'
    resources.mkdir()

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )
    mock_frame = mocker.MagicMock()
    mock_module = mocker.MagicMock()
    mock_module.__package__ = 'mylib'
    mocker.patch('inspect.getmodule', return_value=mock_module)
    mocker.patch('inspect.stack', return_value=[None, mock_frame])

    main = resource_linker_cli()

    mocker.patch.object(sys, 'argv', ['link-cli', '--info'])
    main()

    captured = capsys.readouterr()
    info = json.loads(captured.out)

    assert info['library_name'] == 'mylib'
    assert info['templates_dir'] == 'templates'
    assert 'source_dir' in info
    assert 'target_dir' in info
    # Should NOT print the success message in info mode
    assert 'are now available' not in captured.out
