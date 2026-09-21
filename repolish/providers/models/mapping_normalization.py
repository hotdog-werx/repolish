from __future__ import annotations

from dataclasses import replace

from repolish.providers.models.files import FastLaneSpec, TemplateMapping
from repolish.providers.models.template_path import RepolishTemplatePath


def normalize_template_source(path: str | None) -> str | None:
    """Normalize a template source path to its staged logical name."""
    if path is None:
        return None
    return RepolishTemplatePath.from_string(path).logical_name


def normalize_mapping_entry(
    source: str | TemplateMapping,
    *,
    provider_id: str,
    keep_existing_source_provider: bool = False,
) -> TemplateMapping:
    """Return a normalized TemplateMapping for a lane/command mapping source.

    Normalization guarantees a shared invariant across collection and runtime
    paths: ``source_template`` and ``preprocessed_source`` are logical names
    (no trailing .jinja), and ``source_provider`` is set.
    """
    if isinstance(source, str):
        return TemplateMapping(
            source_template=normalize_template_source(source),
            source_provider=provider_id,
        )

    source_provider = source.source_provider
    if not (keep_existing_source_provider and source_provider):
        source_provider = provider_id

    return replace(
        source,
        source_template=normalize_template_source(source.source_template),
        preprocessed_source=normalize_template_source(
            source.preprocessed_source,
        ),
        source_provider=source_provider,
    )


def normalize_lane_spec_mappings(
    spec: FastLaneSpec,
    *,
    provider_id: str,
    keep_existing_source_provider: bool = False,
) -> FastLaneSpec:
    """Normalize only the mapping side of a FastLaneSpec."""
    return FastLaneSpec(
        file_mappings={
            dest: normalize_mapping_entry(
                src,
                provider_id=provider_id,
                keep_existing_source_provider=keep_existing_source_provider,
            )
            for dest, src in spec.file_mappings.items()
        },
        file_insertions={path: dict(funcs) for path, funcs in spec.file_insertions.items()},
        file_validators={path: dict(fns) for path, fns in spec.file_validators.items()},
        file_copies=list(spec.file_copies),
        source_provider=provider_id,
    )
