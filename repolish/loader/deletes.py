from pathlib import Path, PurePosixPath

from repolish.loader.models import Action, Decision, FileMode, TemplateMapping


def process_delete_files(
    mappings: dict[str, str | TemplateMapping],
    delete_set: set[Path],
    provider_id: str,
    history: dict[str, list[Decision]],
) -> None:
    """Process a provider's delete and keep decisions from file mappings.

    Scans `mappings` (the return value of `provider.create_file_mappings()`)
    for `FileMode.DELETE` and `FileMode.KEEP` entries.

    - `FileMode.DELETE`: adds the path to `delete_set` and records an
      `Action.delete` provenance entry in `history`.
    - `FileMode.KEEP`: removes the path from `delete_set` and records
      `Action.keep`, allowing a later provider to cancel a delete scheduled
      by an earlier one.
    """
    for k, v in mappings.items():
        if not isinstance(v, TemplateMapping):
            continue
        if v.file_mode not in (FileMode.DELETE, FileMode.KEEP):
            continue
        p = Path(*PurePosixPath(k).parts)
        key = p.as_posix()
        if v.file_mode == FileMode.DELETE:
            delete_set.add(p)
            history.setdefault(key, []).append(
                Decision(source=provider_id, action=Action.delete),
            )
        else:  # FileMode.KEEP
            delete_set.discard(p)
            history.setdefault(key, []).append(
                Decision(source=provider_id, action=Action.keep),
            )
