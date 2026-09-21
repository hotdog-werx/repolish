"""Provider facets: contexts, routing, finalize distribution, collection, rendering.

Unit-level coverage exercises each phase directly with hand-built provider
and facet classes; the end-to-end case runs the real apply pipeline through
`apply_provider` with a two-facet provider and sender-delivered inputs.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
import textwrap
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest

from repolish.hydration.rendering import _facet_ctx_for_dest
from repolish.providers.contributions import (
    _handle_provider_facets,
)
from repolish.providers.finalize import (
    _finalize_facet_contexts,
    _partition_facet_inputs,
)
from repolish.providers.inputs import (
    _facet_emitted_inputs,
    _route_input_to_targets,
    _schema_matches,
    collect_all_emitted_inputs,
    gather_received_inputs,
)
from repolish.providers.models import (
    Accumulators,
    BaseContext,
    BaseInputs,
    FacetFinalizeOptions,
    FacetInputsOptions,
    FacetSpec,
    FacetSpecOptions,
    GlobalContext,
    Provider,
    ProviderEntry,
    ProviderFacet,
    SessionBundle,
    TemplateMapping,
    ValidationResult,
    ValidationStatus,
    WorkspaceContext,
    instantiate_facets,
)
from repolish.providers.pipeline import (
    _build_all_providers_list,
    _populate_facet_contexts,
)
from repolish.testing import apply_provider

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


# ---------------------------------------------------------------------------
# Shared fixture classes
# ---------------------------------------------------------------------------


class AlphaCtx(BaseContext):
    """Facet context with a field finalize writes into."""

    text: str = '(none)'


class AlphaInputs(BaseInputs):
    """Payload senders construct to reach the alpha facet."""

    text: str = ''


class BetaCtx(BaseContext):
    title: str = 'plain'


class BetaInputs(BaseInputs):
    """All-default sibling schema: must never steal a payload."""


class ForeignInputs(BaseInputs):
    """Matches no schema on the provider: must stay with the provider."""

    tag: str = ''


class AlphaFacet(ProviderFacet[AlphaCtx, AlphaInputs]):
    name = 'alpha'

    def finalize_context(
        self,
        opt: FacetFinalizeOptions[AlphaCtx, AlphaInputs],
    ) -> AlphaCtx:
        if opt.received_inputs:
            opt.own_context.text = opt.received_inputs[-1].text
        return opt.own_context

    def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
        return FacetSpec(
            file_mappings={'alpha.txt': 'alpha.txt.jinja'},
        )


class BetaFacet(ProviderFacet[BetaCtx, BetaInputs]):
    name = 'beta'

    def create_spec(self, opt: FacetSpecOptions[BetaCtx]) -> FacetSpec:
        return FacetSpec(
            file_mappings={'beta.txt': 'beta.txt.jinja'},
        )


class OwnCtx(BaseContext):
    own_value: str = 'untouched'


class OwnInputs(BaseInputs):
    value: str = ''


class FacetsProvider(Provider[OwnCtx, OwnInputs]):
    facets: ClassVar[list[type[ProviderFacet[Any, Any]]]] = [
        AlphaFacet,
        BetaFacet,
    ]

    def create_context(self) -> OwnCtx:
        return OwnCtx()


def _entry(
    pid: str,
    own_schema: type[BaseInputs] | None = None,
    extra_schemas: list[type[BaseInputs]] | None = None,
) -> ProviderEntry:
    return ProviderEntry(
        provider_id=pid,
        alias=pid,
        input_type=own_schema,
        input_types=[s for s in [own_schema, *(extra_schemas or [])] if s is not None],
    )


# ---------------------------------------------------------------------------
# Facet contract defaults
# ---------------------------------------------------------------------------


def test_instantiate_facets_copies_templates_root(tmp_path: Path) -> None:
    inst = FacetsProvider()
    inst.templates_root = tmp_path
    facets = instantiate_facets(inst)
    assert [f.name for f in facets] == ['alpha', 'beta']
    assert all(f.templates_root == tmp_path for f in facets)


def test_provider_without_facets_yields_empty_list() -> None:
    class Plain(Provider[OwnCtx, OwnInputs]):
        def create_context(self) -> OwnCtx:
            return OwnCtx()

    assert instantiate_facets(Plain()) == []


def test_facet_context_and_schema_inference() -> None:
    inst = FacetsProvider()
    facets = {f.name: f for f in instantiate_facets(inst)}
    assert isinstance(facets['alpha'].create_context(), AlphaCtx)
    assert facets['alpha'].get_inputs_schema() is AlphaInputs
    assert isinstance(facets['beta'].create_context(), BetaCtx)
    assert facets['beta'].get_inputs_schema() is BetaInputs


def test_facet_schema_excluded_for_base_inputs() -> None:
    class NoInputsFacet(ProviderFacet[AlphaCtx, BaseInputs]):
        name = 'noinputs'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec()

    assert NoInputsFacet().get_inputs_schema() is None


def test_facet_context_defaults_to_base_context() -> None:
    class Bare(ProviderFacet):
        name = 'bare'

        def create_spec(self, opt: FacetSpecOptions[BaseContext]) -> FacetSpec:
            return FacetSpec()

    ctx = Bare().create_context()
    assert isinstance(ctx, BaseContext)


def test_facet_without_generic_args_has_no_input_schema() -> None:
    class Bare(ProviderFacet):
        name = 'bare'

        def create_spec(self, opt: FacetSpecOptions[BaseContext]) -> FacetSpec:
            return FacetSpec()

    assert Bare().get_inputs_schema() is None


def test_facet_context_instantiation_failure_falls_back() -> None:
    class RequiredCtx(BaseContext):
        """No defaults: instantiating without arguments must fail."""

        value: int

    class StrictFacet(ProviderFacet[RequiredCtx, AlphaInputs]):
        name = 'strict'

        def create_spec(self, opt: FacetSpecOptions[RequiredCtx]) -> FacetSpec:
            return FacetSpec()

    ctx = StrictFacet().create_context()
    assert type(ctx) is BaseContext


# ---------------------------------------------------------------------------
# Context population
# ---------------------------------------------------------------------------


def test_populate_facet_contexts_injects_identity(tmp_path: Path) -> None:
    inst = FacetsProvider()
    inst.alias = 'facets'
    contexts: dict[str, BaseContext] = {'facets': OwnCtx()}
    _populate_facet_contexts(
        inst,
        'facets',
        contexts,
        GlobalContext(
            workspace=WorkspaceContext(mode='standalone', root_dir=tmp_path),
        ),
    )
    own = contexts['facets']
    assert set(own.facets) == {'alpha', 'beta'}
    assert isinstance(own.facets['alpha'], AlphaCtx)
    # Facets ride the provider identity: repolish carries the provider's
    # alias and session, so mode branching works inside facet code.
    assert own.facets['alpha'].repolish.provider.alias == 'facets'
    assert own.facets['alpha'].repolish.workspace.mode == 'standalone'


def test_duplicate_facet_names_raise() -> None:
    class DupA(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'same'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec()

    class DupB(DupA):
        pass

    class DupProvider(FacetsProvider):
        facets: ClassVar[list] = [DupA, DupB]

    contexts: dict[str, BaseContext] = {'dup': OwnCtx()}
    with pytest.raises(ValueError, match='duplicate facet name'):
        _populate_facet_contexts(
            DupProvider(),
            'dup',
            contexts,
            GlobalContext(),
        )


def test_facet_create_context_failure_skips_facet(tmp_path: Path) -> None:
    class Broken(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'broken'

        def create_context(self) -> AlphaCtx:
            msg = 'boom'
            raise RuntimeError(msg)

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec()

    class Partial(FacetsProvider):
        facets: ClassVar[list] = [Broken, AlphaFacet]

    inst = Partial()
    inst.alias = 'partial'
    contexts: dict[str, BaseContext] = {'partial': OwnCtx()}
    _populate_facet_contexts(
        inst,
        'partial',
        contexts,
        GlobalContext(
            workspace=WorkspaceContext(mode='standalone', root_dir=tmp_path),
        ),
    )
    # One broken facet must not stop the run: it is skipped, its healthy
    # sibling still populates.
    assert set(contexts['partial'].facets) == {'alpha'}


# ---------------------------------------------------------------------------
# Routing and finalize distribution
# ---------------------------------------------------------------------------


def test_payload_reaches_only_schema_matching_facet() -> None:
    received: dict[str, list[BaseInputs]] = {}
    entry = _entry('p', OwnInputs, [AlphaInputs, BetaInputs])
    _route_input_to_targets(AlphaInputs(text='hi'), [entry], received)
    _route_input_to_targets(OwnInputs(value='own'), [entry], received)
    assert received['p'] == [AlphaInputs(text='hi'), OwnInputs(value='own')]


def test_structural_fallback_stays_provider_only() -> None:
    """An all-default facet model must not catch a structurally matching payload."""

    class Lookalike(BaseInputs):
        """Structurally compatible with BetaInputs, loaded from elsewhere."""

        title: str = 'plain'

    received: dict[str, list[BaseInputs]] = {}
    # No provider-level schema: only the facet schemas are consulted, and
    # those match by exact isinstance only.
    entry = _entry('p', None, [AlphaInputs, BetaInputs])
    _route_input_to_targets(Lookalike(), [entry], received)
    assert received == {}


def test_structural_fallback_delivers_to_provider() -> None:
    """The provider's own schema still accepts structurally identical payloads."""

    class Lookalike(BaseInputs):
        """Structurally identical to OwnInputs but a distinct class."""

        value: str = ''

    received: dict[str, list[BaseInputs]] = {}
    entry = _entry('p', OwnInputs)
    _route_input_to_targets(Lookalike(value='twin'), [entry], received)
    assert received['p'] == [Lookalike(value='twin')]


def test_schema_matches_exact_structural_and_rejected() -> None:
    """`_schema_matches` accepts exact and structural matches, rejects the rest."""

    class PickyInputs(BaseInputs):
        """Required field: structurally different payloads fail validation."""

        value: int

    class TwinInputs(BaseInputs):
        """Structurally identical to PickyInputs but a distinct class."""

        value: int = 0

    assert _schema_matches(PickyInputs, PickyInputs(value=3))
    assert _schema_matches(PickyInputs, TwinInputs(value=3))
    assert not _schema_matches(PickyInputs, AlphaInputs(text='no value here'))


def test_facet_emitted_inputs_skip_missing_context() -> None:
    class EmittingFacet(AlphaFacet):
        def provide_inputs(
            self,
            opt: FacetInputsOptions[AlphaCtx],
        ) -> list[AlphaInputs]:
            return [AlphaInputs(text='from-facet')]

    class Sender(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [EmittingFacet]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    # The facet declared but its context never created: no payload, no crash.
    assert (
        _facet_emitted_inputs(
            0,
            'sender',
            Sender(),
            {'sender': OwnCtx()},
            [],
        )
        == []
    )


def test_collect_all_emitted_inputs_includes_facet_payloads() -> None:
    class EmittingFacet(AlphaFacet):
        def provide_inputs(
            self,
            opt: FacetInputsOptions[AlphaCtx],
        ) -> list[AlphaInputs]:
            return [AlphaInputs(text='dry-pass')]

    class Sender(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [EmittingFacet]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    inst = Sender()
    provider_contexts: dict[str, BaseContext] = {'sender': OwnCtx()}
    _populate_facet_contexts(inst, 'sender', provider_contexts, GlobalContext())
    module_cache: list[tuple[str, dict]] = [('sender', {})]
    instances: list[Provider[Any, Any] | None] = [inst]
    all_providers = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
    )

    flat = collect_all_emitted_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers,
    )
    assert flat == [AlphaInputs(text='dry-pass')]


def test_partition_facet_inputs() -> None:
    facets = [AlphaFacet(), BetaFacet()]
    raw: list[BaseInputs] = [
        OwnInputs(value='a'),
        AlphaInputs(text='x'),
        BetaInputs(),
    ]
    own, by_facet = _partition_facet_inputs(facets, OwnInputs, raw)
    # Own exact match goes to the provider; each facet schema claims its
    # own payloads; anything unrecognized remains with the provider.
    assert own == [OwnInputs(value='a')]
    assert by_facet == {
        'alpha': [AlphaInputs(text='x')],
        'beta': [BetaInputs()],
    }


def test_partition_without_own_schema() -> None:
    facets = [AlphaFacet(), BetaFacet()]
    own, by_facet = _partition_facet_inputs(facets, None, [AlphaInputs()])
    # Without the provider's own schema the payload cannot exact-match it;
    # facet schemas still claim theirs.
    assert own == []
    assert by_facet == {'alpha': [AlphaInputs()]}


def test_partition_leaves_unmatched_payload_with_provider() -> None:
    own, by_facet = _partition_facet_inputs(
        [AlphaFacet(), BetaFacet()],
        OwnInputs,
        [ForeignInputs(tag='unknown')],
    )
    # No facet schema claims it and it is not the provider's own schema:
    # it stays with the provider, preserving the pre-facet behavior for
    # payloads delivered through the structural fallback.
    assert own == [ForeignInputs(tag='unknown')]
    assert by_facet == {}


def test_finalize_facet_contexts_writes_subset_back() -> None:
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx()
    own.facets['beta'] = BetaCtx()
    by_facet: dict[str, list[BaseInputs]] = {
        'alpha': [AlphaInputs(text='delivered')],
    }
    _finalize_facet_contexts(
        [AlphaFacet(), BetaFacet()],
        'p',
        own,
        by_facet,
        [],
        0,
        None,
    )
    assert own.facets['alpha'].text == 'delivered'
    assert own.facets['beta'].title == 'plain'


def test_broken_facet_finalize_keeps_context() -> None:
    class Broken(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'broken'

        def finalize_context(
            self,
            opt: FacetFinalizeOptions[AlphaCtx, AlphaInputs],
        ) -> AlphaCtx:
            msg = 'boom'
            raise RuntimeError(msg)

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec()

    own = OwnCtx()
    own.facets['broken'] = AlphaCtx(text='pre-finalize')
    _finalize_facet_contexts(
        [Broken()],
        'p',
        own,
        {'broken': [AlphaInputs()]},
        [],
        0,
        None,
    )
    assert own.facets['broken'].text == 'pre-finalize'


def test_finalize_skips_facets_without_contexts() -> None:
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx()
    # 'beta' has no context (creation failed earlier, say): it is skipped
    # while 'alpha' still finalizes.
    _finalize_facet_contexts(
        [AlphaFacet(), BetaFacet()],
        'p',
        own,
        {},
        [],
        0,
        None,
    )
    assert 'beta' not in own.facets


def test_finalize_accepts_non_model_facet_context() -> None:
    """A facet may keep a plain mapping as its context; it rides through."""

    class PlainFacet(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'plain'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec()

    own = OwnCtx()
    own.facets['plain'] = cast('BaseContext', {'kind': 'mapping'})
    _finalize_facet_contexts(
        [PlainFacet()],
        'p',
        own,
        {},
        [],
        0,
        None,
    )
    # The default finalize returns the mapping unchanged; non-BaseContext
    # results are not written back, so the value survives as-is.
    assert own.facets['plain'] == {'kind': 'mapping'}


def test_facet_emitted_inputs_route_to_peer_entries() -> None:
    """A facet's provide_inputs output enters the routing pool like a provider's."""

    class EmittingFacet(AlphaFacet):
        def provide_inputs(
            self,
            opt: FacetInputsOptions[AlphaCtx],
        ) -> list[AlphaInputs]:
            return [AlphaInputs(text='from-facet')]

    class Sender(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [EmittingFacet]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    class Receiver(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [AlphaFacet]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    module_cache: list[tuple[str, dict]] = [('sender', {}), ('receiver', {})]
    sender_inst, receiver_inst = Sender(), Receiver()
    sender_inst.alias = 'sender'
    receiver_inst.alias = 'receiver'
    instances: list[Provider[Any, Any] | None] = [sender_inst, receiver_inst]
    provider_contexts: dict[str, BaseContext] = {
        'sender': OwnCtx(),
        'receiver': OwnCtx(),
    }
    for pid, inst in (('sender', sender_inst), ('receiver', receiver_inst)):
        _populate_facet_contexts(inst, pid, provider_contexts, GlobalContext())

    all_providers = _build_all_providers_list(
        module_cache,
        instances,
        provider_contexts,
    )
    received = gather_received_inputs(
        module_cache,
        instances,
        provider_contexts,
        all_providers,
    )
    # The sender's facet payload reaches the receiver (and the sender
    # itself, since routing delivers to every schema-matching provider).
    assert received['receiver'] == [AlphaInputs(text='from-facet')]
    assert received['sender'] == [AlphaInputs(text='from-facet')]


# ---------------------------------------------------------------------------
# Spec collection
# ---------------------------------------------------------------------------


def _provider_with_facet_contexts() -> tuple[FacetsProvider, OwnCtx]:
    inst = FacetsProvider()
    inst.alias = 'facets-provider'
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx()
    own.facets['beta'] = BetaCtx()
    return inst, own


def test_facet_contributions_land_in_bundle() -> None:
    inst, own = _provider_with_facet_contexts()
    accum = Accumulators()
    _handle_provider_facets(inst, own, 'facets', accum, regular_dests=set())
    assert set(accum.merged_file_mappings) == {'alpha.txt', 'beta.txt'}
    alpha = accum.merged_file_mappings['alpha.txt']
    assert isinstance(alpha, TemplateMapping)
    assert alpha.source_template == 'alpha.txt'
    assert alpha.source_provider == 'facets'
    assert accum.facet_owners == {
        'alpha.txt': ('facets', 'alpha'),
        'beta.txt': ('facets', 'beta'),
    }


def test_facet_insertions_and_validators_collect() -> None:
    def render_tag() -> str:
        return 'tagged'

    def check_ok(
        context: object,
        path: object,
    ) -> object:  # pragma: no cover - not invoked
        return ValidationResult(
            status=ValidationStatus.PASS,
            message='ok',
            validator_name='check_ok',
        )

    class RichFacet(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'rich'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec(
                file_insertions={'dev.txt': {'render-tag': render_tag}},
                file_validators={'dev.txt': {'check-ok': check_ok}},
            )

    class RichProvider(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [RichFacet]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    inst = RichProvider()
    inst.alias = 'rich'
    own = OwnCtx()
    own.facets['rich'] = AlphaCtx()
    accum = Accumulators()
    _handle_provider_facets(inst, own, 'rich', accum, regular_dests=set())
    assert 'render-tag' in accum.file_insertions['dev.txt']
    assert 'rich:render-tag' in accum.file_insertions['dev.txt']
    # Insertions bind to the facet's own context.
    bound = accum.file_insertions['dev.txt']['render-tag']
    assert callable(bound)
    assert set(accum.file_validators['dev.txt']) == {'check-ok'}
    assert accum.validator_sources['dev.txt'] == 'rich'


def test_facet_without_context_is_skipped_at_collection() -> None:
    inst, own = _provider_with_facet_contexts()
    # 'beta' has no context (creation failed earlier, say): only the facets
    # with contexts contribute.
    del own.facets['beta']
    accum = Accumulators()
    _handle_provider_facets(inst, own, 'facets', accum, regular_dests=set())
    assert set(accum.merged_file_mappings) == {'alpha.txt'}


def test_broken_create_spec_is_skipped_with_warning() -> None:
    class BrokenSpec(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'alpha'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            msg = 'boom'
            raise RuntimeError(msg)

    class WithBroken(FacetsProvider):
        facets: ClassVar[list] = [BrokenSpec, BetaFacet]

    inst = WithBroken()
    inst.alias = 'broken-spec'
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx()
    own.facets['beta'] = BetaCtx()
    accum = Accumulators()
    _handle_provider_facets(
        inst,
        own,
        'broken-spec',
        accum,
        regular_dests=set(),
    )
    # The broken facet contributed nothing; its healthy sibling did.
    assert set(accum.merged_file_mappings) == {'beta.txt'}
    assert accum.facet_owners == {'beta.txt': ('broken-spec', 'beta')}


def test_facet_vs_regular_collision_raises() -> None:
    class Colliding(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'alpha'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec(file_mappings={'README.md': 'README.md.jinja'})

    class CollidingProvider(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [Colliding]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    inst = CollidingProvider()
    inst.alias = 'colliding'
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx()
    accum = Accumulators()
    with pytest.raises(ValueError, match='regular hooks'):
        _handle_provider_facets(
            inst,
            own,
            'colliding',
            accum,
            regular_dests={'README.md'},
        )


def test_facet_vs_facet_collision_raises() -> None:
    class Left(ProviderFacet[AlphaCtx, AlphaInputs]):
        name = 'left'

        def create_spec(self, opt: FacetSpecOptions[AlphaCtx]) -> FacetSpec:
            return FacetSpec(file_mappings={'shared.txt': 'left.txt.jinja'})

    class Right(ProviderFacet[BetaCtx, BetaInputs]):
        name = 'right'

        def create_spec(self, opt: FacetSpecOptions[BetaCtx]) -> FacetSpec:
            return FacetSpec(file_mappings={'shared.txt': 'right.txt.jinja'})

    class Overlapping(Provider[OwnCtx, OwnInputs]):
        facets: ClassVar[list] = [Left, Right]

        def create_context(self) -> OwnCtx:
            return OwnCtx()

    inst = Overlapping()
    inst.alias = 'overlap'
    own = OwnCtx()
    own.facets['left'] = AlphaCtx()
    own.facets['right'] = BetaCtx()
    with pytest.raises(ValueError, match='sibling facet'):
        _handle_provider_facets(
            inst,
            own,
            'overlap',
            Accumulators(),
            regular_dests=set(),
        )


# ---------------------------------------------------------------------------
# Rendering injection
# ---------------------------------------------------------------------------


def test_facet_ctx_for_dest_owns_only_mapped_files() -> None:
    own = OwnCtx()
    own.facets['alpha'] = AlphaCtx(text='owned')
    bundle = SessionBundle(
        provider_contexts={'p': own},
        facet_owners={'alpha.txt': ('p', 'alpha')},
    )
    facet_dump = _facet_ctx_for_dest('alpha.txt', bundle)
    assert facet_dump is not None
    assert facet_dump['text'] == 'owned'
    assert facet_dump['facets'] == {}
    assert _facet_ctx_for_dest('unowned.txt', bundle) is None


def test_facet_ctx_for_dest_tolerates_missing_owners() -> None:
    ghost_provider = SessionBundle(
        provider_contexts={},
        facet_owners={'alpha.txt': ('ghost', 'alpha')},
    )
    assert _facet_ctx_for_dest('alpha.txt', ghost_provider) is None

    missing_facet = SessionBundle(
        provider_contexts={'p': OwnCtx()},
        facet_owners={'alpha.txt': ('p', 'alpha')},
    )
    assert _facet_ctx_for_dest('alpha.txt', missing_facet) is None


# ---------------------------------------------------------------------------
# End to end: two facets, sender-delivered input, cross-file sibling access
# ---------------------------------------------------------------------------

_counter = itertools.count()


def _load_module(path: Path) -> ModuleType:
    name = f'_facet_e2e_provider_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_FACET_PROVIDER = """\
    from repolish import (
        BaseContext,
        BaseInputs,
        FacetFinalizeOptions,
        FacetSpec,
        FacetSpecOptions,
        Provider,
        ProviderFacet,
    )

    class Ctx(BaseContext):
        pass

    class NotesInputs(BaseInputs):
        text: str = ''

    class NotesCtx(BaseContext):
        text: str = '(none)'

    class NotesFacet(ProviderFacet[NotesCtx, NotesInputs]):
        name = 'notes'

        def finalize_context(self, opt):
            if opt.received_inputs:
                opt.own_context.text = opt.received_inputs[-1].text
            return opt.own_context

        def create_spec(self, opt):
            return FacetSpec(file_mappings={'NOTES.md': 'NOTES.md.jinja'})

    class HeaderCtx(BaseContext):
        title: str = 'plain'

    class HeaderFacet(ProviderFacet[HeaderCtx, BaseInputs]):
        name = 'header'

        def create_spec(self, opt):
            return FacetSpec(file_mappings={'HEADER.txt': 'HEADER.txt.jinja'})

    class P(Provider[Ctx, BaseInputs]):
        facets = [NotesFacet, HeaderFacet]

        def create_context(self):
            return Ctx()
    """


def test_two_facet_provider_end_to_end(tmp_path: Path) -> None:
    provider_root = tmp_path / 'pkg' / 'resources' / 'templates'
    (provider_root / 'repolish').mkdir(parents=True)
    (provider_root / 'repolish.py').write_text(
        textwrap.dedent(_FACET_PROVIDER),
        encoding='utf-8',
    )
    templates = {
        'NOTES.md.jinja': 'note: {{ facet.text }}\n',
        'HEADER.txt.jinja': 'title: {{ facet.title }}\nnote: {{ facets.notes.text }}\n',
    }
    for name, content in templates.items():
        (provider_root / 'repolish' / name).write_text(
            textwrap.dedent(content),
            encoding='utf-8',
        )
    mod = _load_module(provider_root / 'repolish.py')
    provider_cls = next(
        val
        for val in vars(mod).values()
        if isinstance(val, type) and val.__module__ == mod.__name__ and hasattr(val, 'create_context')
    )
    project = tmp_path / 'project'
    project.mkdir()

    result = apply_provider(
        provider_cls,
        project,
        alias='demo',
        extra_inputs=[mod.NotesInputs(text='from-sender')],
    )

    assert result.exit_code == 0
    assert result.apply_result == {
        'HEADER.txt': 'written',
        'NOTES.md': 'written',
    }
    # The facet shorthand resolves on the owning file only...
    assert (project / 'NOTES.md').read_text(
        encoding='utf-8',
    ) == 'note: from-sender\n'
    # ...while the sibling map is readable from any of the provider's files.
    assert (project / 'HEADER.txt').read_text(encoding='utf-8') == ('title: plain\nnote: from-sender\n')
