"""Bundle transforms for fast lane runs.

:func:`merge_fast_lanes` folds every lane's contributions into the
:class:`~repolish.providers.models.SessionBundle` (full ``repolish apply``);
:func:`restrict_to_lane` cuts the bundle down to exactly one lane's
contributions (lane runs). Lane contributions are collected and normalized
by the provider pipeline like any other hook, so the transforms here are
pure dict work: both run modes consume the same collected specs, which is
what makes lane files safe to run in isolation. Lazy lanes arrive as
factories and are evaluated here, once, only when a run needs them.

Duplicate dests are load-time errors, never silent overrides: the same dest
in two merged lane specs always raises; the same dest in a regular hook
and a lane spec raises unless the project's ``repolish.yaml`` carries a
``fast_lanes.resolutions`` entry for it (see
:class:`~repolish.config.models.project.FastLanesSection`).
"""

from pathlib import Path, PurePosixPath

from hotlog import get_logger

from repolish.config.models import FastLaneResolution
from repolish.providers.models import (
    FastLaneEntry,
    FastLaneSpec,
    FileMode,
    SessionBundle,
    TemplateMapping,
)

logger = get_logger(__name__)


def _eval_spec(entry: FastLaneEntry) -> FastLaneSpec:
    """Resolve one collected lane entry to its normalized spec.

    Eager lanes arrive as specs; lazy lanes as factories whose first call
    normalizes the result (see ``_lazy_lane_spec`` in the collection code).
    """
    if isinstance(entry, FastLaneSpec):
        return entry
    return entry()


def _spec_dests(spec: FastLaneSpec) -> set[str]:
    """Return every dest path a lane spec claims, across all three kinds."""
    return set(spec.file_mappings) | set(spec.file_insertions) | set(spec.file_validators)


def _detect_lane_lane_collisions(merged: dict[str, FastLaneSpec]) -> None:
    """Fail when the same dest is declared by two different merged lanes.

    This is a static authoring mistake (two specs fed identical inputs in
    every run mode, no state involved) so it always raises in full runs and
    cannot be resolved away via ``fast_lanes.resolutions``. Lane runs do not
    run this check: evaluating every lane's factory there would defeat lazy
    registration, and with one lane executing there is nothing to collide
    with.
    """
    seen: dict[str, str] = {}
    for lane_key, spec in merged.items():
        for dest in sorted(_spec_dests(spec)):
            other = seen.get(dest)
            if other is not None and other != lane_key:
                msg = (
                    f'fast lane collision on {dest!r}: declared by both lane '
                    f'{other!r} and lane {lane_key!r}. A dest may belong to only '
                    'one fast lane; move one of the declarations.'
                )
                raise ValueError(msg)
            seen[dest] = lane_key


def _regular_claims(
    bundle: SessionBundle,
) -> tuple[set[str], set[str], set[str]]:
    """Return the dest sets the regular hooks currently claim.

    Mappings claim their dest through ``file_mappings`` or, for DELETE and
    CREATE_ONLY declarations, through the resolved ``delete_files`` /
    ``create_only_files`` lists.
    """
    mappings = (
        set(bundle.file_mappings)
        | {p.as_posix() for p in bundle.delete_files}
        | {p.as_posix() for p in bundle.create_only_files}
    )
    return mappings, set(bundle.file_insertions), set(bundle.file_validators)


def _collision_kinds(
    dest: str,
    mapping_claims: set[str],
    insertion_claims: set[str],
    validator_claims: set[str],
) -> list[str]:
    """Name which regular contribution kinds claim *dest* (for error text)."""
    kinds: list[str] = []
    if dest in mapping_claims:
        kinds.append('file mapping')
    if dest in insertion_claims:
        kinds.append('insertion')
    if dest in validator_claims:
        kinds.append('validator')
    return kinds


def _unresolved_collision_msg(
    dest: str,
    lane_key: str,
    kinds: list[str],
) -> str:
    pid = lane_key.split(':', 1)[0]
    return (
        f'fast lane collision on {dest!r}: lane {lane_key!r} declares it and so '
        f'does a regular hook ({", ".join(kinds)}) of provider {pid!r}. Regular '
        'hooks can be conditional on context, so this may surface only in some '
        f'project states. Add a fast_lanes.resolutions entry for {dest!r} in '
        "repolish.yaml ('fast_lane' or 'regular') to choose which side owns the dest."
    )


def _resolve_regular_collisions(
    bundle: SessionBundle,
    merged: dict[str, FastLaneSpec],
    resolutions: dict[str, FastLaneResolution],
) -> tuple[dict[str, set[str]], set[str]]:
    """Decide every regular-vs-lane collision against the project config.

    Returns ``(lane_drops, regular_drops)``: per-lane dest sets the config
    resolved to ``'regular'`` (the regular contribution wins; lane runs skip
    those dests), and the dests resolved to ``'fast_lane'`` (the lane's
    contribution wins everywhere; the regular entries are dropped from the
    bundle). Unresolved collisions raise.
    """
    mapping_claims, insertion_claims, validator_claims = _regular_claims(bundle)
    lane_drops: dict[str, set[str]] = {key: set() for key in merged}
    regular_drops: set[str] = set()
    for lane_key, spec in merged.items():
        for dest in sorted(_spec_dests(spec)):
            kinds = _collision_kinds(
                dest,
                mapping_claims,
                insertion_claims,
                validator_claims,
            )
            if not kinds:
                continue
            resolution = resolutions.get(dest)
            if resolution is FastLaneResolution.FAST_LANE:
                regular_drops.add(dest)
            elif resolution is FastLaneResolution.REGULAR:
                lane_drops[lane_key].add(dest)
            else:
                raise ValueError(
                    _unresolved_collision_msg(dest, lane_key, kinds),
                )
    return lane_drops, regular_drops


def _apply_mapping(
    bundle: SessionBundle,
    dest: str,
    mapping: str | TemplateMapping,
) -> None:
    """Fold one lane mapping into the bundle, honoring its FileMode."""
    path = Path(*PurePosixPath(dest).parts)
    mode = mapping.file_mode if isinstance(mapping, TemplateMapping) else FileMode.REGULAR
    if mode is FileMode.DELETE:
        bundle.delete_files.append(path)
    elif mode is FileMode.KEEP:
        bundle.delete_files = [p for p in bundle.delete_files if p != path]
    elif mode is FileMode.SUPPRESS:
        if isinstance(mapping, TemplateMapping) and mapping.source_template:
            bundle.suppressed_sources.add(mapping.source_template)
    else:
        if mode is FileMode.CREATE_ONLY:
            bundle.create_only_files.append(path)
        bundle.file_mappings[dest] = mapping


def _apply_insertion_contributions(
    bundle: SessionBundle,
    spec: FastLaneSpec,
    *,
    skip: set[str],
    provider_name: str,
) -> None:
    """Fold one lane spec's insertions into the per-file and session registries."""
    pid = spec.source_provider or ''
    for dest, functions in spec.file_insertions.items():
        if dest in skip:
            continue
        registry = bundle.file_insertions.setdefault(dest, {})
        for fn_name, bound in functions.items():
            # First unqualified name is the deterministic fallback; qualified
            # keys allow explicit targeting (same contract as regular hooks).
            registry.setdefault(fn_name, bound)
            registry[f'{provider_name}:{fn_name}'] = bound
            bundle.insertion_registry.setdefault(fn_name, bound)
            bundle.insertion_registry[f'{provider_name}:{fn_name}'] = bound
        bundle.insertion_sources.setdefault(dest, []).append(pid)


def _apply_validator_contributions(
    bundle: SessionBundle,
    spec: FastLaneSpec,
    *,
    skip: set[str],
) -> None:
    """Fold one lane spec's validators into the registry and source map."""
    pid = spec.source_provider or ''
    for dest, path_validators in spec.file_validators.items():
        if dest in skip:
            continue
        bundle.file_validators.setdefault(dest, {}).update(path_validators)
        bundle.validator_sources[dest] = pid


def _apply_lane_contributions(
    bundle: SessionBundle,
    spec: FastLaneSpec,
    *,
    skip: set[str],
    pid_to_alias: dict[str, str] | None,
) -> None:
    """Fold one lane spec's contributions into the bundle.

    Bookkeeping mirrors the regular collection path: insertion functions land
    in the per-file registries and the session-wide registry under both their
    unqualified name and a ``alias:fn`` qualified key, and source maps record
    the declaring provider.
    """
    pid = spec.source_provider or ''
    provider_name = (pid_to_alias or {}).get(pid) or pid
    for dest, mapping in spec.file_mappings.items():
        if dest in skip:
            continue
        _apply_mapping(bundle, dest, mapping)
    _apply_insertion_contributions(
        bundle,
        spec,
        skip=skip,
        provider_name=provider_name,
    )
    _apply_validator_contributions(bundle, spec, skip=skip)


def _drop_regular_claims(bundle: SessionBundle, dests: set[str]) -> None:
    """Remove every regular contribution for dests a resolution gave to a lane."""
    for dest in dests:
        bundle.file_mappings.pop(dest, None)
        bundle.delete_files = [p for p in bundle.delete_files if p.as_posix() != dest]
        bundle.create_only_files = [p for p in bundle.create_only_files if p.as_posix() != dest]
        bundle.file_insertions.pop(dest, None)
        bundle.file_validators.pop(dest, None)
        bundle.insertion_sources.pop(dest, None)
        bundle.validator_sources.pop(dest, None)


def merge_fast_lanes(
    bundle: SessionBundle,
    *,
    resolutions: dict[str, FastLaneResolution],
    pid_to_alias: dict[str, str] | None = None,
) -> list[FastLaneSpec]:
    """Fold every merged lane's contributions into *bundle* (full apply).

    Mutates the bundle in place so lane-declared dests render, insert, and
    validate exactly as they would in a lane run: parity is guaranteed because
    both run modes consume the same collected specs. Duplicate detection runs
    first; see the module docstring for the error and resolution rules.

    Returns the merged specs so the caller can fold their copies into the
    run's resolved copy set (copies live outside the bundle).
    """
    if not bundle.fast_lanes:
        return []
    merged = {lane_key: _eval_spec(entry) for lane_key, entry in bundle.fast_lanes.items()}
    if not merged:
        return []
    _detect_lane_lane_collisions(merged)
    lane_drops, regular_drops = _resolve_regular_collisions(
        bundle,
        merged,
        resolutions,
    )
    _drop_regular_claims(bundle, regular_drops)
    for lane_key, spec in merged.items():
        _apply_lane_contributions(
            bundle,
            spec,
            skip=lane_drops[lane_key],
            pid_to_alias=pid_to_alias,
        )
    return list(merged.values())


def restrict_to_lane(
    bundle: SessionBundle,
    lane: str,
    *,
    resolutions: dict[str, FastLaneResolution],
    pid_to_alias: dict[str, str] | None = None,
) -> FastLaneSpec:
    """Cut *bundle* down to exactly one lane's contributions (lane runs).

    Regular-hook content never runs in a lane run: the mapping, insertion,
    and validator fields are replaced with the lane's own declarations
    (config-level ``delete_files`` is not honored either; lanes never delete
    outside their own ``FileMode.DELETE`` mappings). The provider's copy set
    is the same: a lane run copies exactly what the lane declares in
    ``file_copies`` and never collects (or executes) the provider's defaults;
    symlinks are still materialized as declared.

    Returns the selected lane's evaluated spec so the caller can derive the
    run's copy set from it.

    Only the selected lane is evaluated: a run selecting one lazy lane
    leaves every other lane's factory uncalled. Lane-vs-lane collisions are
    not detected here for that reason (full runs still catch them); the
    regular-vs-lane check runs for the selected lane: a resolution of
    ``'regular'`` removes that dest from the
    run, ``'fast_lane'`` keeps it.
    """
    matches = [key for key in bundle.fast_lanes if key.split(':', 1)[1] == lane]
    if not matches:
        available = sorted({key.split(':', 1)[1] for key in bundle.fast_lanes})
        msg = f'unknown fast lane {lane!r}; available lanes: {available}'
        raise ValueError(msg)
    if len(matches) > 1:
        owners = sorted({key.split(':', 1)[0] for key in matches})
        msg = f'fast lane {lane!r} is declared by multiple providers ({owners}); rename one of the lanes'
        raise ValueError(msg)

    spec = _eval_spec(bundle.fast_lanes[matches[0]])
    mapping_claims, insertion_claims, validator_claims = _regular_claims(bundle)
    skip: set[str] = set()
    for dest in sorted(_spec_dests(spec)):
        kinds = _collision_kinds(
            dest,
            mapping_claims,
            insertion_claims,
            validator_claims,
        )
        if not kinds:
            continue
        resolution = resolutions.get(dest)
        if resolution is FastLaneResolution.REGULAR:
            skip.add(dest)
        elif resolution is not FastLaneResolution.FAST_LANE:
            raise ValueError(_unresolved_collision_msg(dest, matches[0], kinds))

    bundle.file_mappings = {}
    bundle.delete_files = []
    bundle.create_only_files = []
    bundle.file_insertions = {}
    bundle.insertion_registry = {}
    bundle.insertion_sources = {}
    bundle.file_validators = {}
    bundle.validator_sources = {}
    _apply_lane_contributions(
        bundle,
        spec,
        skip=skip,
        pid_to_alias=pid_to_alias,
    )
    return spec
