from pathlib import Path
from textwrap import dedent

from repolish.loader import create_providers


def test_merge_strategy_context_drives_file_mappings(tmp_path: Path):
    """Integration-style test demonstrating derived context (merge strategy).

    - Provider A defines base configuration via `create_context()`.
    - Provider B reads the merged context and derives a `merge_strategy`
      variable (e.g. 'ours' vs 'theirs') and exposes a `create_file_mappings`
      factory that varies its output based on that derived value.

    The loader must call Provider B's factory with the merged context so that
    templates can adapt their behavior based on configuration provided by
    earlier providers (or the project config).
    """
    # Provider A: supplies a base config value
    a = dedent(
        """
        def create_context():
            return {'preferred_source': 'provider_a'}
        """,
    )

    # Provider B: derives 'merge_strategy' from merged context and produces
    # a mapping that embeds the strategy into the destination filename.
    b = dedent(
        """
        def create_context(ctx):
            # derive a merge_strategy based on existing merged values
            preferred = ctx.get('preferred_source')
            if preferred == 'provider_a':
                strat = 'ours'
            else:
                strat = 'theirs'
            return {'merge_strategy': strat}

        def create_file_mappings(ctx):
            strat = ctx.get('merge_strategy', 'unknown')
            # mapping key is destination file; value is source template name
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

    # Provider B's factory should see the merged context and expose a mapping
    # using the derived 'merge_strategy' value from Provider B's create_context.
    assert providers.file_mappings.get('config.merged.ours') == 'config_template'
