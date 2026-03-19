from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from repolish.config.models.project import MonorepoConfig
from repolish.config.topology import (
    check_running_from_member,
    detect_monorepo,
    detect_monorepo_from_config,
)

_FIXTURES_DIR = Path(__file__).parent / 'fixtures'
_MONOREPO_BASIC = _FIXTURES_DIR / 'monorepo-basic'


@dataclass
class TCase:
    name: str


class TestDetectMonorepo:
    def test_detect_monorepo_finds_members(self) -> None:
        ctx = detect_monorepo(_MONOREPO_BASIC)

        assert ctx is not None
        assert ctx.mode == 'root'

        member_names = {m.name for m in ctx.members}
        assert 'pkg-a' in member_names
        assert 'pkg-b' in member_names
        # pkg-no-repolish has no repolish.yaml → silently skipped
        assert 'pkg-no-repolish' not in member_names

    def test_detect_monorepo_provider_aliases(self) -> None:
        ctx = detect_monorepo(_MONOREPO_BASIC)

        assert ctx is not None
        for member in ctx.members:
            assert 'simple-provider' in member.provider_aliases

    def test_detect_monorepo_paths_are_relative(self) -> None:
        ctx = detect_monorepo(_MONOREPO_BASIC)

        assert ctx is not None
        for member in ctx.members:
            assert not member.path.is_absolute()

    def test_detect_monorepo_standalone(self, tmp_path: Path) -> None:
        # A directory with no pyproject.toml is standalone.
        result = detect_monorepo(tmp_path)

        assert result is None

    def test_detect_monorepo_no_workspace_section(self, tmp_path: Path) -> None:
        # pyproject.toml exists but has no [tool.uv.workspace].
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "standalone"\n',
        )
        result = detect_monorepo(tmp_path)

        assert result is None

    def test_detect_monorepo_explicit_members(self, tmp_path: Path) -> None:
        # copy monorepo-basic into tmp_path so we can mutate independently
        dest = shutil.copytree(_MONOREPO_BASIC, tmp_path / 'monorepo-basic')

        cfg = MonorepoConfig(members=['packages/pkg-a'])
        ctx = detect_monorepo_from_config(dest, cfg)

        assert ctx is not None
        assert ctx.mode == 'root'
        member_names = {m.name for m in ctx.members}
        assert member_names == {'pkg-a'}

    def test_detect_monorepo_from_config_fallback(self) -> None:
        # members=None falls back to uv detection
        cfg = MonorepoConfig(members=None)
        ctx = detect_monorepo_from_config(_MONOREPO_BASIC, cfg)

        assert ctx is not None
        member_names = {m.name for m in ctx.members}
        assert 'pkg-a' in member_names
        assert 'pkg-b' in member_names


class TestCheckRunningFromMember:
    def test_check_running_from_member(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pkg_a = (_MONOREPO_BASIC / 'packages' / 'pkg-a').resolve()
        monkeypatch.chdir(pkg_a)

        root = check_running_from_member(pkg_a)

        assert root is not None
        assert root.resolve() == _MONOREPO_BASIC.resolve()

    def test_check_running_from_member_at_root(self) -> None:
        root = check_running_from_member(_MONOREPO_BASIC.resolve())

        assert root is None

    def test_check_running_from_member_standalone(self, tmp_path: Path) -> None:
        result = check_running_from_member(tmp_path)

        assert result is None
