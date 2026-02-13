import shutil
from pathlib import Path

from hotlog import get_logger

from repolish.config import RepolishConfig
from repolish.loader import Providers
from repolish.preprocessors import replace_text, safe_file_read

logger = get_logger(__name__)


def prepare_staging(config: RepolishConfig) -> tuple[Path, Path, Path]:
    """Compute and ensure staging dirs next to the config file.

    Returns: (base_dir, setup_input_path, setup_output_path)
    """
    base_dir = config.config_dir
    staging = base_dir / '.repolish'
    setup_input = staging / 'setup-input'
    setup_output = staging / 'setup-output'

    # clear output dir if present
    shutil.rmtree(setup_input, ignore_errors=True)
    shutil.rmtree(setup_output, ignore_errors=True)
    setup_input.mkdir(parents=True, exist_ok=True)
    setup_output.mkdir(parents=True, exist_ok=True)

    return base_dir, setup_input, setup_output


def preprocess_templates(
    setup_input: Path,
    providers: Providers,
    config: RepolishConfig,
    base_dir: Path,
) -> None:
    """Apply anchor-driven replacements to files under setup_input.

    Local project files used for anchor-driven overrides are resolved relative
    to `base_dir` (usually the directory containing the config file).
    """
    anchors_mapping = {**providers.anchors, **config.anchors}

    # Build reverse mapping for conditional files
    source_to_dest = {v: k for k, v in providers.file_mappings.items()}

    for tpl in setup_input.rglob('*'):
        if not tpl.is_file():
            continue
        try:
            tpl_text = tpl.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            # skip unreadable/binary files but log at debug level
            logger.debug(
                'skipping_unreadable_file',
                template_file=str(tpl),
                error=str(exc),
            )
            continue
        rel = tpl.relative_to(
            setup_input / '{{cookiecutter._repolish_project}}',
        )
        rel_str = rel.as_posix()
        # For conditional files, use the mapped destination as local path
        local_path = base_dir / source_to_dest[rel_str] if rel_str in source_to_dest else base_dir / rel
        local_text = safe_file_read(local_path)
        # Let replace_text raise if something unexpected happens; caller will log
        new_text = replace_text(
            tpl_text,
            local_text,
            anchors_dictionary=anchors_mapping,
        )
        if new_text != tpl_text:
            tpl.write_text(new_text, encoding='utf-8')
