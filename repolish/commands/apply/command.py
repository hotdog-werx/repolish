# Shell module — kept for backward-compatible mock paths in tests.
# Functions live in session.py; imports below mirror session.py so that
# patches like `repolish.commands.apply.command.prepare_staging` still resolve.

from hotlog import get_logger  # noqa: F401

from repolish.commands.apply.check import CheckContext, _finish_check, _render_templates  # noqa: F401
from repolish.commands.apply.debug import _write_provider_debug_files  # noqa: F401
from repolish.commands.apply.display import _log_providers_summary  # noqa: F401
from repolish.commands.apply.options import ApplyOptions, ResolvedSession  # noqa: F401
from repolish.commands.apply.pipeline import resolve_session  # noqa: F401
from repolish.commands.apply.session import apply_session, run_session  # noqa: F401
from repolish.commands.apply.staging import _collect_excluded_sources, _create_staged_template  # noqa: F401
from repolish.commands.apply.symlinks import _apply_symlinks  # noqa: F401
from repolish.hydration import apply_generated_output, prepare_staging, preprocess_templates  # noqa: F401
from repolish.loader.models import build_file_records  # noqa: F401
from repolish.utils import run_post_process  # noqa: F401
from repolish.version import __version__  # noqa: F401
