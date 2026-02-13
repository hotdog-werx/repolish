import json
from pathlib import Path

from cookiecutter.main import cookiecutter
from hotlog import get_logger

from repolish.loader import Providers

logger = get_logger(__name__)


def render_template(
    setup_input: Path,
    providers: Providers,
    setup_output: Path,
) -> None:
    """Run cookiecutter once on the merged template (setup_input) into setup_output."""
    # Dump the merged context into the merged template so cookiecutter can
    # read it from disk (avoids requiring each provider to ship cookiecutter.json).
    # Inject a special variable `_repolish_project` used by the staging step
    # so providers can place the project layout under a `repolish/` folder and
    # we copy it to `{{cookiecutter._repolish_project}}` in the staging dir.
    merged_ctx = dict(providers.context)
    # default project folder name used during generation
    merged_ctx.setdefault('_repolish_project', 'repolish')

    ctx_file = setup_input / 'cookiecutter.json'
    ctx_file.write_text(
        json.dumps(merged_ctx, ensure_ascii=False),
        encoding='utf-8',
    )

    cookiecutter(str(setup_input), no_input=True, output_dir=str(setup_output))
