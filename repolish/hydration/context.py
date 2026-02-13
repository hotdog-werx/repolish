from pathlib import Path, PurePosixPath

from repolish.config import RepolishConfig
from repolish.loader import Action, Decision, Providers, create_providers


def _is_conditional_file(path_str: str) -> bool:
    """Check if a file's name starts with the _repolish. prefix.

    Conditional files are those with filenames starting with '_repolish.'
    regardless of where they are in the directory structure (e.g.,
    '_repolish.config.yml' or '.github/workflows/_repolish.ci.yml').

    Args:
        path_str: POSIX-style relative path

    Returns:
        True if the filename starts with '_repolish.'
    """
    filename = PurePosixPath(path_str).name
    return filename.startswith('_repolish.')


def build_final_providers(config: RepolishConfig) -> Providers:
    """Build the final Providers object by merging provider contributions.

    - Loads providers from config.directories
    - Merges config.context over provider.context
    - Applies config.delete_files entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries
    """
    providers = create_providers(
        [str(d) for d in config.directories],
        base_context=config.context,
        context_overrides=config.context_overrides,
    )

    # Merge contexts: config wins
    merged_context = {**providers.context, **config.context}

    # Start from provider delete decisions
    delete_set = set(providers.delete_files)

    cfg_delete = config.delete_files or []
    for raw in cfg_delete:
        neg = isinstance(raw, str) and raw.startswith('!')
        entry = raw[1:] if neg else raw
        p = Path(*PurePosixPath(entry).parts)
        if neg:
            delete_set.discard(p)
        else:
            delete_set.add(p)
        # provenance source: config dir path
        src = config.config_dir.as_posix()
        providers.delete_history.setdefault(p.as_posix(), []).append(
            Decision(
                source=src,
                action=(Action.keep if neg else Action.delete),
            ),
        )

    # produce final Providers-like object
    return Providers(
        context=merged_context,
        anchors=providers.anchors,
        delete_files=list(delete_set),
        delete_history=providers.delete_history,
        file_mappings=providers.file_mappings,
        create_only_files=providers.create_only_files,
    )
