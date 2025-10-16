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
    ignored_files = {'repolish.py'}
    for item in template_dir.rglob('*'):
        if item.name in ignored_files:
            continue
        relative_path = item.relative_to(template_dir)
        destination = staging_dir / relative_path
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
