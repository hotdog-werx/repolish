"""Entry point for the scaffold-provider CLI."""

from repolish.linker.decorator import resource_linker_cli

main = resource_linker_cli(
    resources_dir='resources',
    provider_root='templates',
)
