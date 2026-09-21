"""Unit tests for fast lane merge/restrict and duplicate detection.

These exercise the bundle transforms directly with hand-built
:class:`~repolish.providers.models.SessionBundle` objects, mirroring the state
the collection step leaves behind (regular contributions already folded,
lane specs normalized and nested ``{provider_id: {lane_name: entry}}``).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from repolish.config.models import FastLaneResolution
from repolish.fastlane import merge_fast_lanes, restrict_to_lane
from repolish.providers.models import (
    FastLaneEntry,
    FastLaneSpec,
    FileMode,
    LazyLaneSpec,
    SessionBundle,
    TemplateMapping,
    ValidationResult,
)

PID = '/providers/demo/templates'
ALIASES = {PID: 'demo'}
OTHER_PID = '/providers/other/templates'


def _render(_block: object) -> str:
    """Dummy insertion renderer for lane fixtures."""
    return 'rendered'


def _noop(_ctx: object, _path: Path) -> ValidationResult:
    """Dummy validator for lane fixtures."""
    return ValidationResult()


def _tm(bundle: SessionBundle, dest: str) -> TemplateMapping:
    """Narrow a bundle mapping entry to TemplateMapping for assertions."""
    entry = bundle.file_mappings[dest]
    assert isinstance(entry, TemplateMapping)
    return entry


def _posix(dest: str) -> Path:
    """Build a Path the way the collection code does for POSIX dest strings."""
    return Path(*PurePosixPath(dest).parts)


def _mapping(
    source: str = 'src.jinja',
    *,
    mode: FileMode = FileMode.REGULAR,
) -> TemplateMapping:
    """Annotated mapping entry as collection would produce for a lane."""
    return TemplateMapping(source, file_mode=mode, source_provider=PID)


def _lane(
    lane: str,
    *,
    mappings: dict[str, TemplateMapping] | None = None,
    insertions: dict[str, dict[str, object]] | None = None,
    validators: dict[str, dict[str, object]] | None = None,
    pid: str = PID,
) -> dict[str, dict[str, FastLaneEntry]]:
    """One lane nested the way collection stores it on the bundle."""
    return {
        pid: {
            lane: FastLaneSpec(
                file_mappings=mappings or {},
                file_insertions=insertions or {},
                file_validators=validators or {},
                source_provider=pid,
            ),
        },
    }


def _merge_lanes(
    *lanes: dict[str, dict[str, FastLaneEntry]],
) -> dict[str, dict[str, FastLaneEntry]]:
    """Combine lane dicts the way collection accumulates them per provider."""
    combined: dict[str, dict[str, FastLaneEntry]] = {}
    for lane in lanes:
        for pid, entries in lane.items():
            combined.setdefault(pid, {}).update(entries)
    return combined


def _bundle() -> SessionBundle:
    """A bundle with one regular mapping, insertion, and validator claim."""
    bundle = SessionBundle()
    bundle.file_mappings['regular.txt'] = _mapping('regular.txt')
    bundle.file_insertions['README.md'] = {'regular_fn': _render}
    bundle.insertion_registry['regular_fn'] = _render
    bundle.insertion_sources['README.md'] = [PID]
    bundle.file_validators['regular.txt'] = {'check': _noop}
    bundle.validator_sources['regular.txt'] = PID
    return bundle


class TestMerge:
    def test_merge_without_lanes_is_a_no_op(self) -> None:
        bundle = _bundle()
        before = {
            'mappings': dict(bundle.file_mappings),
            'insertions': {k: dict(v) for k, v in bundle.file_insertions.items()},
            'validators': {k: dict(v) for k, v in bundle.file_validators.items()},
        }

        merge_fast_lanes(bundle, resolutions={})

        assert bundle.file_mappings == before['mappings']
        assert bundle.file_insertions == before['insertions']
        assert bundle.file_validators == before['validators']

    def test_merge_truthy_empty_fast_lanes_returns_empty(self) -> None:
        """Defensive guard: handle a truthy mapping whose items() are empty."""

        class _TruthyEmptyDict(dict[str, dict[str, FastLaneEntry]]):
            def __bool__(self) -> bool:
                return True

        bundle = SessionBundle()
        bundle.fast_lanes = _TruthyEmptyDict()

        merged = merge_fast_lanes(bundle, resolutions={})

        assert merged == []

    def test_merges_all_three_contribution_kinds_with_bookkeeping(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'out/action.yaml': _mapping('action.yaml.jinja')},
            insertions={'docs/usage.md': {'usage': _render}},
            validators={'out/action.yaml': {'lint': _noop}},
        )

        merge_fast_lanes(bundle, resolutions={}, pid_to_alias=ALIASES)

        assert _tm(bundle, 'out/action.yaml').source_template == 'action.yaml.jinja'
        assert 'README.md' in bundle.file_insertions  # regular insertions preserved
        registry = bundle.file_insertions['docs/usage.md']
        assert 'usage' in registry
        assert 'demo:usage' in registry  # alias-qualified key, same as regular hooks
        assert 'usage' in bundle.insertion_registry
        assert 'demo:usage' in bundle.insertion_registry
        assert bundle.insertion_sources['docs/usage.md'] == [PID]
        assert 'lint' in bundle.file_validators['out/action.yaml']
        assert bundle.validator_sources['out/action.yaml'] == PID


class TestFileModes:
    @pytest.mark.parametrize(
        ('mode', 'expected'),
        [
            (FileMode.REGULAR, 'file_mappings'),
            (FileMode.CREATE_ONLY, 'create_only'),
            (FileMode.DELETE, 'delete'),
            (FileMode.KEEP, 'keep'),
            (FileMode.SUPPRESS, 'suppress'),
        ],
    )
    def test_dispatch(self, mode: FileMode, expected: str) -> None:
        bundle = SessionBundle()
        bundle.delete_files = [_posix('stale.txt')]
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'dest.txt': _mapping(mode=mode)},
        )

        merge_fast_lanes(bundle, resolutions={})

        if expected == 'file_mappings':
            assert 'dest.txt' in bundle.file_mappings
        elif expected == 'create_only':
            assert 'dest.txt' in bundle.file_mappings
            assert _posix('dest.txt') in bundle.create_only_files
        elif expected == 'delete':
            assert 'dest.txt' not in bundle.file_mappings
            assert _posix('dest.txt') in bundle.delete_files
        elif expected == 'keep':
            # KEEP on an undeclared dest declares no output of its own and
            # leaves other providers' deletes untouched.
            assert bundle.file_mappings == {}
            assert _posix('stale.txt') in bundle.delete_files
        else:
            assert 'dest.txt' not in bundle.file_mappings
            # SUPPRESS records the source template path so the renderer skips
            # it, exactly like the regular collection path.
            assert 'src.jinja' in bundle.suppressed_sources


class TestCollisions:
    def test_lane_vs_lane_always_raises(self) -> None:
        bundle = SessionBundle()
        bundle.fast_lanes = _merge_lanes(
            _lane('actions', mappings={'shared.txt': _mapping('a.jinja')}),
            _lane('docs', mappings={'shared.txt': _mapping('b.jinja')}),
        )

        with pytest.raises(ValueError, match=r"shared\.txt.*:actions'.*:docs'"):
            merge_fast_lanes(bundle, resolutions={})

    def test_lane_vs_lane_cannot_be_resolved_away(self) -> None:
        bundle = SessionBundle()
        bundle.fast_lanes = _merge_lanes(
            _lane('actions', mappings={'shared.txt': _mapping('a.jinja')}),
            _lane('docs', mappings={'shared.txt': _mapping('b.jinja')}),
        )

        with pytest.raises(ValueError, match='fast lane collision'):
            merge_fast_lanes(
                bundle,
                resolutions={'shared.txt': FastLaneResolution.FAST_LANE},
            )

    def test_regular_vs_lane_unresolved_raises_with_both_sites(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'regular.txt': _mapping('x.jinja')},
        )

        with pytest.raises(ValueError, match='fast lane collision') as exc:
            merge_fast_lanes(bundle, resolutions={})

        message = str(exc.value)
        assert 'regular.txt' in message
        assert f'{PID}:actions' in message
        assert 'file mapping' in message
        assert 'fast_lanes.resolutions' in message

    def test_lane_insertion_vs_regular_insertion_raises(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'docs',
            insertions={'README.md': {'lane_fn': _render}},
        )

        with pytest.raises(ValueError, match=r'README\.md.*insertion'):
            merge_fast_lanes(bundle, resolutions={})

    def test_lane_validator_vs_regular_validator_raises(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            validators={'regular.txt': {'lint': _noop}},
        )

        with pytest.raises(ValueError, match=r'regular\.txt.*validator'):
            merge_fast_lanes(bundle, resolutions={})


class TestResolutions:
    def test_fast_lane_resolution_drops_regular_claims_everywhere(self) -> None:
        bundle = _bundle()
        lane_entry = _mapping('lane.txt')
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'regular.txt': lane_entry},
        )

        merge_fast_lanes(
            bundle,
            resolutions={'regular.txt': FastLaneResolution.FAST_LANE},
            pid_to_alias=ALIASES,
        )

        assert bundle.file_mappings['regular.txt'] is lane_entry
        # regular validator claim on the same dest is resolved the same way
        assert 'regular.txt' not in bundle.file_validators

    def test_regular_resolution_keeps_regular_and_drops_lane(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'regular.txt': _mapping('lane.txt')},
        )

        merge_fast_lanes(
            bundle,
            resolutions={'regular.txt': FastLaneResolution.REGULAR},
            pid_to_alias=ALIASES,
        )

        assert _tm(bundle, 'regular.txt').source_template == 'regular.txt'
        assert len(bundle.file_mappings) == 1  # the lane entry was dropped, not merged

    def test_fast_lane_resolution_holds_in_lane_runs(self) -> None:
        bundle = _bundle()
        lane_entry = _mapping('lane.txt')
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'regular.txt': lane_entry},
        )

        restrict_to_lane(
            bundle,
            'actions',
            resolutions={'regular.txt': FastLaneResolution.FAST_LANE},
        )

        assert bundle.file_mappings['regular.txt'] is lane_entry

    def test_regular_resolution_skips_dest_in_lane_runs(self) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={
                'regular.txt': _mapping('lane.txt'),
                'lane-only.txt': _mapping('lane-only.txt'),
            },
        )

        restrict_to_lane(
            bundle,
            'actions',
            resolutions={'regular.txt': FastLaneResolution.REGULAR},
        )

        assert 'regular.txt' not in bundle.file_mappings
        assert 'lane-only.txt' in bundle.file_mappings

    def test_regular_resolution_skips_lane_insertion_and_validator_dests(
        self,
    ) -> None:
        # README.md is claimed by the regular insertion; resolving it to
        # 'regular' must remove the lane's insertion and validator too.
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'docs',
            insertions={'README.md': {'lane_fn': _render}},
            validators={'README.md': {'lint': _noop}},
        )

        restrict_to_lane(
            bundle,
            'docs',
            resolutions={'README.md': FastLaneResolution.REGULAR},
        )

        assert 'README.md' not in bundle.file_insertions
        assert 'README.md' not in bundle.file_validators

    def test_unresolved_regular_vs_lane_collision_raises_in_lane_runs(
        self,
    ) -> None:
        bundle = _bundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'regular.txt': _mapping('x.jinja')},
        )

        with pytest.raises(
            ValueError,
            match=r'fast lane collision.*fast_lanes\.resolutions',
        ):
            restrict_to_lane(bundle, 'actions', resolutions={})


class TestRestrict:
    def setup_bundle(self) -> SessionBundle:
        bundle = _bundle()
        bundle.delete_files = [_posix('stale.txt')]
        bundle.fast_lanes = _merge_lanes(
            _lane(
                'actions',
                mappings={'out/action.yaml': _mapping('action.yaml.jinja')},
                validators={'out/action.yaml': {'lint': _noop}},
            ),
            _lane(
                'docs',
                insertions={'docs/usage.md': {'usage': _render}},
            ),
        )
        return bundle

    def test_restrict_leaves_exactly_the_lane_contributions(self) -> None:
        bundle = self.setup_bundle()

        restrict_to_lane(
            bundle,
            'actions',
            resolutions={},
            pid_to_alias=ALIASES,
        )

        assert set(bundle.file_mappings) == {'out/action.yaml'}
        assert set(bundle.file_insertions) == set()  # regular insertion dropped too
        assert set(bundle.insertion_registry) == set()
        assert set(bundle.file_validators) == {'out/action.yaml'}
        assert bundle.validator_sources['out/action.yaml'] == PID
        assert 'lint' in bundle.file_validators['out/action.yaml']

    def test_restrict_clears_provider_deletes(self) -> None:
        bundle = self.setup_bundle()

        restrict_to_lane(bundle, 'docs', resolutions={})

        assert bundle.delete_files == []  # lanes never delete

    def test_unknown_lane_names_available_lanes(self) -> None:
        bundle = self.setup_bundle()

        with pytest.raises(
            ValueError,
            match=r"unknown fast lane 'nope'.*actions.*docs",
        ):
            restrict_to_lane(bundle, 'nope', resolutions={})

    def test_drive_colon_pid_selects_lanes(self) -> None:
        # On Windows the provider id is a path with a drive-letter colon; a
        # composite string key would split at the drive and lane selection
        # would fail. Nested keys make the pid opaque.
        bundle = SessionBundle()
        bundle.fast_lanes = _lane(
            'actions',
            mappings={'out/action.yaml': _mapping('action.yaml.jinja')},
            pid='C:/providers/demo/templates',
        )

        restrict_to_lane(bundle, 'actions', resolutions={})

        assert set(bundle.file_mappings) == {'out/action.yaml'}

    def test_lane_name_with_colon_selects_fine(self) -> None:
        # Lane names may contain colons (provider commands land here as
        # lanes named like 'command:fetch'), so neither split nor rsplit
        # of a composite key could ever be safe.
        bundle = self.setup_bundle()
        bundle.fast_lanes[PID]['fetch:latest'] = FastLaneSpec(
            file_mappings={'out/fetch.txt': _mapping('fetch.jinja')},
            source_provider=PID,
        )

        restrict_to_lane(bundle, 'fetch:latest', resolutions={})

        assert set(bundle.file_mappings) == {'out/fetch.txt'}

    def test_same_lane_name_from_two_providers_is_ambiguous(self) -> None:
        bundle = self.setup_bundle()
        other = _lane(
            'actions',
            mappings={'other.txt': _mapping('o.jinja')},
            pid=OTHER_PID,
        )
        bundle.fast_lanes.update(
            other,
        )  # different provider: plain dict update is safe

        with pytest.raises(ValueError, match='multiple providers'):
            restrict_to_lane(bundle, 'actions', resolutions={})

    def test_lane_vs_lane_collision_not_detected_in_lane_runs(self) -> None:
        # Only the selected lane is evaluated in a lane run, so lane-vs-lane
        # detection (which would need every lane's dests) does not run there.
        # Full runs still catch the static mistake (see TestCollisions).
        bundle = self.setup_bundle()
        conflicting = _lane(
            'docs',
            mappings={'out/action.yaml': _mapping('x.jinja')},
        )
        bundle.fast_lanes = _merge_lanes(bundle.fast_lanes, conflicting)

        restrict_to_lane(bundle, 'actions', resolutions={})  # does not raise

        assert 'out/action.yaml' in bundle.file_mappings

    def test_unrelated_lane_regular_collision_ignored_in_lane_runs(
        self,
    ) -> None:
        # A collision between the docs lane and a regular hook must not block
        # a run of the actions lane; only the executed lane's dests matter.
        bundle = self.setup_bundle()
        bundle.file_insertions['docs/usage.md'] = {'regular_fn': _render}

        restrict_to_lane(bundle, 'actions', resolutions={})  # does not raise

        assert 'out/action.yaml' in bundle.file_mappings


def _counting_factory(
    spec: FastLaneSpec,
) -> tuple[FastLaneEntry, list[int]]:
    """A lane entry shaped like the collection wrapper around a factory.

    Collection stores lazy lanes as memoized `LazyLaneSpec` entries.
    The list counts factory calls.
    """
    calls: list[int] = []

    def factory() -> FastLaneSpec:
        calls.append(1)
        return spec

    return LazyLaneSpec(factory), calls


class TestLazyFactories:
    def test_merge_evaluates_coupled_factories(self) -> None:
        bundle = _bundle()
        entry, calls = _counting_factory(
            FastLaneSpec(
                file_mappings={
                    'out/action.yaml': _mapping('action.yaml.jinja'),
                },
                source_provider=PID,
            ),
        )
        bundle.fast_lanes[PID] = {'actions': entry}

        merge_fast_lanes(bundle, resolutions={}, pid_to_alias=ALIASES)

        assert calls == [1]  # evaluated exactly once per run
        assert _tm(bundle, 'out/action.yaml').source_template == 'action.yaml.jinja'

    def test_restrict_evaluates_only_the_selected_factory(self) -> None:
        bundle = SessionBundle()
        actions, actions_calls = _counting_factory(
            FastLaneSpec(
                file_mappings={'a.txt': _mapping('a.jinja')},
                source_provider=PID,
            ),
        )
        docs, docs_calls = _counting_factory(
            FastLaneSpec(
                file_insertions={'README.md': {'usage': _render}},
                source_provider=PID,
            ),
        )
        bundle.fast_lanes[PID] = {'actions': actions, 'docs': docs}

        restrict_to_lane(bundle, 'actions', resolutions={})

        assert actions_calls == [1]
        assert docs_calls == []  # unselected lane's code never loads
        assert set(bundle.file_mappings) == {'a.txt'}

    def test_merge_detects_lane_vs_lane_across_coupled_factories(self) -> None:
        bundle = SessionBundle()
        first, _ = _counting_factory(
            FastLaneSpec(
                file_mappings={'shared.txt': _mapping('a.jinja')},
                source_provider=PID,
            ),
        )
        second, _ = _counting_factory(
            FastLaneSpec(
                file_mappings={'shared.txt': _mapping('b.jinja')},
                source_provider=PID,
            ),
        )
        bundle.fast_lanes[PID] = {'actions': first, 'docs': second}

        with pytest.raises(ValueError, match=r"shared\.txt.*:actions'.*:docs'"):
            merge_fast_lanes(bundle, resolutions={})
