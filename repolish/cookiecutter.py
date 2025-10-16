from pathlib import Path, PurePosixPath

from .config import RepolishConfig
from .loader import Action, Decision, Providers, create_providers


def build_final_providers(config: RepolishConfig) -> Providers:
    """Build the final Providers object by merging provider contributions.

    - Loads providers from config.directories
    - Merges config.context over provider.context
    - Applies config.delete_files entries (with '!' negation) on top of
      provider decisions and records provenance Decisions for config entries
    """
    providers = create_providers(config.directories)

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
        # provenance source: config file path if set, else 'config'
        cfg_file = config.config_file
        src = cfg_file.as_posix() if isinstance(cfg_file, Path) else 'config'
        providers.delete_history.setdefault(p.as_posix(), []).append(
            Decision(source=src, action=(Action.keep if neg else Action.delete)),
        )

    # produce final Providers-like object
    return Providers(
        context=merged_context,
        anchors=providers.anchors,
        delete_files=list(delete_set),
        delete_history=providers.delete_history,
    )
