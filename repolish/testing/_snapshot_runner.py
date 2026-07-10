"""Higher-level snapshot test utilities for repolish providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from pydantic import BaseModel

from repolish.providers.models.provider import ProviderEntry
from repolish.testing._snapshot import assert_snapshots

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from repolish.providers.models.context import BaseContext
    from repolish.providers.models.provider import Provider

from repolish.testing._testbed import ProviderTestBed

CtxT = TypeVar('CtxT', bound='BaseContext')
InpT = TypeVar('InpT', bound=BaseModel)


def mock_provider_entry(
    provider_class: type[Provider[CtxT, InpT]],
    context: CtxT,
    *,
    alias: str | None = None,
    provider_id: str | None = None,
    input_type: type[BaseModel] | None = None,
) -> ProviderEntry:
    """Build a mock ``ProviderEntry`` for testing cross-provider scenarios.

    Use this helper when your provider reads another provider's context via
    ``get_provider_context()`` or ``opt.all_providers``. Instead of constructing
    the full ``ProviderEntry`` manually, this function fills in sensible defaults.

    Example::

        from repolish.testing import mock_provider_entry

        # Mock a Poe provider with pre-populated context
        poe_entry = mock_provider_entry(
            PoeProvider,
            context=PoeCtx(ci_tasks=['lint', 'test']),
            alias='poe',
        )

        opts = SnapshotRunOptions(
            all_providers=[poe_entry],
        )

        # CI-checks provider can now read Poe's context via get_provider_context()
        ctx, rendered = run_snapshot_case(
            CIChecksProvider,
            options=opts,
            snapshot_dir=SNAPSHOT_DIR,
        )

    Args:
        provider_class: The provider class being mocked.
        context: The context object this mock provider exposes.
        alias: Provider alias (defaults to provider class name in lowercase).
        provider_id: Provider ID (defaults to alias).
        input_type: The input schema type for the provider
            (defaults to a generic BaseModel).

    Returns:
        A ``ProviderEntry`` suitable for passing to ``SnapshotRunOptions.all_providers``.
    """
    # Use BaseModel as default input_type if not specified
    if input_type is None:
        input_type = BaseModel

    if alias is None:
        alias = provider_class.__name__.lower()
    if provider_id is None:
        provider_id = alias

    return ProviderEntry(
        provider_id=provider_id,
        alias=alias,
        inst_type=provider_class,
        context=context,
        context_type=type(context),
        input_type=input_type,
    )


@dataclass(frozen=True)
class SnapshotRunOptions(Generic[InpT]):
    """Configuration options for a single snapshot test run.

    This dataclass captures the common parameters needed to run a
    provider snapshot test, removing repeated constructor/finalize glue
    and making defaults explicit.

    Example::

        opts = SnapshotRunOptions[PoeProviderInputs](
            mode='root',
            received_inputs=case.inputs,
            local_files_dir=case.snapshot_dir(),
            mutate_context=lambda c: _apply_case_overrides(c, case),
        )

        ctx, rendered = run_snapshot_case(
            PoeProvider,
            options=opts,
            snapshot_dir=case.snapshot_dir(),
            filter_rendered=lambda out: include_paths(
                out,
                exact={'poe_tasks.toml'},
                prefixes=('poe-tasks/',),
            ),
        )
    """

    mode: Literal['standalone', 'root', 'member'] = 'standalone'
    received_inputs: list[InpT] = field(default_factory=list)
    all_providers: list[ProviderEntry] | None = None
    provider_index: int = 0
    preprocess: bool = True
    local_files_dir: Path | None = None
    extra_context: dict[str, object] | None = None
    # Optional post-finalize mutator for one-off context edits
    mutate_context: Callable[[BaseContext], None] | None = None


def run_snapshot_case(
    provider_class: type[Provider[CtxT, InpT]],
    *,
    options: SnapshotRunOptions[InpT],
    snapshot_dir: Path | None = None,
    filter_rendered: Callable[[dict[str, str]], dict[str, str]] | None = None,
    bed_kwargs: dict[str, object] | None = None,
) -> tuple[CtxT, dict[str, str]]:
    """Execute the common snapshot test flow and optionally assert snapshots.

    This function captures the repeated pattern used in provider snapshot tests:

    1. Construct ``ProviderTestBed`` with the given options
    2. Call ``finalize()`` with received inputs and provider metadata
    3. Apply ``mutate_context`` if provided
    4. Call ``render_all()`` with extra context
    5. Apply ``filter_rendered`` if provided
    6. Call ``assert_snapshots()`` if ``snapshot_dir`` is provided
    7. Return ``(ctx, rendered)`` for extra assertions

    Example::

        opts = SnapshotRunOptions[MyProviderInputs](
            mode='root',
            received_inputs=[MyProviderInputs(flag=True)],
            local_files_dir=SNAPSHOT_DIR,
        )

        ctx, rendered = run_snapshot_case(
            MyProvider,
            options=opts,
            snapshot_dir=SNAPSHOT_DIR,
            filter_rendered=lambda out: include_paths(
                out,
                exact={'config.toml'},
                prefixes=('templates/',),
            ),
        )

        # Extra assertions beyond snapshot comparison
        assert 'expected_value' in rendered['config.toml']

    Args:
        provider_class: The concrete Provider subclass to test.
        options: Configuration for the snapshot run.
        snapshot_dir: Directory containing golden snapshot files.
            When provided, ``assert_snapshots()`` is called.
        filter_rendered: Optional filter applied to rendered output
            before snapshot comparison. Useful for mode-specific filtering
            or excluding generated paths.
        bed_kwargs: Additional keyword arguments passed to
            ``ProviderTestBed`` constructor for advanced customization.

    Returns:
        A tuple of ``(context, rendered)`` where:

        - ``context`` is the finalized provider context
        - ``rendered`` is the ``{dest_path: content}`` dict from rendering
    """
    # Build ProviderTestBed with explicit args, bed_kwargs for additional overrides
    # Use dict[str, Any] to allow flexible overriding via bed_kwargs
    bed_kwargs_merged: dict[str, Any] = {
        'provider_class': provider_class,
        'mode': options.mode,
        'preprocess': options.preprocess,
        'local_files_dir': options.local_files_dir,
    }
    if bed_kwargs:
        bed_kwargs_merged.update(bed_kwargs)

    bed = ProviderTestBed(**bed_kwargs_merged)

    # Finalize context with received inputs and provider metadata
    ctx = bed.finalize(
        received_inputs=options.received_inputs,
        all_providers=options.all_providers,
        provider_index=options.provider_index,
    )

    # Apply optional context mutator for one-off customizations
    if options.mutate_context is not None:
        options.mutate_context(ctx)

    # Render all templates
    rendered = bed.render_all(extra_context=options.extra_context)

    # Apply optional filter for mode-specific or path-based filtering
    if filter_rendered is not None:
        rendered = filter_rendered(rendered)

    # Assert against snapshots if directory provided
    if snapshot_dir is not None:
        assert_snapshots(rendered, snapshot_dir)

    return ctx, rendered  # type: ignore[return-value]
