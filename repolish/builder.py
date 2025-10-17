import shutil
from pathlib import Path


def create_cookiecutter_template(
    staging_dir: Path,
    template_directories: list[Path],
) -> Path:
    """Create a cookiecutter template in a staging directory.

    Args:
        staging_dir: Path to the staging directory to create the templates.
        template_directories: List of template directories to copy into the
            staging directory. If multiple directories are provided, later
            directories will overwrite files from earlier ones.

    Returns:
        The Path to the staging directory containing the combined templates.
    """
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    for template_dir in template_directories:
        _copy_template_dir(template_dir, staging_dir)
    return staging_dir


def _copy_template_dir(template_dir: Path, staging_dir: Path) -> None:
    """Copy the contents of a template directory into the staging directory.

    Each provider is expected to have a `repolish/` subdirectory containing
    the project layout files. These will be copied over to the staging dir under
    the special folder `{{cookiecutter._repolish_project}}`.
    """
    repolish_dir = template_dir / 'repolish'
    if repolish_dir.exists() and repolish_dir.is_dir():
        dest_root = staging_dir / '{{cookiecutter._repolish_project}}'
        for item in repolish_dir.rglob('*'):
            rel = item.relative_to(repolish_dir)
            dest = dest_root / rel
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
