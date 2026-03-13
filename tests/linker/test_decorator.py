import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock

from repolish.cli.testing import CliRunner
from repolish.linker import Symlink
from repolish.linker.decorator import resource_linker, resource_linker_cli
from tests.linker.conftest import (
    BasicLinkCliFixture,
    MockedPackageDict,
    PackageDictFixture,
)

runner = CliRunner()


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
):
    """Test basic usage of resource_linker decorator."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(basic_link_cli, [])

    assert result.exit_code == 0
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        Path('.repolish') / 'mylib',
        expected_force=False,
    )


def test_resource_linker_info_mode(
    test_package: PackageDictFixture,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker --info outputs JSON."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        pass

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=test_package['pkg_root'],
    )

    result = runner.invoke(link_cli, ['--info'])

    assert result.exit_code == 0
    info = json.loads(result.output)
    assert info['library_name'] == 'mylib'
    assert 'source_dir' in info
    assert 'target_dir' in info


def test_resource_linker_custom_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
    basic_link_cli: BasicLinkCliFixture,
):
    """Test resource_linker with custom target directory."""
    monkeypatch.chdir(tmp_path)

    custom_target = tmp_path / 'custom' / 'target'

    result = runner.invoke(basic_link_cli, ['--target-dir', str(custom_target)])

    assert result.exit_code == 0
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        custom_target,
        expected_force=False,
    )


def test_resource_linker_force_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
    basic_link_cli: BasicLinkCliFixture,
):
    """Test resource_linker with --force flag."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(basic_link_cli, ['--force'])

    assert result.exit_code == 0
    _assert_link_resources_called(
        mocked_package['mock_link_resources'],
        mocked_package['resources'],
        Path('.repolish') / 'mylib',
        expected_force=True,
    )


def test_resource_linker_info_mode_ignores_templates_subdir(
    test_package: PackageDictFixture,
    mocker: pytest_mock.MockerFixture,
):
    """`--info` output should not contain outdated templates subdir key."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        pass

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=test_package['pkg_root'],
    )

    result = runner.invoke(link_cli, ['--info'])

    assert result.exit_code == 0
    info = json.loads(result.output)
    assert 'templates_subdir' not in info


def test_resource_linker_calls_wrapped_function(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocked_package: MockedPackageDict,
):
    """Test resource_linker calls the wrapped function after linking."""
    monkeypatch.chdir(tmp_path)

    called: list[bool] = []

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        called.append(True)

    result = runner.invoke(link_cli, [])

    assert result.exit_code == 0
    assert called == [True]


def test_resource_linker_handles_link_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker exits with code 1 when linking fails."""
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

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )

    result = runner.invoke(link_cli, [])

    assert result.exit_code == 1


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

    mock_link_resources = mocker.patch(
        'repolish.linker.decorator.link_resources',
        return_value=True,
    )
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

    result = runner.invoke(link_cli, [])

    assert result.exit_code == 0
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
    called: list[bool] = []

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
    )
    def link_cli() -> None:
        called.append(True)

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=test_package['pkg_root'],
    )

    result = runner.invoke(link_cli, ['--info'])

    assert result.exit_code == 0
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
            expected_msg='resources from my-library are now available',
        ),
        ResourceLinkerCliCase(
            name='custom_library_name',
            package_name='mylib',
            library_name_arg='custom-name',
            source_dir='resources',
            expected_lib_name='custom-name',
            expected_msg='resources from custom-name are now available',
        ),
        ResourceLinkerCliCase(
            name='custom_source_directory',
            package_name='mylib',
            library_name_arg=None,
            source_dir='templates',
            expected_lib_name='mylib',
            expected_msg='templates from mylib are now available',
        ),
    ],
    ids=lambda case: case.name,
)
def test_resource_linker_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
    case: ResourceLinkerCliCase,
):
    """Test resource_linker_cli with various configurations."""
    monkeypatch.chdir(tmp_path)

    pkg_root = tmp_path / case.package_name
    pkg_root.mkdir()
    source_path = pkg_root / case.source_dir
    source_path.mkdir()

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=pkg_root,
    )
    mock_frame = mocker.MagicMock()
    mock_module = mocker.MagicMock()
    mock_module.__package__ = case.package_name
    mocker.patch('inspect.getmodule', return_value=mock_module)
    mocker.patch('inspect.stack', return_value=[None, mock_frame])

    mock_link = mocker.patch(
        'repolish.linker.decorator.link_resources',
        return_value=True,
    )

    main = resource_linker_cli(
        library_name=case.library_name_arg,
        default_source_dir=case.source_dir,
    )

    result = runner.invoke(main, [])

    assert result.exit_code == 0
    _assert_link_resources_called(
        mock_link,
        source_path,
        Path('.repolish') / case.expected_lib_name,
        expected_force=False,
    )
    assert case.expected_msg in result.output


def test_resource_linker_cli_info_mode(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
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

    result = runner.invoke(main, ['--info'])

    assert result.exit_code == 0
    info = json.loads(result.output)
    assert info['library_name'] == 'mylib'
    assert info['templates_dir'] == 'templates'
    assert 'source_dir' in info
    assert 'target_dir' in info
    assert 'are now available' not in result.output


def test_resource_linker_with_default_symlinks(
    test_package: PackageDictFixture,
    mocker: pytest_mock.MockerFixture,
):
    """Test resource_linker includes default_symlinks in --info output."""

    @resource_linker(
        library_name='mylib',
        default_source_dir='resources',
        default_symlinks=[
            Symlink(
                source='configs/.editorconfig',
                target='.editorconfig',
            ),
            Symlink(
                source='configs/.gitignore',
                target='.gitignore',
            ),
        ],
    )
    def link_cli() -> None:
        pass

    mocker.patch(
        'repolish.linker.decorator._get_package_root',
        return_value=test_package['pkg_root'],
    )

    result = runner.invoke(link_cli, ['--info'])

    assert result.exit_code == 0
    info = json.loads(result.output)
    assert info['library_name'] == 'mylib'
    assert 'symlinks' in info
    assert len(info['symlinks']) == 2
    assert info['symlinks'][0]['source'] == 'configs/.editorconfig'
    assert info['symlinks'][0]['target'] == '.editorconfig'
    assert info['symlinks'][1]['source'] == 'configs/.gitignore'
    assert info['symlinks'][1]['target'] == '.gitignore'
