from pathlib import Path
from textwrap import dedent

from repolish.loader import create_providers


def test_merge_strategy_context_drives_file_mappings(tmp_path: Path):
    """Integration-style test demonstrating derived context (merge strategy).

    - Provider A sends its ``preferred_source`` value to other providers via
      ``provide_inputs``.
    - Provider B receives the input, derives a ``merge_strategy`` in
      ``finalize_context``, and exposes a ``create_file_mappings`` factory
      that varies its output based on that derived value.

    This verifies the full class-based inter-provider communication path.
    """
    # Provider A: supplies preferred_source via provide_inputs (plain dict)
    a = dedent(
        """
        from repolish import BaseContext, Provider, BaseInputs

        class ACtx(BaseContext):
            preferred_source: str = 'provider_a'

        class A(Provider[ACtx, BaseInputs]):
            def get_provider_name(self):
                return 'prov_a'

            def create_context(self):
                return ACtx()

            def provide_inputs(self, own_context, all_providers, provider_index):
                # return a plain dict; the loader routes it by structural match
                return [{'preferred_source': own_context.preferred_source}]
        """,
    )

    # Provider B: receives preferred_source, derives merge_strategy, uses it
    # in create_file_mappings.
    b = dedent(
        """
        from pydantic import BaseModel
        from repolish import BaseContext, Provider, BaseInputs

        class PrefInput(BaseModel):
            preferred_source: str = 'unknown'

        class BCtx(BaseContext):
            merge_strategy: str = 'unknown'

        class B(Provider[BCtx, PrefInput]):
            def get_provider_name(self):
                return 'prov_b'

            def create_context(self):
                return BCtx()

            def get_inputs_schema(self):
                return PrefInput

            def finalize_context(self, own_context, received_inputs, all_providers, provider_index):
                if received_inputs:
                    preferred = received_inputs[0].preferred_source
                    strat = 'ours' if preferred == 'provider_a' else 'theirs'
                    return own_context.model_copy(update={'merge_strategy': strat})
                return own_context

            def create_file_mappings(self, context=None):
                strat = context.merge_strategy if context else 'unknown'
                return {f'config.merged.{strat}': 'config_template'}
        """,
    )

    pa = tmp_path / 'prov_a'
    pa.mkdir()
    (pa / 'repolish.py').write_text(a)

    pb = tmp_path / 'prov_b'
    pb.mkdir()
    (pb / 'repolish.py').write_text(b)

    providers = create_providers([str(pa), str(pb)])

    # Provider B's mapping key should reflect the strategy derived from A's input
    assert providers.file_mappings.get('config.merged.ours') == 'config_template'
