import io
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_mock
from rich.console import Console

from repolish.commands.link import (
    _get_provider_names,
)
from repolish.commands.link import (
    command as run_link,
)
from repolish.config import (
    ProviderConfig,
    ProviderSymlink,
    RepolishConfigFile,
)
from repolish.config.models import ProviderFileInfo
from repolish.linker import (
    create_provider_symlinks,
    process_provider,
    run_provider_link,
    save_provider_info,
)
from repolish.linker.orchestrator import _load_provider_default_symlinks
from repolish.providers.models.workspace import MemberInfo, WorkspaceContext


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


def test_create_provider_symlinks_no_symlinks(tmp_path: Path):
    """Test create_provider_symlinks handles empty symlinks list."""
    # Should not raise, should just return
    create_provider_symlinks('mylib', tmp_path, [])


def test_create_provider_symlinks_creates_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test create_provider_symlinks creates symlinks from config."""
    monkeypatch.chdir(tmp_path)

    # Setup provider resources
    provider_dir = tmp_path / '.repolish' / 'mylib'
    provider_dir.mkdir(parents=True)
    config_dir = provider_dir / 'configs'
    config_dir.mkdir()
    (config_dir / '.editorconfig').write_text('root = true')
    (config_dir / '.prettierrc').write_text('{}')

    symlinks = [
        ProviderSymlink(
            source=Path('configs/.editorconfig'),
            target=Path('.editorconfig'),
        ),
        ProviderSymlink(
            source=Path('configs/.prettierrc'),
            target=Path('.prettierrc'),
        ),
    ]

    create_provider_symlinks('mylib', provider_dir, symlinks)

    # Verify symlinks/copies were created
    assert (tmp_path / '.editorconfig').exists()
    assert (tmp_path / '.prettierrc').exists()
    assert (tmp_path / '.editorconfig').read_text() == 'root = true'
    assert (tmp_path / '.prettierrc').read_text() == '{}'


def test_get_provider_names_with_order():
    """Test _get_provider_names returns providers_order when set."""
    config = RepolishConfigFile(
        providers_order=['lib1', 'lib2', 'lib3'],
        providers={
            'lib1': ProviderConfig(cli='lib1-link'),
            'lib2': ProviderConfig(cli='lib2-link'),
            'lib3': ProviderConfig(cli='lib3-link'),
        },
    )

    result = _get_provider_names(config)

    assert result == ['lib1', 'lib2', 'lib3']


def test_get_provider_names_without_order():
    """Test _get_provider_names returns all providers when no order set."""
    config = RepolishConfigFile(
        providers={
            'lib1': ProviderConfig(cli='lib1-link'),
            'lib2': ProviderConfig(cli='lib2-link'),
            'local': ProviderConfig(provider_root='./templates'),
        },
    )

    result = _get_provider_names(config)

    # Order is arbitrary but should include all providers
    assert set(result) == {'lib1', 'lib2', 'local'}


@pytest.mark.parametrize(
    ('exception', 'expected_result'),
    [
        (None, 0),  # Success case
        (subprocess.CalledProcessError(1, 'cmd'), 1),  # Link command fails
        (FileNotFoundError('not found'), 1),  # CLI not found
    ],
)
def test_process_single_provider_error_handling(
    exception: subprocess.CalledProcessError | FileNotFoundError | None,
    expected_result: int,
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
):
    """Test process_provider handles various error conditions."""
    provider_config = ProviderConfig(cli='mylib-link')

    if exception is None:
        # Success case
        provider_info = ProviderFileInfo(
            resources_dir=str(tmp_path / '.repolish' / 'mylib'),
            site_package_dir='/fake/source/mylib',
        )
        _ = mocker.patch(
            'repolish.linker.orchestrator.run_provider_link',
            return_value=provider_info,
        )
        result = process_provider('mylib', provider_config, tmp_path)
        assert result == expected_result
    else:
        # Error cases
        _ = mocker.patch(
            'repolish.linker.orchestrator.run_provider_link',
            side_effect=exception,
        )
        result = process_provider('mylib', provider_config, tmp_path)
        assert result == expected_result


def test_run_no_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test run handles configs with no providers."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    result = run_link(config_file)

    assert result == 0


def test_run_with_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run processes providers successfully."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers:
  mylib:
    cli: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    provider_info = ProviderFileInfo(
        resources_dir=str(tmp_path / '.repolish' / 'mylib'),
        site_package_dir='/fake/source/mylib',
    )

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        return_value=provider_info,
    )
    result = run_link(config_file)

    assert result == 0


def test_run_with_directory_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run processes directory-based providers (no CLI, just directory path)."""
    monkeypatch.chdir(tmp_path)

    # Create provider directory with templates
    provider_dir = tmp_path / 'local_provider'
    provider_dir.mkdir()
    # provider resources exist at the root of the directory now
    (provider_dir / 'repolish.py').write_text('# local provider')
    (provider_dir / 'repolish').mkdir()

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text(f"""
providers:
  local:
    provider_root: {provider_dir}
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    # Mock should NOT be called since directory providers don't use run_provider_link
    mock_run_provider_link = mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
    )

    result = run_link(config_file)

    assert result == 0
    # Verify run_provider_link was NOT called for directory-based provider
    mock_run_provider_link.assert_not_called()


def test_run_provider_not_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run handles provider in order but not in providers config."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers_order: [lib1, lib2, nonexistent]

providers:
  lib1:
    cli: lib1-link
  lib2:
    cli: lib2-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    provider_info = ProviderFileInfo(
        resources_dir=str(tmp_path / '.repolish' / 'lib'),
        site_package_dir='/fake/source/lib',
    )

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        return_value=provider_info,
    )
    result = run_link(config_file)

    # Should succeed despite missing provider in order
    assert result == 0


def test_run_provider_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """Test run returns error when provider processing fails."""
    monkeypatch.chdir(tmp_path)

    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text("""
directories:
  - ./templates

providers:
  mylib:
    cli: mylib-link
""")

    # Create dummy template directory
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'repolish.py').write_text('# provider')
    (tmp_path / 'templates' / 'repolish').mkdir()

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        side_effect=subprocess.CalledProcessError(1, 'cmd'),
    )
    result = run_link(config_file)

    assert result == 1


def test_save_provider_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that save_provider_info saves provider info correctly."""
    monkeypatch.chdir(tmp_path)

    provider_info = ProviderFileInfo(
        resources_dir=str(tmp_path / '.repolish' / 'mylib'),
        site_package_dir='/fake/source/mylib',
    )

    save_provider_info('mylib', provider_info, tmp_path)

    # Check provider info file saved in .repolish/_/ directory
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.mylib.json'
    assert info_file.exists()

    saved_info = json.loads(info_file.read_text())
    assert saved_info['resources_dir'] == str(tmp_path / '.repolish' / 'mylib')
    assert saved_info['provider_root'] == ''


def test_save_provider_info_with_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test that save_provider_info saves alias when name differs from directory."""
    monkeypatch.chdir(tmp_path)

    # Provider is called "base" in config, but resources_dir is "codeguide"
    provider_info = ProviderFileInfo(
        resources_dir=str(tmp_path / '.repolish' / 'codeguide'),
        site_package_dir='/fake/source/codeguide',
    )

    save_provider_info('base', provider_info, tmp_path)

    # Provider info should be saved in .repolish/_/
    info_file = tmp_path / '.repolish' / '_' / 'provider-info.base.json'
    assert info_file.exists()

    _ = json.loads(info_file.read_text())

    # Alias mapping should also be saved
    alias_file = tmp_path / '.repolish' / '_' / '.all-providers.json'
    assert alias_file.exists()

    aliases = json.loads(alias_file.read_text())
    assert 'aliases' in aliases
    assert aliases['aliases']['base'] == 'codeguide'


def test_run_provider_link_no_extra_save(
    mocker: pytest_mock.MockerFixture,
    tmp_path: Path,
):
    """Test that run_provider_link doesn't save info (that's done by process_provider)."""
    provider_info_data = {
        'resources_dir': '.repolish/mylib',
        'site_package_dir': '/fake/source/mylib',
    }

    mock_run = mocker.patch('subprocess.run')
    mock_info = MagicMock()
    mock_info.stdout = json.dumps(provider_info_data)
    mock_link = MagicMock()
    mock_run.side_effect = [mock_info, mock_link]

    result = run_provider_link('mylib', 'mylib-link')

    assert isinstance(result, ProviderFileInfo)
    assert result.resources_dir == '.repolish/mylib'


def _cwd_provider_info(*_args: object, **_kwargs: object) -> ProviderFileInfo:
    """Return a ProviderFileInfo whose resources_dir is under the current working directory."""
    return ProviderFileInfo(
        resources_dir=str(Path.cwd() / '.repolish' / 'lib'),
        site_package_dir='/fake/source/lib',
    )


def test_run_monorepo_links_root_and_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """command() links root providers then each member's providers."""
    monkeypatch.chdir(tmp_path)

    root_config = tmp_path / 'repolish.yaml'
    root_config.write_text("""
providers:
  root_lib:
    cli: root-lib-link
workspace:
  members:
    - packages/*
""")

    for name in ('pkg_a', 'pkg_b'):
        member_dir = tmp_path / 'packages' / name
        member_dir.mkdir(parents=True)
        (member_dir / 'repolish.yaml').write_text(f"""
providers:
  {name}_lib:
    cli: {name}-lib-link
""")

    mock_link = mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        side_effect=_cwd_provider_info,
    )

    result = run_link(root_config)

    assert result == 0
    # One call for root + one call per member = 3 total
    assert mock_link.call_count == 3


def test_run_monorepo_member_failure_stops_early(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """command() returns 1 immediately when a member provider fails."""
    monkeypatch.chdir(tmp_path)

    root_config = tmp_path / 'repolish.yaml'
    root_config.write_text("""
providers:
  root_lib:
    cli: root-lib-link
workspace:
  members:
    - packages/*
""")

    for name in ('pkg_a', 'pkg_b'):
        member_dir = tmp_path / 'packages' / name
        member_dir.mkdir(parents=True)
        (member_dir / 'repolish.yaml').write_text(f"""
providers:
  {name}_lib:
    cli: {name}-lib-link
""")

    call_count = 0

    def _side_effect(*_args: object, **_kwargs: object) -> ProviderFileInfo:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _cwd_provider_info()
        raise subprocess.CalledProcessError(1, 'cmd')

    mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        side_effect=_side_effect,
    )

    result = run_link(root_config)

    assert result == 1


def test_run_monorepo_skips_member_without_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
):
    """command() silently skips member directories that have no repolish.yaml."""
    monkeypatch.chdir(tmp_path)

    root_config = tmp_path / 'repolish.yaml'
    root_config.write_text("""
providers:
  root_lib:
    cli: root-lib-link
workspace:
  members:
    - packages/*
""")

    # pkg_a has a config; pkg_b does not.
    pkg_a = tmp_path / 'packages' / 'pkg_a'
    pkg_a.mkdir(parents=True)
    (pkg_a / 'repolish.yaml').write_text("""
providers:
  pkg_a_lib:
    cli: pkg-a-lib-link
""")
    (tmp_path / 'packages' / 'pkg_b').mkdir(parents=True)

    mock_link = mocker.patch(
        'repolish.linker.orchestrator.run_provider_link',
        side_effect=_cwd_provider_info,
    )

    result = run_link(root_config)

    assert result == 0
    # Root + pkg_a only (pkg_b is skipped)
    assert mock_link.call_count == 2


def test_load_provider_default_symlinks_via_mode_handler(
    tmp_path: Path,
) -> None:
    """Mode handler's create_default_symlinks() is called and combined with provider symlinks."""
    repolish_src = """\
from repolish import Provider, ModeHandler, BaseContext, BaseInputs, Symlink


class RootHandler(ModeHandler):
    def create_default_symlinks(self):
        return [Symlink(source='configs/.editorconfig', target='.editorconfig')]


class P(Provider[BaseContext, BaseInputs]):
    root_mode = RootHandler

    def create_context(self):
        return BaseContext()
"""
    (tmp_path / 'repolish.py').write_text(repolish_src)

    symlinks = _load_provider_default_symlinks(tmp_path, 'root')

    assert len(symlinks) == 1
    assert symlinks[0].target.name == '.editorconfig'


# ---------------------------------------------------------------------------
# Additional link.py coverage tests
# ---------------------------------------------------------------------------
from repolish.commands.link import (  # noqa: E402
    _link_config,
    _link_members,
    _print_link_tree,
)


def test_print_link_tree_with_symlinks(
    tmp_path: Path,
    mocker: pytest_mock.MockerFixture,
) -> None:
    """_print_link_tree prints summary when sections contain symlinks."""
    out = io.StringIO()
    test_console = Console(file=out, force_terminal=False, no_color=True, width=1000)
    mocker.patch('repolish.commands.link.console', test_console)

    sl = ProviderSymlink(
        source=tmp_path / 'src/.editorconfig',
        target=tmp_path / '.editorconfig',
    )
    sections = [('Standalone', {'my-provider': [sl]})]
    _print_link_tree(sections)

    output = out.getvalue()
    assert 'link summary' in output
    assert 'Standalone' in output
    assert '.editorconfig' in output


def test_link_config_no_providers(tmp_path: Path) -> None:
    """_link_config returns (0, {}) immediately when config has no providers."""
    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text('providers: {}\n')
    rc, syms = _link_config(config_file)
    assert rc == 0
    assert syms == {}


def test_link_config_appends_member_section_with_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
) -> None:
    """_link_members appends a section when syms is non-empty."""
    monkeypatch.chdir(tmp_path)
    member_dir = tmp_path / 'packages' / 'pkg_a'
    member_dir.mkdir(parents=True)
    (member_dir / 'repolish.yaml').write_text(
        'providers:\n  pkg_a_lib:\n    cli: pkg-a-lib-link\n',
    )

    sl = ProviderSymlink(
        source=member_dir / 'src/.editorconfig',
        target=member_dir / '.editorconfig',
    )

    mocker.patch(
        'repolish.commands.link._link_config',
        return_value=(0, {'pkg_a_lib': [sl]}),
    )

    mono_ctx = WorkspaceContext(
        mode='root',
        root_dir=tmp_path,
        members=[
            MemberInfo(
                path=member_dir.relative_to(tmp_path),
                name='pkg_a',
                provider_aliases=frozenset({'pkg_a_lib'}),
            ),
        ],
    )

    rc, sections = _link_members(mono_ctx, tmp_path)
    assert rc == 0
    assert len(sections) == 1
    assert sections[0][0] == 'Member: pkg_a'


def test_command_returns_nonzero_when_root_link_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
) -> None:
    """command() returns 1 immediately when root provider linking fails in monorepo mode."""
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text(
        'providers:\n  root_lib:\n    cli: root-lib-link\nworkspace:\n  members:\n    - packages/*\n',
    )
    (tmp_path / 'packages').mkdir()

    mocker.patch('repolish.commands.link._link_config', return_value=(1, {}))

    result = run_link(config_file)
    assert result == 1


def test_command_appends_root_syms_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mocker: pytest_mock.MockerFixture,
) -> None:
    """command() appends a Root section when root_syms is non-empty."""
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / 'repolish.yaml'
    config_file.write_text(
        'providers:\n  root_lib:\n    cli: root-lib-link\nworkspace:\n  members:\n    - packages/*\n',
    )
    (tmp_path / 'packages').mkdir()

    sl = ProviderSymlink(
        source=tmp_path / 'src/.editorconfig',
        target=tmp_path / '.editorconfig',
    )
    mocker.patch(
        'repolish.commands.link._link_config',
        return_value=(0, {'root_lib': [sl]}),
    )
    mocker.patch('repolish.commands.link._link_members', return_value=(0, []))
    mocker.patch('repolish.commands.link._print_link_tree')

    result = run_link(config_file)
    assert result == 0
