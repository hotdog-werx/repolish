from pathlib import Path
from textwrap import dedent

from repolish.loader import create_providers


def test_file_mappings_receive_merged_context(tmp_path: Path):
    """A provider may use the merged context when creating file mappings.

    This test creates a provider that sets `readme_ext` via `create_context`
    and a `create_file_mappings` factory that builds the destination name
    using that value. The loader should call the factory with the merged
    context so the resulting mapping reflects the configured extension.
    """
    src = dedent(
        """
        def create_context():
            return {'readme_ext': 'txt'}

        def create_file_mappings(ctx):
            ext = ctx.get('readme_ext', 'md')
            return {f'README.{ext}': 'README_template'}
        """,
    )

    provider = tmp_path / 'prov'
    provider.mkdir()
    (provider / 'repolish.py').write_text(src)

    providers = create_providers([str(provider)])

    assert providers.file_mappings.get('README.txt') == 'README_template'
